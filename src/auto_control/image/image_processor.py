import datetime
import logging
import os
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

from src.auto_control.config.auto_config import TEMPLATE_EXTENSIONS
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.display_context import RuntimeDisplayContext
from src.auto_control.utils.debug_image_saver import DebugImageSaver  # 导入公共调试图工具类
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
        test_mode: bool = False
    ) -> None:
        """
        初始化图像处理器（强制依赖上层传入有效实例）
        :param original_base_res: 全屏录制的基准分辨率（必需）
        :param logger: 日志实例（必需）
        :param coord_transformer: 坐标转换器实例（必需）
        :param display_context: 运行时上下文实例（必需）
        :param template_dir: 模板目录（可选，默认使用path_manager的task_template路径）
        :param test_mode: 测试模式开关（控制是否保存调试图+初始化清空历史图），默认False
        :raises ValueError: 任何必需依赖缺失或无效时抛错
        """
        # 强制检查所有必需依赖（不存在/无效直接抛错，不提供降级）
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

        # 赋值核心属性（已校验有效性，直接使用）
        self.logger = logger
        self.original_base_res = original_base_res
        self.coord_transformer = coord_transformer
        self.display_context = display_context
        self.template_dir = template_dir or path_manager.get("task_template")
        self.test_mode = test_mode

        # 初始化辅助属性
        self.templates: Dict[str, np.ndarray] = {}
        debug_dir = path_manager.get("match_temple_debug")
        os.makedirs(debug_dir, exist_ok=True)  # 确保调试目录存在

        # 初始化公共调试图保存工具
        self.debug_saver = DebugImageSaver(
            logger=logger,
            debug_dir=debug_dir,
            test_mode=test_mode
        )

        # 匹配参数配置
        self.min_confidence = 0.8
        self.min_template_size = (10, 10)
        self.match_algorithm = cv2.TM_CCOEFF_NORMED

        # 加载模板并输出初始化日志
        self.load_all_templates()
        self.logger.info(
            f"初始化完成 | 加载模板数: {len(self.templates)} | "
            f"原始基准分辨率: {self.original_base_res} | 模板目录: {self.template_dir} | "
            f"测试模式: {'启用（已清空历史调试图）' if self.test_mode else '禁用'}"
        )

    def load_template(self, template_name: str, template_path: Optional[str] = None) -> bool:
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

    def load_all_templates(self) -> None:
        if not os.path.isdir(self.template_dir):
            self.logger.warning(f"模板目录不存在: {self.template_dir}")
            return

        for root, dirs, files in os.walk(self.template_dir):
            for filename in files:
                if filename.lower().endswith(TEMPLATE_EXTENSIONS):
                    rel_path = os.path.relpath(root, self.template_dir)
                    template_name = os.path.join(rel_path, os.path.splitext(filename)[0]).replace('\\', '/') if rel_path != "." else os.path.splitext(filename)[0]
                    template_path = os.path.join(root, filename)
                    self.load_template(template_name, template_path)

    def get_template(self, template_name: str) -> Optional[np.ndarray]:
        template = self.templates.get(template_name)
        if template is None:
            self.logger.warning(f"模板未找到，尝试重新加载: {template_name}")
            if self.load_template(template_name):
                template = self.templates.get(template_name)
        return template

    def match_template(
        self,
        image: np.ndarray,
        template: Union[str, np.ndarray],
        threshold: float = 0.8,
        roi: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Tuple[int, int, int, int]]:
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
            orig_roi_phys = None  # 原始ROI的物理坐标（用于标注）
            processed_roi = roi   # 处理后的ROI（逻辑坐标）
            roi_offset_phys = (0, 0)

            # 处理模板（原有逻辑不变）
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

            # ------------------------------ 复用CoordinateTransformer的ROI处理 ------------------------------
            cropped_image = orig_image
            if roi:
                # 调用公共ROI处理方法（禁用扩展，使用图像物理尺寸作为边界）
                processed_roi_phys, roi_offset_phys = self.coord_transformer.process_roi(
                    roi=roi,
                    boundary_width=image_phys_w,
                    boundary_height=image_phys_h,
                    enable_expand=False  # ImageProcessor不启用扩展
                )
                if processed_roi_phys:
                    orig_roi_phys = processed_roi_phys
                    rx_phys, ry_phys, rw_phys, rh_phys = processed_roi_phys
                    cropped_image = orig_image[ry_phys:ry_phys+rh_phys, rx_phys:rx_phys+rw_phys]
                    # 新增：裁剪后子图有效性检查，为空则回退到原图
                    if cropped_image.size == 0:
                        self.logger.warning(f"ROI裁剪后子图为空，使用原图进行匹配 | 原始ROI: {roi} | 处理后ROI物理坐标: {processed_roi_phys}")
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

            # ------------------------------ 修复：模板缩放比例计算（基于整体物理尺寸，与ROI无关） ------------------------------
            # 核心修正：模板缩放比例 = 当前整体物理尺寸 / 基准分辨率（全屏=屏幕，窗口=客户区）
            if is_fullscreen:
                target_phys_size = self.display_context.screen_physical_res
            else:
                target_phys_size = self.display_context.client_physical_res
            # 计算正确的缩放比例（仅依赖整体分辨率，不依赖ROI尺寸）
            scale_ratio = self.coord_transformer.calculate_template_scale_ratio(
                target_phys_size=target_phys_size,
                has_roi=False  # 模板缩放与ROI无关，仅需整体分辨率比例
            )
            self.logger.debug(
                f"模板缩放比例计算完成 | 基准分辨率: {self.original_base_res} | "
                f"当前整体物理尺寸: {target_phys_size} | 缩放比例: {scale_ratio:.4f}"
            )

            # 模板缩放（基于正确比例，保留尺寸限制逻辑）
            scaled_w = max(self.min_template_size[0], int(round(template_orig_w * scale_ratio)))
            scaled_h = max(self.min_template_size[1], int(round(template_orig_h * scale_ratio)))
            # 确保缩放后模板不超过裁剪子图尺寸（避免匹配时模板超出范围）
            scaled_w = min(scaled_w, cropped_image.shape[1] - 2)
            scaled_h = min(scaled_h, cropped_image.shape[0] - 2)
            template_scaled_size = (scaled_w, scaled_h)

            if scaled_w <= 0 or scaled_h <= 0:
                self.logger.error(
                    f"模板缩放失败 | 缩放后尺寸无效: {template_scaled_size} | "
                    f"子图尺寸: (宽={cropped_image.shape[1]}, 高={cropped_image.shape[0]}) | 比例: {scale_ratio:.4f}"
                )
                return None

            # 优化：缩小用LANCZOS4（抗锯齿更好，保留模板细节），放大用CUBIC
            interpolation = cv2.INTER_LANCZOS4 if scale_ratio < 1.0 else cv2.INTER_CUBIC
            scaled_template = cv2.resize(template_bgr, (scaled_w, scaled_h), interpolation=interpolation)
            self.logger.debug(
                f"模板缩放完成 | 原始尺寸: {template_orig_size} → 缩放后: {template_scaled_size} | "
                f"插值方式: {interpolation} | 缩放比例: {scale_ratio:.4f}"
            )

            # 模板匹配核心逻辑（原有不变）
            cropped_gray = cv2.cvtColor(cropped_image, cv2.COLOR_BGR2GRAY) if len(cropped_image.shape) == 3 else cropped_image
            template_gray = cv2.cvtColor(scaled_template, cv2.COLOR_BGR2GRAY) if len(scaled_template.shape) == 3 else scaled_template

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
                        processed_roi=processed_roi
                    )
                return None

            # ------------------------------ 复用CoordinateTransformer的子图坐标→原图物理坐标 + 中心计算 ------------------------------
            match_x_sub, match_y_sub = max_loc
            # 子图内矩形 → 原图物理矩形（应用ROI偏移）
            match_bbox_sub = (match_x_sub, match_y_sub, scaled_template.shape[1], scaled_template.shape[0])
            match_bbox_phys = self.coord_transformer.apply_roi_offset_to_subcoord(
                sub_coord=match_bbox_sub,
                roi_offset_phys=roi_offset_phys
            )
            # 计算矩形中心（复用公共方法）
            center_phys = self.coord_transformer.get_rect_center(match_bbox_phys)

            # ------------------------------ 复用CoordinateTransformer的全屏/窗口逻辑坐标统一转换 ------------------------------
            final_bbox_log = self.coord_transformer.get_unified_logical_rect(match_bbox_phys)

            # 测试模式保存图片（原有逻辑不变）
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
                    template_scaled_size=template_scaled_size
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