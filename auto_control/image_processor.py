import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from glob import glob
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from airtest import aircv
from airtest.core.cv import Template

# 导入您的配置
from .config.control__config import (AUTO_LOAD_TEMPLATES, DEFAULT_MATCH_METHOD,
                                     DEFAULT_RESOLUTION,
                                     DEFAULT_SCALE_STRATEGY, DEFAULT_THRESHOLD,
                                     MAX_WORKERS, TEMPLATE_DIR,
                                     TEMPLATE_EXTENSIONS, TEMPLATE_ROI_CONFIG,
                                     MatchMethod, ScaleStrategy)


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
        auto_load: bool = AUTO_LOAD_TEMPLATES
    ):
        """
        初始化图像处理器

        Args:
            base_resolution: 设计基准分辨率 (宽, 高)
            max_workers: 线程池最大工作线程数
            template_dir: 覆盖配置中的模板目录路径
            auto_load: 是否自动加载模板
        """
        self.base_resolution = base_resolution
        self.templates: Dict[str, TemplateInfo] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        self.template_dir = template_dir or TEMPLATE_DIR

        if auto_load:
            self.load_templates_from_dir(
                dir_path=self.template_dir,
                extensions=TEMPLATE_EXTENSIONS,
                roi_config=TEMPLATE_ROI_CONFIG
            )

    def load_templates_from_dir(
        self,
        dir_path: str,
        extensions: Tuple[str, ...] = TEMPLATE_EXTENSIONS,
        recursive: bool = True,
        roi_config: Optional[Dict[str,
                                  Tuple[float, float, float, float]]] = None,
        threshold: float = DEFAULT_THRESHOLD,
        scale_strategy: ScaleStrategy = DEFAULT_SCALE_STRATEGY
    ) -> Dict[str, Template]:
        """
        从目录加载所有图片作为模板
        """
        if not os.path.exists(dir_path):
            print(f"[WARN] 模板目录不存在: {dir_path}")
            return {}

        loaded = {}
        pattern = os.path.join(dir_path, '**' if recursive else '', '*')
        for file_path in glob(pattern, recursive=recursive):
            if file_path.lower().endswith(extensions):
                template_name = os.path.splitext(
                    os.path.basename(file_path))[0]
                try:
                    loaded[template_name] = self.load_template(
                        name=template_name,
                        path=file_path,
                        roi=roi_config.get(
                            template_name) if roi_config else None,
                        threshold=threshold,
                        scale_strategy=scale_strategy
                    )
                    print(f"成功加载模板: {template_name}")
                except Exception as e:
                    print(f"[ERROR] 加载模板失败 {template_name}: {str(e)}")
        return loaded

    def __del__(self):
        self.executor.shutdown()

    def update_resolution(self, new_resolution: Tuple[int, int]) -> None:
        """
        更新基准分辨率
        """
        self.base_resolution = new_resolution
        for name in self.templates:
            self.templates[name].last_resolution = None

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
            # 先验证图像文件是否存在
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

            return template

        except Exception as e:
            print(f"[ERROR] 加载模板 '{name}' 失败: {str(e)}")
            raise ValueError(f"模板加载失败: {str(e)}") from e
    
    def get_template(self, template_name: str) -> Optional[Template]:
        """
        根据模板名称获取模板对象
        
        Args:
            template_name: 模板名称
            
        Returns:
            Template: 如果存在则返回模板对象,否则返回None
        """
        template_info = self.templates.get(template_name)
        if template_info is None:
            print(f"[WARN] 模板 '{template_name}' 未加载")
            return None
        
        return template_info.template

    def _scale_image(
        self,
        image: np.ndarray,
        target_resolution: Tuple[int, int],
        scale_strategy: ScaleStrategy
    ) -> np.ndarray:
        """
        根据策略缩放图像
        """
        base_w, base_h = DEFAULT_RESOLUTION
        target_w, target_h = target_resolution

        if scale_strategy == ScaleStrategy.FIT:
            scale = min(target_w / base_w, target_h / base_h)
            return cv2.resize(image, None, fx=scale, fy=scale)
        elif scale_strategy == ScaleStrategy.STRETCH:
            return cv2.resize(image, (target_w, target_h))
        elif scale_strategy == ScaleStrategy.CROP:
            scale = max(target_w / base_w, target_h / base_h)
            scaled_img = cv2.resize(image, None, fx=scale, fy=scale)
            h, w = scaled_img.shape[:2]
            crop_x = max(0, (w - target_w) // 2)
            crop_y = max(0, (h - target_h) // 2)
            return scaled_img[crop_y:crop_y+target_h, crop_x:crop_x+target_w]
        else:
            scale = min(target_w / base_w, target_h / base_h)
            return cv2.resize(image, None, fx=scale, fy=scale)

    def _convert_roi(
        self,
        original_roi: Optional[Tuple[float, float, float, float]],
        from_resolution: Tuple[int, int],
        to_resolution: Tuple[int, int]
    ) -> Optional[Tuple[float, float, float, float]]:
        """
        转换ROI坐标到新分辨率
        """
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

        return (new_x1, new_y1, new_x2, new_y2)

    def get_roi_region(
        self,
        screen: np.ndarray,
        roi: Optional[Tuple[float, float, float, float]]
    ) -> np.ndarray:
        """
        从屏幕截图中提取ROI区域
        """
        if roi is None:
            return screen

        h, w = screen.shape[:2]
        x1, y1, x2, y2 = roi
        abs_x1 = int(w * x1)
        abs_y1 = int(h * y1)
        abs_x2 = int(w * x2)
        abs_y2 = int(h * y2)

        abs_x1 = max(0, min(abs_x1, w-1))
        abs_y1 = max(0, min(abs_y1, h-1))
        abs_x2 = max(0, min(abs_x2, w))
        abs_y2 = max(0, min(abs_y2, h))

        return screen[abs_y1:abs_y2, abs_x1:abs_x2]

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
            print("[ERROR] 无效的屏幕截图")
            return self._create_no_match_result(template_name)

        if template_name not in self.templates:
            print(f"[WARN] 模板 '{template_name}' 未加载")
            return self._create_no_match_result(template_name)

        template_info = self.templates[template_name]

        try:
            # 获取ROI区域
            roi_img = self.get_roi_region(screen, template_info.roi)

            # 类型检查
            if not isinstance(template_info.template, Template):
                print(f"[ERROR] 无效的模板对象: {template_name}")
                return self._create_no_match_result(template_name)

            # 执行匹配
            match_result = template_info.template.match_in(roi_img)

            # 处理匹配结果
            return self._process_match_result(
                match_result,
                template_name,
                template_info,
                screen.shape[:2]
            )

        except Exception as e:
            print(f"[ERROR] 模板匹配失败 '{template_name}': {str(e)}")
            return self._create_no_match_result(template_name, template_info.template)

    def _create_no_match_result(
        self,
        template_name: str,
        template: Optional[Template] = None
    ) -> MatchResult:
        """创建无匹配结果对象"""
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
            print(f"[DEBUG] 未找到匹配: {template_name}")
            return self._create_no_match_result(template_name, template_info.template)

        center_x, center_y, confidence = self._extract_match_info(match_result)

        if center_x is None or center_y is None:
            return self._create_no_match_result(template_name, template_info.template)

        # 处理ROI偏移
        if template_info.roi:
            screen_h, screen_w = screen_shape
            roi_x1 = int(screen_w * template_info.roi[0])
            roi_y1 = int(screen_h * template_info.roi[1])
            center_x += roi_x1
            center_y += roi_y1

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
        """
        从匹配结果中提取位置信息

        Args:
            match_result: 匹配结果，可能是字典或元组

        Returns:
            Tuple[Optional[float], Optional[float], float]: 中心点坐标和置信度
        """
        center_x, center_y, confidence = None, None, 0.0

        print(f"[DEBUG] 处理匹配结果: {match_result}")

        if isinstance(match_result, dict):
            if 'result' in match_result and 'confidence' in match_result:
                if isinstance(match_result['result'], (tuple, list)) and len(match_result['result']) == 2:
                    center_x, center_y = match_result['result']
                    confidence = match_result['confidence']
                else:
                    print(
                        f"[ERROR] 字典中 'result' 不是有效的坐标: {match_result['result']}")
            else:
                print(
                    f"[ERROR] 字典缺少 'result' 或 'confidence' 键: {match_result}")
        elif isinstance(match_result, tuple) and len(match_result) == 2:
            # 兼容之前元组形式返回结果
            center_x, center_y = match_result
            confidence = 1.0
        elif isinstance(match_result, (tuple, list)) and len(match_result) == 2:  # 修改这行
            # 兼容元组和列表形式的坐标
            center_x, center_y = match_result
            confidence = 1.0
        else:
            print(f"[ERROR] 不支持的匹配结果类型: {type(match_result).__name__}, 内容: {match_result}")

        return center_x, center_y, confidence

    def preprocess_for_ocr(
        self,
        image: np.ndarray,
        denoise: bool = True,
        clahe_clip: float = 2.0,
        clahe_grid: Tuple[int, int] = (8, 8)
    ) -> np.ndarray:
        """
        为OCR优化图像预处理
        """
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        clahe = cv2.createCLAHE(
            clipLimit=clahe_clip,
            tileGridSize=clahe_grid
        )
        enhanced = clahe.apply(gray)

        binary = cv2.adaptiveThreshold(
            enhanced, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        if denoise:
            binary = cv2.fastNlMeansDenoising(binary, None, 10, 7, 21)

        return binary

    def crop_image(
        self,
        image: np.ndarray,
        region: Tuple[int, int, int, int]
    ) -> np.ndarray:
        """
        裁剪图像
        """
        return aircv.crop_image(image, region)

    def find_color(
        self,
        image: np.ndarray,
        color: Tuple[int, int, int],
        threshold: float = 0.9,
        color_range: Optional[Tuple[int, int, int]] = None
    ) -> Optional[Tuple[int, int]]:
        """
        在图像中查找指定颜色
        """
        try:
            if color_range is not None:
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
                        return (cX, cY)
            else:
                color_template = aircv.create_color_template(color)
                pos = color_template.match_in(image)
                if pos and color_template.get_score() >= threshold:
                    return (int(pos[0]), int(pos[1]))
        except Exception as e:
            print(f"[ERROR] 颜色匹配错误: {str(e)}")

        return None

    def match_multiple_templates(
        self,
        screen: np.ndarray,
        template_names: List[str],
        target_resolution: Tuple[int, int],
        threshold: float = 0.8,
        method: MatchMethod = DEFAULT_MATCH_METHOD,
        parallel: bool = True
    ) -> MatchResult:
        """
        同时匹配多个模板并返回最佳结果
        """
        best_match = MatchResult(name="", position=None, confidence=0.0)

        if parallel:
            futures = {}
            for name in template_names:
                future = self.executor.submit(
                    self.match_template,
                    screen.copy(),
                    name,
                    target_resolution,
                    method
                )
                futures[future] = name

            for future in as_completed(futures):
                result = future.result()
                if result.confidence > best_match.confidence:
                    best_match = result
        else:
            for name in template_names:
                result = self.match_template(
                    screen, name, target_resolution, method)
                if result.confidence > best_match.confidence:
                    best_match = result

        return best_match if best_match.confidence >= threshold else MatchResult(
            name="",
            position=None,
            confidence=0.0
        )

    def find_shapes(
        self,
        image: np.ndarray,
        shape_type: str = "rectangle",
        min_area: int = 100,
        max_results: int = 10,
        canny_threshold1: int = 50,
        canny_threshold2: int = 150
    ) -> List[Union[Tuple[int, int, int, int], Tuple[int, int, int]]]:
        """
        查找图像中的形状
        """
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()

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

            return results
        except Exception as e:
            print(f"[ERROR] 形状查找错误: {str(e)}")
            return []

    def close(self):
        """释放资源"""
        self.executor.shutdown()
