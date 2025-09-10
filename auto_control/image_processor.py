import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from airtest import aircv
from airtest.core.cv import Template

# 导入配置
from .config import (
    ScaleStrategy, MatchMethod, TEMPLATE_DIR, AUTO_LOAD_TEMPLATES,
    TEMPLATE_EXTENSIONS, TEMPLATE_ROI_CONFIG, DEFAULT_RESOLUTION,
    DEFAULT_THRESHOLD, DEFAULT_SCALE_STRATEGY, DEFAULT_MATCH_METHOD, MAX_WORKERS
)


# 数据类定义
@dataclass
class MatchResult:
    """匹配结果数据类"""
    name: str
    position: Optional[Tuple[int, int]]
    confidence: float
    template: Optional[Template] = None


@dataclass
class TemplateInfo:
    """模板信息数据类"""
    name: str
    template: Template
    path: str
    roi: Optional[Tuple[float, float, float, float]] = None
    threshold: float = DEFAULT_THRESHOLD
    scale_strategy: ScaleStrategy = DEFAULT_SCALE_STRATEGY
    last_resolution: Optional[Tuple[int, int]] = None


class ImageProcessor:
    def __init__(
        self,
        base_resolution: Tuple[int, int] = DEFAULT_RESOLUTION,
        max_workers: int = MAX_WORKERS,
        template_dir: Optional[str] = None,
        auto_load: bool = AUTO_LOAD_TEMPLATES,
        logger=None
    ):
        """
        初始化图像处理器
        
        Args:
            base_resolution: 设计基准分辨率 (宽, 高)
            max_workers: 线程池最大工作线程数
            template_dir: 模板目录路径
            auto_load: 是否自动加载模板
            logger: 日志实例（从上层传递）
        """
        self.base_resolution = base_resolution
        self.templates: Dict[str, TemplateInfo] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        self.template_dir = template_dir or TEMPLATE_DIR
        # 初始化日志系统（支持降级）
        self.logger = logger if logger else self._create_default_logger()

        if auto_load:
            self.load_templates_from_dir(
                dir_path=self.template_dir,
                extensions=TEMPLATE_EXTENSIONS,
                roi_config=TEMPLATE_ROI_CONFIG
            )
        
        self.logger.info(
            f"图像处理器初始化完成 | 基准分辨率: {base_resolution} | "
            f"模板目录: {self.template_dir} | 自动加载: {auto_load}"
        )

    def _create_default_logger(self):
        """无日志实例时的降级实现"""
        class DefaultLogger:
            @staticmethod
            def debug(msg):
                print(f"[DEBUG] ImageProcessor: {msg}")
            
            @staticmethod
            def info(msg):
                print(f"[INFO] ImageProcessor: {msg}")
            
            @staticmethod
            def warning(msg):
                print(f"[WARNING] ImageProcessor: {msg}")
            
            @staticmethod
            def error(msg, exc_info=False):
                print(f"[ERROR] ImageProcessor: {msg}")
        
        return DefaultLogger()

    def _timing_decorator(func):
        """计时装饰器"""
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start_time = time.time()
            result = func(self, *args, **kwargs)
            elapsed = time.time() - start_time
            self.logger.debug(f"{func.__name__} 执行时间: {elapsed:.3f}秒")
            return result
        return wrapper

    def list_templates(self) -> List[str]:
        """列出所有已加载的模板名称"""
        return list(self.templates.keys())

    def remove_template(self, template_name: str) -> bool:
        """移除指定的模板"""
        if template_name in self.templates:
            del self.templates[template_name]
            self.logger.info(f"已移除模板: {template_name}")
            return True
        else:
            self.logger.warning(f"尝试移除不存在的模板: {template_name}")
            return False

    def clear_templates(self) -> None:
        """清除所有模板"""
        count = len(self.templates)
        self.templates.clear()
        self.logger.info(f"已清除所有模板 | 数量: {count}")

    def load_templates_from_dir(
            self,
            dir_path: str,
            extensions: Tuple[str, ...] = TEMPLATE_EXTENSIONS,
            recursive: bool = True,
            roi_config: Optional[Dict[str, Tuple[float, float, float, float]]] = None,
            threshold: float = DEFAULT_THRESHOLD,
            scale_strategy: ScaleStrategy = DEFAULT_SCALE_STRATEGY
        ) -> Dict[str, Template]:
        """从目录加载所有图片作为模板（包含子目录）"""
        if not os.path.exists(dir_path):
            self.logger.warning(f"模板目录不存在: {dir_path}")
            return {}

        loaded = {}
        total_loaded = 0
        total_failed = 0

        # 遍历目录及子目录中的所有文件
        for root, _, files in os.walk(dir_path):
            if not recursive and root != dir_path:
                continue  # 非递归模式时跳过子目录
                
            for file_name in files:
                if file_name.lower().endswith(extensions):
                    file_path = os.path.join(root, file_name)
                    
                    # 生成相对路径作为模板名（保留目录结构）
                    rel_path = os.path.relpath(file_path, start=dir_path)
                    template_name = os.path.splitext(rel_path)[0].replace('\\', '/')
                    
                    try:
                        template = self.load_template(
                            name=template_name,
                            path=file_path,
                            roi=roi_config.get(template_name) if roi_config else None,
                            threshold=threshold,
                            scale_strategy=scale_strategy
                        )
                        loaded[template_name] = template
                        total_loaded += 1
                    except Exception as e:
                        self.logger.error(f"加载模板失败 {template_name}: {str(e)}")
                        total_failed += 1

        self.logger.info(
            f"模板加载完成 | 目录: {dir_path} | "
            f"成功: {total_loaded} | 失败: {total_failed} | 总计: {total_loaded + total_failed}"
        )
        return loaded

    def __del__(self):
        # 先记录释放信息（使用同步方式）
        if hasattr(self.logger, 'logger'):
            # 如果是标准logger，直接调用同步方法
            self.logger.logger.debug("图像处理器资源已释放")
        else:
            # 如果是降级logger，直接调用方法
            self.logger.debug("图像处理器资源已释放")
        
        # 然后关闭线程池
        self.executor.shutdown()

    def update_resolution(self, new_resolution: Tuple[int, int]) -> None:
        """更新基准分辨率"""
        if new_resolution == self.base_resolution:
            self.logger.debug(f"分辨率未变化，无需更新: {new_resolution}")
            return

        self.base_resolution = new_resolution
        # 重置所有模板的分辨率缓存
        for name in self.templates:
            self.templates[name].last_resolution = None
        
        self.logger.info(f"基准分辨率已更新为: {new_resolution}")

    def load_template(
        self,
        name: str,
        path: str,
        roi: Optional[Tuple[float, float, float, float]] = None,
        threshold: float = DEFAULT_THRESHOLD,
        scale_strategy: ScaleStrategy = DEFAULT_SCALE_STRATEGY
    ) -> Template:
        """
        加载模板图像
        
        Args:
            name: 模板名称
            path: 模板文件路径
            roi: 感兴趣区域 (x1, y1, x2, y2)，范围0-1
            threshold: 匹配阈值
            scale_strategy: 缩放策略
            
        Returns:
            Template: Airtest模板对象
            
        Raises:
            ValueError: 当图像加载失败时
        """
        try:
            # 验证图像文件是否存在
            if not os.path.isfile(path):
                raise ValueError(f"模板文件不存在: {path}")

            # 尝试读取图像数据
            img = aircv.imread(path)
            if img is None:
                raise ValueError(f"无法读取图像文件: {path}")

            # 创建模板对象
            template = Template(filename=path, threshold=threshold)

            # 保存模板信息
            self.templates[name] = TemplateInfo(
                name=name,
                template=template,
                path=path,
                roi=roi,
                threshold=threshold,
                scale_strategy=scale_strategy
            )

            self.logger.debug(f"模板加载成功: {name} (路径: {path})")
            return template

        except Exception as e:
            self.logger.error(f"加载模板 '{name}' 失败", exc_info=True)
            raise ValueError(f"模板加载失败: {str(e)}") from e
    
    def get_template(self, template_name: str) -> Optional[Template]:
        """根据模板名称获取模板对象"""
        template_info = self.templates.get(template_name)
        if template_info is None:
            self.logger.warning(f"模板 '{template_name}' 未加载")
            return None
        
        self.logger.debug(f"获取模板成功: {template_name}")
        return template_info.template

    def _scale_image(
        self,
        image: np.ndarray,
        target_resolution: Tuple[int, int],
        scale_strategy: ScaleStrategy
    ) -> np.ndarray:
        """根据策略缩放图像"""
        base_w, base_h = DEFAULT_RESOLUTION
        target_w, target_h = target_resolution

        if scale_strategy == ScaleStrategy.FIT:
            scale = min(target_w / base_w, target_h / base_h)
            scaled_img = cv2.resize(image, None, fx=scale, fy=scale)
        elif scale_strategy == ScaleStrategy.STRETCH:
            scaled_img = cv2.resize(image, (target_w, target_h))
        elif scale_strategy == ScaleStrategy.CROP:
            scale = max(target_w / base_w, target_h / base_h)
            scaled_img = cv2.resize(image, None, fx=scale, fy=scale)
            h, w = scaled_img.shape[:2]
            crop_x = max(0, (w - target_w) // 2)
            crop_y = max(0, (h - target_h) // 2)
            scaled_img = scaled_img[crop_y:crop_y+target_h, crop_x:crop_x+target_w]
        else:
            scale = min(target_w / base_w, target_h / base_h)
            scaled_img = cv2.resize(image, None, fx=scale, fy=scale)

        self.logger.debug(
            f"图像缩放完成 | 原始分辨率: {DEFAULT_RESOLUTION} | "
            f"目标分辨率: {target_resolution} | 策略: {scale_strategy.name}"
        )
        return scaled_img

    def _convert_roi(
        self,
        original_roi: Optional[Tuple[float, float, float, float]],
        from_resolution: Tuple[int, int],
        to_resolution: Tuple[int, int]
    ) -> Optional[Tuple[float, float, float, float]]:
        """转换ROI坐标到新分辨率"""
        if original_roi is None:
            return None

        from_w, from_h = from_resolution
        x1, y1, x2, y2 = original_roi

        abs_x1 = x1 * from_w
        abs_y1 = y1 * from_h
        abs_x2 = x2 * from_w
        abs_y2 = y2 * from_h

        to_w, to_h = to_resolution
        new_x1 = abs_x1 / to_w
        new_y1 = abs_y1 / to_h
        new_x2 = abs_x2 / to_w
        new_y2 = abs_y2 / to_h

        converted_roi = (new_x1, new_y1, new_x2, new_y2)
        self.logger.debug(
            f"ROI转换完成 | 原始: {original_roi} ({from_resolution}) | "
            f"转换后: {converted_roi} ({to_resolution})"
        )
        return converted_roi

    def get_roi_region(
        self,
        screen: np.ndarray,
        roi: Optional[Tuple[float, float, float, float]]
    ) -> np.ndarray:
        """从屏幕截图中提取ROI区域"""
        if roi is None:
            self.logger.debug("未指定ROI，返回原始图像")
            return screen

        h, w = screen.shape[:2]
        x1, y1, x2, y2 = roi
        abs_x1 = int(w * x1)
        abs_y1 = int(h * y1)
        abs_x2 = int(w * x2)
        abs_y2 = int(h * y2)

        # 边界检查
        abs_x1 = max(0, min(abs_x1, w-1))
        abs_y1 = max(0, min(abs_y1, h-1))
        abs_x2 = max(0, min(abs_x2, w))
        abs_y2 = max(0, min(abs_y2, h))

        roi_region = screen[abs_y1:abs_y2, abs_x1:abs_x2]
        self.logger.debug(
            f"ROI区域提取完成 | 区域: ({x1},{y1},{x2},{y2}) | "
            f"像素坐标: ({abs_x1},{abs_y1})-({abs_x2},{abs_y2}) | "
            f"尺寸: {roi_region.shape[1]}x{roi_region.shape[0]}"
        )
        return roi_region

    @_timing_decorator
    def match_template(
        self,
        screen: np.ndarray,
        template_name: str
    ) -> MatchResult:
        """
        模板匹配
        
        Args:
            screen: 屏幕截图
            template_name: 模板名称
            
        Returns:
            MatchResult: 匹配结果
        """
        # 验证输入参数
        if screen is None or screen.size == 0:
            self.logger.error("无效的屏幕截图（空图像或尺寸为0）")
            return self._create_no_match_result(template_name)

        if template_name not in self.templates:
            self.logger.warning(f"模板 '{template_name}' 未加载，无法匹配")
            return self._create_no_match_result(template_name)

        template_info = self.templates[template_name]

        try:
            # 获取ROI区域
            roi_img = self.get_roi_region(screen, template_info.roi)

            # 类型检查
            if not isinstance(template_info.template, Template):
                self.logger.error(f"模板 '{template_name}' 不是有效的Template对象")
                return self._create_no_match_result(template_name)

            # 执行匹配
            self.logger.debug(f"开始匹配模板: {template_name}（阈值: {template_info.threshold}）")
            match_result = template_info.template.match_in(roi_img)

            # 处理匹配结果
            return self._process_match_result(
                match_result,
                template_name,
                template_info,
                screen.shape[:2]
            )

        except Exception as e:
            self.logger.error(f"模板匹配失败 '{template_name}'", exc_info=True)
            return self._create_no_match_result(template_name, template_info.template)

    def _create_no_match_result(
        self,
        template_name: str,
        template: Optional[Template] = None
    ) -> MatchResult:
        """创建无匹配结果对象"""
        self.logger.debug(f"模板 '{template_name}' 未找到匹配")
        return MatchResult(
            name=template_name,
            position=None,
            confidence=0.0,
            template=template
        )

    def _process_match_result(
        self,
        match_result: Union[dict, tuple, None],
        template_name: str,
        template_info: TemplateInfo,
        screen_shape: Tuple[int, int]
    ) -> MatchResult:
        """处理匹配结果"""
        if not match_result:
            self.logger.debug(f"模板 '{template_name}' 未找到有效匹配")
            return self._create_no_match_result(template_name, template_info.template)

        center_x, center_y, confidence = self._extract_match_info(match_result)

        if center_x is None or center_y is None:
            self.logger.debug(f"模板 '{template_name}' 匹配结果无效")
            return self._create_no_match_result(template_name, template_info.template)

        # 处理ROI偏移
        if template_info.roi:
            screen_h, screen_w = screen_shape
            roi_x1 = int(screen_w * template_info.roi[0])
            roi_y1 = int(screen_h * template_info.roi[1])
            center_x += roi_x1
            center_y += roi_y1
            self.logger.debug(
                f"模板 '{template_name}' 应用ROI偏移: ({roi_x1},{roi_y1}) | "
                f"偏移后坐标: ({center_x},{center_y})"
            )

        # 置信度检查
        if confidence < template_info.threshold:
            self.logger.debug(
                f"模板 '{template_name}' 置信度不足 "
                f"({confidence:.2f} < {template_info.threshold})"
            )
            return self._create_no_match_result(template_name, template_info.template)

        self.logger.debug(
            f"模板 '{template_name}' 匹配成功 | "
            f"坐标: ({center_x},{center_y}) | 置信度: {confidence:.2f}"
        )
        return MatchResult(
            name=template_name,
            position=(int(center_x), int(center_y)),
            confidence=float(confidence),
            template=template_info.template
        )

    def _extract_match_info(
        self,
        match_result: Union[dict, tuple]
    ) -> Tuple[Optional[float], Optional[float], float]:
        """从匹配结果中提取位置信息"""
        center_x, center_y, confidence = None, None, 0.0

        self.logger.debug(f"处理匹配结果: {type(match_result).__name__}")

        if isinstance(match_result, dict):
            if 'result' in match_result and 'confidence' in match_result:
                if isinstance(match_result['result'], (tuple, list)) and len(match_result['result']) == 2:
                    center_x, center_y = match_result['result']
                    confidence = match_result['confidence']
                else:
                    self.logger.error(f"字典中 'result' 不是有效坐标: {match_result['result']}")
            else:
                self.logger.error(f"字典缺少 'result' 或 'confidence' 键: {match_result.keys()}")
        elif isinstance(match_result, (tuple, list)) and len(match_result) == 2:
            # 兼容元组/列表形式的坐标
            center_x, center_y = match_result
            confidence = 1.0  # 旧格式默认最高置信度
        else:
            self.logger.error(
                f"不支持的匹配结果类型: {type(match_result).__name__}, "
                f"内容: {str(match_result)[:100]}"  # 截断长内容
            )

        return center_x, center_y, confidence

    def preprocess_for_ocr(
        self,
        image: np.ndarray,
        clahe_clip: float = 2.0,
        clahe_grid: Tuple[int, int] = (8, 8)
    ) -> np.ndarray:
        """为OCR优化图像预处理"""
        if image is None or image.size == 0:
            self.logger.error("无效图像，无法进行OCR预处理")
            return np.array([])

        # 转为灰度图
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # 对比度增强
        clahe = cv2.createCLAHE(
            clipLimit=clahe_clip,
            tileGridSize=clahe_grid
        )
        enhanced = clahe.apply(gray)

        self.logger.debug(
            f"OCR预处理完成 | 原始尺寸: {image.shape[:2]} | "
            f"CLAHE参数: {clahe_clip}/{clahe_grid}"
        )
        return enhanced

    def crop_image(
        self,
        image: np.ndarray,
        region: Tuple[int, int, int, int]
    ) -> np.ndarray:
        """裁剪图像"""
        if image is None or image.size == 0:
            self.logger.error("无效图像，无法裁剪")
            return np.array([])

        try:
            cropped = aircv.crop_image(image, region)
            self.logger.debug(
                f"图像裁剪完成 | 区域: {region} | "
                f"原始尺寸: {image.shape[:2]} | 裁剪后: {cropped.shape[:2]}"
            )
            return cropped
        except Exception as e:
            self.logger.error(f"图像裁剪失败: {str(e)}", exc_info=True)
            return np.array([])

    def find_color(
        self,
        image: np.ndarray,
        color: Tuple[int, int, int],
        threshold: float = 0.9,
        color_range: Optional[Tuple[int, int, int]] = None
    ) -> Optional[Tuple[int, int]]:
        """在图像中查找指定颜色"""
        if image is None or image.size == 0:
            self.logger.error("无效图像，无法查找颜色")
            return None

        try:
            if color_range is not None:
                # 颜色范围匹配
                lower = np.array([
                    max(0, color[0]-color_range[0]),
                    max(0, color[1]-color_range[1]),
                    max(0, color[2]-color_range[2])
                ])
                upper = np.array([
                    min(255, color[0]+color_range[0]),
                    min(255, color[1]+color_range[1]),
                    min(255, color[2]+color_range[2])
                ])
                mask = cv2.inRange(image, lower, upper)
                contours, _ = cv2.findContours(
                    mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                if contours:
                    max_contour = max(contours, key=cv2.contourArea)
                    M = cv2.moments(max_contour)
                    if M["m00"] > 0:
                        cX = int(M["m10"] / M["m00"])
                        cY = int(M["m01"] / M["m00"])
                        self.logger.debug(
                            f"颜色范围匹配成功 | 颜色: {color} | 范围: {color_range} | "
                            f"坐标: ({cX},{cY})"
                        )
                        return (cX, cY)
            else:
                # 精确颜色匹配
                color_template = aircv.create_color_template(color)
                pos = color_template.match_in(image)
                if pos and color_template.get_score() >= threshold:
                    self.logger.debug(
                        f"精确颜色匹配成功 | 颜色: {color} | 阈值: {threshold} | "
                        f"坐标: {pos}"
                    )
                    return (int(pos[0]), int(pos[1]))

            self.logger.debug(f"未找到匹配颜色: {color}")
            return None
        except Exception as e:
            self.logger.error(f"颜色匹配错误", exc_info=True)
            return None

    def find_color_regions(
        self,
        image: np.ndarray,
        color: Tuple[int, int, int],
        color_range: Tuple[int, int, int] = (10, 10, 10),
        min_area: int = 10,
        max_results: int = 10
    ) -> List[Tuple[int, int, int, int]]:
        """查找图像中指定颜色的区域"""
        if image is None or image.size == 0:
            self.logger.error("无效图像，无法查找颜色区域")
            return []

        try:
            # 创建颜色范围掩码
            lower = np.array([
                max(0, color[0]-color_range[0]),
                max(0, color[1]-color_range[1]),
                max(0, color[2]-color_range[2])
            ])
            upper = np.array([
                min(255, color[0]+color_range[0]),
                min(255, color[1]+color_range[1]),
                min(255, color[2]+color_range[2])
            ])
            
            mask = cv2.inRange(image, lower, upper)
            
            # 查找轮廓
            contours, _ = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # 提取区域
            regions = []
            for contour in contours:
                area = cv2.contourArea(contour)
                if area >= min_area:
                    x, y, w, h = cv2.boundingRect(contour)
                    regions.append((x, y, w, h))
                    
                    if len(regions) >= max_results:
                        break
            
            # 按面积排序
            regions.sort(key=lambda r: r[2]*r[3], reverse=True)
            
            self.logger.debug(
                f"颜色区域查找完成 | 颜色: {color} | 范围: {color_range} | "
                f"找到区域: {len(regions)}个 | 最小面积: {min_area}"
            )
            return regions
            
        except Exception as e:
            self.logger.error(f"颜色区域查找错误", exc_info=True)
            return []

    @_timing_decorator
    def match_multiple_templates(
        self,
        screen: np.ndarray,
        template_names: List[str],
        threshold: float = 0.8,
        parallel: bool = True,
        return_all: bool = False
    ) -> Union[MatchResult, List[MatchResult]]:
        """同时匹配多个模板并返回结果"""
        if not template_names:
            self.logger.warning("未提供模板名称列表，无法进行多模板匹配")
            return MatchResult(name="", position=None, confidence=0.0) if not return_all else []

        if screen is None or screen.size == 0:
            self.logger.error("无效的屏幕截图，无法进行多模板匹配")
            return MatchResult(name="", position=None, confidence=0.0) if not return_all else []

        results = []
        self.logger.debug(
            f"开始多模板匹配 | 模板数量: {len(template_names)} | "
            f"并行模式: {parallel} | 阈值: {threshold} | 返回所有: {return_all}"
        )

        if parallel:
            futures = {}
            for name in template_names:
                future = self.executor.submit(
                    self.match_template,
                    screen.copy(),
                    name
                )
                futures[future] = name

            for future in as_completed(futures):
                template_name = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    self.logger.error(f"多模板匹配线程错误 '{template_name}'", exc_info=True)
        else:
            for name in template_names:
                result = self.match_template(screen, name)
                results.append(result)

        # 过滤低于阈值的结果
        valid_results = [r for r in results if r.confidence >= threshold]
        
        if return_all:
            self.logger.info(
                f"多模板匹配完成 | 有效结果: {len(valid_results)}/{len(template_names)} | "
                f"阈值: {threshold}"
            )
            return valid_results
        else:
            # 返回最佳匹配
            best_match = max(valid_results, key=lambda x: x.confidence, default=MatchResult(name="", position=None, confidence=0.0))
            
            if best_match.confidence > 0:
                self.logger.info(
                    f"多模板匹配成功 | 最佳匹配: {best_match.name} | "
                    f"置信度: {best_match.confidence:.2f} | 坐标: {best_match.position}"
                )
                return best_match
            else:
                self.logger.debug(
                    f"多模板匹配未找到合格结果 | 最高置信度: {best_match.confidence:.2f} < {threshold}"
                )
                return MatchResult(name="", position=None, confidence=0.0)

    def find_shapes(
        self,
        image: np.ndarray,
        shape_type: str = "rectangle",
        min_area: int = 100,
        max_results: int = 10,
        canny_threshold1: int = 50,
        canny_threshold2: int = 150
    ) -> List[Union[Tuple[int, int, int, int], Tuple[int, int, int]]]:
        """查找图像中的形状"""
        if image is None or image.size == 0:
            self.logger.error("无效图像，无法查找形状")
            return []

        try:
            # 转为灰度图
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()

            # 边缘检测
            edges = cv2.Canny(gray, canny_threshold1, canny_threshold2)
            contours, _ = cv2.findContours(
                edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

            results = []
            for cnt in sorted(contours, key=cv2.contourArea, reverse=True):
                area = cv2.contourArea(cnt)
                if area < min_area:
                    continue

                if shape_type == "rectangle":
                    x, y, w, h = cv2.boundingRect(cnt)
                    results.append((x, y, w, h))
                elif shape_type == "circle":
                    (x, y), radius = cv2.minEnclosingCircle(cnt)
                    results.append((int(x), int(y), int(radius)))

                if len(results) >= max_results:
                    break

            self.logger.debug(
                f"形状查找完成 | 类型: {shape_type} | 找到: {len(results)}个 | "
                f"最小面积: {min_area} | 最大结果数: {max_results}"
            )
            return results
        except Exception as e:
            self.logger.error(f"形状查找错误", exc_info=True)
            return []

    def compare_images(
        self,
        img1: np.ndarray,
        img2: np.ndarray,
        method: int = cv2.HISTCMP_CORREL
    ) -> float:
        """比较两张图像的相似度"""
        if img1 is None or img2 is None or img1.size == 0 or img2.size == 0:
            self.logger.error("无效图像，无法比较")
            return 0.0
        
        try:
            # 确保图像尺寸相同
            if img1.shape != img2.shape:
                img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
            
            # 计算直方图
            hist1 = cv2.calcHist([img1], [0], None, [256], [0, 256])
            hist2 = cv2.calcHist([img2], [0], None, [256], [0, 256])
            
            # 归一化
            cv2.normalize(hist1, hist1, 0, 1, cv2.NORM_MINMAX)
            cv2.normalize(hist2, hist2, 0, 1, cv2.NORM_MINMAX)
            
            # 比较直方图
            similarity = cv2.compareHist(hist1, hist2, method)
            
            self.logger.debug(
                f"图像比较完成 | 相似度: {similarity:.3f} | "
                f"方法: {method} | 图像尺寸: {img1.shape[:2]}"
            )
            return similarity
            
        except Exception as e:
            self.logger.error(f"图像比较错误", exc_info=True)
            return 0.0

    def save_image(
        self,
        image: np.ndarray,
        file_path: str,
        create_dir: bool = True
    ) -> bool:
        """保存图像到文件"""
        if image is None or image.size == 0:
            self.logger.error("无效图像，无法保存")
            return False
        
        try:
            # 创建目录（如果需要）
            if create_dir:
                dir_path = os.path.dirname(file_path)
                if dir_path and not os.path.exists(dir_path):
                    os.makedirs(dir_path)
            
            # 保存图像
            success = cv2.imwrite(file_path, image)
            
            if success:
                self.logger.debug(f"图像保存成功: {file_path}")
            else:
                self.logger.error(f"图像保存失败: {file_path}")
                
            return success
            
        except Exception as e:
            self.logger.error(f"图像保存错误: {str(e)}", exc_info=True)
            return False

    def get_screen_resolution(self, screen: np.ndarray) -> Tuple[int, int]:
        """获取屏幕截图的分辨率"""
        if screen is None or screen.size == 0:
            self.logger.error("无效屏幕截图，无法获取分辨率")
            return (0, 0)
        
        height, width = screen.shape[:2]
        self.logger.debug(f"屏幕分辨率: {width}x{height}")
        return (width, height)

    def find_template_with_scale(
        self,
        screen: np.ndarray,
        template_name: str,
        min_scale: float = 0.5,
        max_scale: float = 2.0,
        scale_steps: int = 10
    ) -> MatchResult:
        """在不同缩放比例下查找模板"""
        if screen is None or screen.size == 0:
            self.logger.error("无效屏幕截图，无法进行多尺度模板匹配")
            return self._create_no_match_result(template_name)
        
        if template_name not in self.templates:
            self.logger.warning(f"模板 '{template_name}' 未加载，无法匹配")
            return self._create_no_match_result(template_name)
        
        best_match = self._create_no_match_result(template_name)
        template_info = self.templates[template_name]
        
        self.logger.debug(
            f"开始多尺度模板匹配 | 模板: {template_name} | "
            f"缩放范围: {min_scale}-{max_scale} | 步数: {scale_steps}"
        )
        
        # 生成缩放比例序列
        scales = np.linspace(min_scale, max_scale, scale_steps)
        
        for scale in scales:
            try:
                # 缩放屏幕截图
                scaled_screen = cv2.resize(
                    screen, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
                )
                
                # 进行模板匹配
                result = self.match_template(scaled_screen, template_name)
                
                # 调整坐标到原始尺寸
                if result.position:
                    x, y = result.position
                    result.position = (int(x / scale), int(y / scale))
                    result.confidence = result.confidence  # 置信度保持不变
                
                # 更新最佳匹配
                if result.confidence > best_match.confidence:
                    best_match = result
                    
            except Exception as e:
                self.logger.warning(f"缩放比例 {scale:.2f} 下匹配失败: {str(e)}")
                continue
        
        if best_match.confidence > 0:
            self.logger.info(
                f"多尺度模板匹配成功 | 模板: {template_name} | "
                f"最佳比例: {scales[np.argmax([r.confidence for r in results])]:.2f} | "
                f"置信度: {best_match.confidence:.2f} | 坐标: {best_match.position}"
            )
        else:
            self.logger.debug(f"多尺度模板匹配未找到合格结果: {template_name}")
        
        return best_match

    def wait_for_template(
        self,
        screen_provider: callable,
        template_name: str,
        timeout: float = 10.0,
        interval: float = 0.5,
        threshold: float = DEFAULT_THRESHOLD
    ) -> Optional[MatchResult]:
        """等待模板出现"""
        import time
        
        start_time = time.time()
        self.logger.info(
            f"开始等待模板 | 模板: {template_name} | 超时: {timeout}秒 | 间隔: {interval}秒"
        )
        
        while time.time() - start_time < timeout:
            try:
                # 获取当前屏幕
                screen = screen_provider()
                if screen is None or screen.size == 0:
                    self.logger.warning("获取到无效屏幕，继续等待")
                    time.sleep(interval)
                    continue
                
                # 进行模板匹配
                result = self.match_template(screen, template_name)
                
                if result.confidence >= threshold:
                    self.logger.info(
                        f"模板出现 | 模板: {template_name} | "
                        f"置信度: {result.confidence:.2f} | 坐标: {result.position}"
                    )
                    return result
                
                # 等待下一轮
                time.sleep(interval)
                
            except Exception as e:
                self.logger.error(f"等待模板过程中发生错误: {str(e)}", exc_info=True)
                time.sleep(interval)
        
        self.logger.warning(f"等待模板超时 | 模板: {template_name} | 超时时间: {timeout}秒")
        return None

    def close(self):
        """释放资源"""
        self.executor.shutdown()
        self.logger.info("图像处理器已关闭，资源已释放")