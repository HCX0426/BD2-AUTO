import datetime
import logging
import os
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np


from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.debug_image_saver import DebugImageSaver
from src.auto_control.utils.display_context import RuntimeDisplayContext
from src.core.path_manager import path_manager


class ImageProcessor:
    """图像处理器：对齐OCR流程（先裁剪ROI，再模板缩放）"""

    def __init__(
        self,
        original_base_res: Tuple[int, int],
        logger: Optional[logging.Logger] = None,
        coord_transformer: Optional[CoordinateTransformer] = None,
        display_context: Optional[RuntimeDisplayContext] = None,
        template_dir: str = None,
        test_mode: bool = False,
        config: Optional[object] = None,
    ) -> None:
        """
        初始化图像处理器（强制依赖上层传入有效实例）

        Args:
            original_base_res: 全屏录制的基准分辨率（宽, 高）
            logger: 日志实例（必需）
            coord_transformer: 坐标转换器实例（必需）
            display_context: 运行时上下文实例（必需）
            template_dir: 模板目录（可选，默认使用path_manager的task_template路径）
            test_mode: 测试模式开关（控制是否保存调试图+初始化清空历史图），默认False

        Raises:
            ValueError: 任何必需依赖缺失或无效时抛错
        """
        if not logger:
            raise ValueError("初始化失败：logger不能为空（必须传入有效日志实例）")
        if not isinstance(original_base_res, (tuple, list)) or len(original_base_res) != 2:
            raise ValueError(f"初始化失败：original_base_res必须是二元组（当前：{original_base_res}）")
        if original_base_res[0] <= 0 or original_base_res[1] <= 0:
            raise ValueError(f"初始化失败：original_base_res必须为正整数（当前：{original_base_res}）")
        if not isinstance(coord_transformer, CoordinateTransformer):
            raise ValueError("初始化失败：coord_transformer必须是CoordinateTransformer实例")
        if not isinstance(display_context, RuntimeDisplayContext):
            raise ValueError("初始化失败：display_context必须是RuntimeDisplayContext实例")

        self.logger = logger
        self.original_base_res = original_base_res
        self.coord_transformer = coord_transformer
        self.display_context = display_context
        self.template_dir = template_dir or path_manager.get("task_template")
        self.test_mode = test_mode
        
        # 配置初始化
        self.config = config
        # 获取模板扩展名配置，支持外部配置覆盖默认值
        self.template_extensions = getattr(config, "TEMPLATE_EXTENSIONS", (".png", ".jpg", ".jpeg", ".bmp"))

        # 模板缓存，采用LRU策略
        self.templates: Dict[str, np.ndarray] = {}
        self.template_access_time: Dict[str, float] = {}
        self.max_template_cache_size = 100  # 最大缓存模板数量

        debug_dir = path_manager.get("match_temple_debug")
        os.makedirs(debug_dir, exist_ok=True)

        self.debug_saver = DebugImageSaver(logger=logger, debug_dir=debug_dir, test_mode=test_mode)

        self.min_confidence = 0.8
        self.min_template_size = (10, 10)
        self.match_algorithm = cv2.TM_CCOEFF_NORMED

        # 记录所有模板路径，实现延迟加载
        self.all_template_paths: Dict[str, str] = {}
        self._scan_all_templates()
        self.logger.info(
            f"初始化完成 | 加载模板数: {len(self.templates)} | "
            f"原始基准分辨率: {self.original_base_res} | 模板目录: {self.template_dir} | "
            f"测试模式: {'启用（已清空历史调试图）' if self.test_mode else '禁用'}"
        )

    def load_template(self, template_name: str, template_path: Optional[str] = None) -> bool:
        """
        加载指定名称的模板图片

        Args:
            template_name: 模板名称
            template_path: 模板文件路径（可选，未指定则从模板目录读取{template_name}.png）

        Returns:
            bool: 加载成功返回True，失败返回False
        """
        try:
            if not template_path:
                template_path = os.path.join(self.template_dir, f"{template_name}.png")
            if not os.path.exists(template_path):
                self.logger.error(f"模板不存在: {template_path}")
                return False

            template_color = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template_color is None:
                self.logger.error(f"读取模板失败: {template_path}")
                return False

            self.templates[template_name] = template_color
            self.logger.debug(f"加载模板成功: {template_name} | 原始尺寸: {template_color.shape[:2]}")
            return True
        except Exception as e:
            self.logger.error(f"加载模板异常: {str(e)}", exc_info=True)
            return False

    def _scan_all_templates(self) -> None:
        """扫描所有模板文件，记录路径但不立即加载"""
        if not os.path.isdir(self.template_dir):
            self.logger.warning(f"模板目录不存在: {self.template_dir}")
            return

        for root, dirs, files in os.walk(self.template_dir):
            for filename in files:
                if filename.lower().endswith(self.template_extensions):
                    rel_path = os.path.relpath(root, self.template_dir)
                    template_name = (
                        os.path.join(rel_path, os.path.splitext(filename)[0]).replace("\\", "/")
                        if rel_path != "."
                        else os.path.splitext(filename)[0]
                    )
                    template_path = os.path.join(root, filename)
                    self.all_template_paths[template_name] = template_path
        self.logger.debug(f"扫描完成，共发现{len(self.all_template_paths)}个模板文件")

    def _cleanup_template_cache(self) -> None:
        """清理模板缓存，移除最少使用的模板"""
        if len(self.templates) <= self.max_template_cache_size:
            return

        # 按照访问时间排序，移除最久未使用的模板
        sorted_templates = sorted(self.template_access_time.items(), key=lambda x: x[1])

        # 需要清理的模板数量
        templates_to_remove = len(self.templates) - self.max_template_cache_size

        for template_name, _ in sorted_templates[:templates_to_remove]:
            if template_name in self.templates:
                del self.templates[template_name]
                del self.template_access_time[template_name]
                self.logger.debug(f"清理模板缓存: {template_name}")

    def load_all_templates(self) -> None:
        """遍历模板目录，加载所有符合扩展名的模板文件"""
        for template_name, template_path in self.all_template_paths.items():
            self.load_template(template_name, template_path)

    def get_template(self, template_name: str) -> Optional[np.ndarray]:
        """
        获取指定名称的模板数组，若不存在则尝试重新加载

        Args:
            template_name: 模板名称

        Returns:
            Optional[np.ndarray]: 模板数组（BGR格式），获取失败返回None
        """
        import time
        current_time = time.time()
        
        # 检查模板是否在缓存中
        template = self.templates.get(template_name)
        if template is None:
            self.logger.debug(f"模板未在缓存中，尝试加载: {template_name}")
            # 检查是否有记录的模板路径
            template_path = self.all_template_paths.get(template_name)
            if template_path:
                if self.load_template(template_name, template_path):
                    template = self.templates.get(template_name)
            else:
                self.logger.warning(f"未找到模板路径: {template_name}")
        
        # 更新访问时间
        if template is not None:
            self.template_access_time[template_name] = current_time
            # 清理缓存
            self._cleanup_template_cache()
        
        return template

    def match_template(
        self,
        image: np.ndarray,
        template: Union[str, np.ndarray],
        threshold: float = 0.8,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        在指定图像中匹配模板，支持ROI裁剪和模板分辨率自适应缩放

        Args:
            image: 待匹配的原始图像（BGR格式）
            template: 模板名称或模板数组（BGR格式）
            threshold: 匹配置信度阈值，默认0.8
            roi: 感兴趣区域（逻辑坐标，x,y,w,h），可选，指定则仅在该区域内匹配

        Returns:
            Optional[Tuple[int, int, int, int]]: 匹配成功返回统一逻辑坐标的矩形（x,y,w,h），失败返回None
        """
        try:
            is_fullscreen = self.display_context.is_fullscreen
            ctx = self.display_context
            self.logger.debug(
                f"上下文全屏状态: {is_fullscreen} | ROI: {roi} | 阈值: {threshold} | "
                f"客户区逻辑尺寸: {ctx.client_logical_res} | 屏幕物理尺寸: {ctx.screen_physical_res}"
            )

            if image is None or image.size == 0:
                self.logger.error("模板匹配失败：输入图像为空或无效")
                return None
            orig_image = image.copy()
            image_phys_h, image_phys_w = orig_image.shape[:2]
            orig_roi_phys = None
            processed_roi = roi
            roi_offset_phys = (0, 0)

            if isinstance(template, str):
                template_bgr = self.get_template(template)
                if template_bgr is None:
                    self.logger.error(f"模板匹配失败：模板「{template}」不存在或加载失败")
                    return None
                template_name = template
            else:
                if not isinstance(template, np.ndarray) or template.size == 0:
                    self.logger.error("模板匹配失败：自定义模板为无效numpy数组")
                    return None
                template_bgr = template
                template_name = "custom_template"
            template_orig_h, template_orig_w = template_bgr.shape[:2]
            template_orig_size = (template_orig_w, template_orig_h)
            self.logger.debug(
                f"开始模板匹配 | 模板: {template_name} | 原始尺寸: {template_orig_size} | "
                f"输入图像尺寸: (宽={image_phys_w}, 高={image_phys_h}) | 阈值: {threshold} | "
                f"ROI: {roi} | 上下文全屏状态: {is_fullscreen}"
            )

            cropped_image = orig_image
            if roi:
                processed_roi_phys, roi_offset_phys = self.coord_transformer.process_roi(
                    roi=roi, boundary_width=image_phys_w, boundary_height=image_phys_h, enable_expand=False
                )
                if processed_roi_phys:
                    orig_roi_phys = processed_roi_phys
                    rx_phys, ry_phys, rw_phys, rh_phys = processed_roi_phys
                    cropped_image = orig_image[ry_phys : ry_phys + rh_phys, rx_phys : rx_phys + rw_phys]
                    if cropped_image.size == 0:
                        self.logger.warning(
                            f"ROI裁剪后子图为空，使用原图进行匹配 | 原始ROI: {roi} | 处理后ROI物理坐标: {processed_roi_phys}"
                        )
                        cropped_image = orig_image
                        roi_offset_phys = (0, 0)
                        orig_roi_phys = None
                    else:
                        self.logger.debug(
                            f"ROI裁剪完成 | 子图尺寸: (宽={cropped_image.shape[1]}, 高={cropped_image.shape[0]}) | "
                            f"原图偏移: {roi_offset_phys} | 裁剪后图像是否有效: {cropped_image.size > 0}"
                        )
                else:
                    processed_roi = None
                    roi_offset_phys = (0, 0)
                    orig_roi_phys = None

            if is_fullscreen:
                target_phys_size = self.display_context.screen_physical_res
            else:
                target_phys_size = self.display_context.client_physical_res

            scale_ratio = self.coord_transformer.calculate_template_scale_ratio(
                target_phys_size=target_phys_size, has_roi=False
            )
            self.logger.debug(
                f"模板缩放比例计算完成 | 基准分辨率: {self.original_base_res} | "
                f"当前整体物理尺寸: {target_phys_size} | 缩放比例: {scale_ratio:.4f}"
            )

            scaled_w = max(self.min_template_size[0], int(round(template_orig_w * scale_ratio)))
            scaled_h = max(self.min_template_size[1], int(round(template_orig_h * scale_ratio)))
            scaled_w = min(scaled_w, cropped_image.shape[1] - 2)
            scaled_h = min(scaled_h, cropped_image.shape[0] - 2)
            template_scaled_size = (scaled_w, scaled_h)

            if scaled_w <= 0 or scaled_h <= 0:
                self.logger.error(
                    f"模板缩放失败 | 缩放后尺寸无效: {template_scaled_size} | "
                    f"子图尺寸: (宽={cropped_image.shape[1]}, 高={cropped_image.shape[0]}) | 比例: {scale_ratio:.4f}"
                )
                return None

            interpolation = cv2.INTER_LANCZOS4 if scale_ratio < 1.0 else cv2.INTER_CUBIC
            scaled_template = cv2.resize(template_bgr, (scaled_w, scaled_h), interpolation=interpolation)
            self.logger.debug(
                f"模板缩放完成 | 原始尺寸: {template_orig_size} → 缩放后: {template_scaled_size} | "
                f"插值方式: {interpolation} | 缩放比例: {scale_ratio:.4f}"
            )

            cropped_gray = (
                cv2.cvtColor(cropped_image, cv2.COLOR_BGR2GRAY) if len(cropped_image.shape) == 3 else cropped_image
            )
            template_gray = (
                cv2.cvtColor(scaled_template, cv2.COLOR_BGR2GRAY)
                if len(scaled_template.shape) == 3
                else scaled_template
            )

            if (template_gray.shape[0] > cropped_gray.shape[0]) or (template_gray.shape[1] > cropped_gray.shape[1]):
                self.logger.error(
                    f"模板匹配失败：模板尺寸超过子图尺寸 | "
                    f"模板尺寸: (宽={template_gray.shape[1]}, 高={template_gray.shape[0]}) | "
                    f"子图尺寸: (宽={cropped_gray.shape[1]}, 高={cropped_gray.shape[0]})"
                )
                return None

            result = cv2.matchTemplate(cropped_gray, template_gray, self.match_algorithm)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            match_score = max_val
            self.logger.debug(
                f"模板匹配完成 | 最高匹配分数: {match_score:.4f} | 阈值: {threshold} | "
                f"匹配位置（子图内）: {max_loc}"
            )

            if match_score < threshold:
                self.logger.debug(
                    f"模板匹配失败：分数不足 | 模板: {template_name} | 分数: {match_score:.4f} < 阈值: {threshold}"
                )
                if self.test_mode:
                    self.debug_saver.save_template_debug(
                        orig_image=orig_image,
                        template_name=template_name,
                        is_success=False,
                        match_score=match_score,
                        threshold=threshold,
                        is_fullscreen=is_fullscreen,
                        orig_roi_phys=orig_roi_phys,
                        processed_roi=processed_roi,
                    )
                return None

            match_x_sub, match_y_sub = max_loc
            match_bbox_sub = (match_x_sub, match_y_sub, scaled_template.shape[1], scaled_template.shape[0])
            match_bbox_phys = self.coord_transformer.apply_roi_offset_to_subcoord(
                sub_coord=match_bbox_sub, roi_offset_phys=roi_offset_phys
            )
            center_phys = self.coord_transformer.get_rect_center(match_bbox_phys)

            final_bbox_log = self.coord_transformer.get_unified_logical_rect(match_bbox_phys)

            if self.test_mode:
                self.debug_saver.save_template_debug(
                    orig_image=orig_image,
                    template_name=template_name,
                    is_success=True,
                    match_score=match_score,
                    threshold=threshold,
                    is_fullscreen=is_fullscreen,
                    orig_roi_phys=orig_roi_phys,
                    processed_roi=processed_roi,
                    match_bbox_phys=match_bbox_phys,
                    center_phys=center_phys,
                    final_bbox_log=final_bbox_log,
                    template_orig_size=template_orig_size,
                    template_scaled_size=template_scaled_size,
                )

            self.logger.info(
                f"模板匹配成功 | 模板: {template_name} | 逻辑坐标: {final_bbox_log} | "
                f"物理坐标: {match_bbox_phys} | 匹配分数: {match_score:.4f} | "
                f"模式: {'全屏' if is_fullscreen else '窗口'} | 模板缩放比例: {scale_ratio:.4f}"
            )
            return final_bbox_log

        except Exception as e:
            template_name = template if isinstance(template, str) else "custom_template"
            self.logger.error(f"模板匹配异常 | 模板: {template_name} | 错误: {str(e)}", exc_info=True)
            return None
