import cv2
import numpy as np
import os
from typing import Optional, Tuple, Dict, List, Union
import logging

# 导入坐标转换器
from auto_control.config.image_config import TEMPLATE_DIR, TEMPLATE_EXTENSIONS
from auto_control.coordinate_transformer import CoordinateTransformer


class ImageProcessor:
    """
    图像处理器：通用模板匹配优化（支持窗口化 + DPI缩放 + 多尺度匹配）
    注意：所有模板必须在目标应用全屏运行时录制，
    且 original_base_res 必须设置为录制时的物理屏幕分辨率（如 1920x1080）。
    窗口模式下运行时会自动根据 DPI 和客户区尺寸进行适配。
    """

    def __init__(
        self,
        original_base_res: Tuple[int, int],
        logger: Optional[logging.Logger] = None,
        coord_transformer: Optional[CoordinateTransformer] = None,
        template_dir: str = TEMPLATE_DIR
    ):
        self.logger = logger or self._create_default_logger()
        self.template_dir = template_dir
        self.templates: Dict[str, np.ndarray] = {}
        self.coord_transformer = coord_transformer
        self.original_base_res = original_base_res

        # 调试目录
        self.debug_img_dir = os.path.join(os.getcwd(), "debug", "template_image")
        os.makedirs(self.debug_img_dir, exist_ok=True)
        self.logger.info(f"调试图片保存目录: {self.debug_img_dir}")

        # 通用匹配参数
        self.edge_threshold = 0.3
        self.min_template_size = (10, 10)
        self.nms_radius = 5
        self.match_algorithms = {
            "gray": cv2.TM_CCOEFF_NORMED,
            "color": cv2.TM_CCOEFF_NORMED,
            "fallback": cv2.TM_SQDIFF_NORMED
        }

        # 加载模板
        self.load_all_templates()
        self.logger.info(
            f"初始化完成 | 加载模板数: {len(self.templates)} | "
            f"原始基准分辨率: {self.original_base_res}"
        )

    # ========== 1. 通用模板加载（灰度+梯度融合） ==========
    def load_template(self, template_name: str, template_path: Optional[str] = None) -> bool:
        try:
            if not template_path:
                template_path = os.path.join(self.template_dir, f"{template_name}.png")
            if not os.path.exists(template_path):
                self.logger.error(f"模板不存在: {template_path}")
                return False

            template_color = cv2.imread(template_path)
            if template_color is None:
                self.logger.error(f"读取模板失败: {template_path}")
                return False

            gray = cv2.cvtColor(template_color, cv2.COLOR_BGR2GRAY)
            grad_x = cv2.Sobel(template_color, cv2.CV_64F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(template_color, cv2.CV_64F, 0, 1, ksize=3)
            grad_mag = cv2.magnitude(grad_x, grad_y)
            grad_mag = cv2.normalize(grad_mag, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            template = cv2.addWeighted(gray, 0.7, grad_mag[:, :, 0], 0.3, 0)

            self.templates[template_name] = template
            self.logger.debug(f"加载模板成功: {template_name} | 尺寸: {template.shape[:2]}")
            return True
        except Exception as e:
            self.logger.error(f"加载模板异常: {str(e)}", exc_info=True)
            return False

    # ========== 2. 模板缩放（融合 DPI + 分辨率） ==========
    def _scale_template_to_current_size(
        self,
        template: np.ndarray,
        dpi_scale: float,
        hwnd: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        """
        将模板缩放到匹配当前显示大小和 DPI 的尺寸。

        注意：此方法假设 coord_transformer._current_client_size 存储的是逻辑像素尺寸。
        """
        if not self.coord_transformer:
            self.logger.warning("_scale_template_to_current_size: 未设置 coord_transformer。")
            return template

        try:
            # === 1. 判断窗口是否为全屏 ===
            is_fullscreen = self.coord_transformer._is_current_window_fullscreen(hwnd)

            # === 2. 获取当前的逻辑客户区尺寸 ===
            logical_client_w, logical_client_h = self.coord_transformer._current_client_size

            # === 3. 计算当前窗口的物理尺寸 ===
            # 这个物理尺寸是用于与原始基准分辨率比较的
            current_phys_w = logical_client_w * dpi_scale
            current_phys_h = logical_client_h * dpi_scale

            # === 4. 获取原始基准分辨率（物理像素）===
            orig_base_w, orig_base_h = self.original_base_res

            # === 5. 计算缩放比例 ===
            # 使用当前物理尺寸与原始基准物理尺寸的比例
            # 我们只关心宽度方向的缩放，因为通常 UI 是等比缩放的
            total_scale = current_phys_w / orig_base_w

            # 如果是全屏模式，可能需要考虑高度比例，但这里简化处理
            if is_fullscreen:
                # 全屏模式下，可以使用更复杂的缩放策略
                # 但为了简单，我们先保持一致
                pass

            # === 6. 验证并应用最终缩放 ===
            if total_scale <= 0:
                self.logger.error(f"_scale_template_to_current_size: 无效的总缩放因子: {total_scale}")
                return template

            scaled_w = max(self.min_template_size[0], int(round(template.shape[1] * total_scale)))
            scaled_h = max(self.min_template_size[1], int(round(template.shape[0] * total_scale)))

            interpolation = cv2.INTER_AREA if total_scale < 1.0 else cv2.INTER_CUBIC
            scaled_template = cv2.resize(template, (scaled_w, scaled_h), interpolation=interpolation)

            self.logger.debug(
                f"模板缩放完成 | 模式: {'全屏' if is_fullscreen else '窗口'} | "
                f"DPI: {dpi_scale:.2f} | "
                f"逻辑客户区: ({logical_client_w}, {logical_client_h}) | "
                f"物理客户区: ({current_phys_w:.1f}, {current_phys_h:.1f}) | "
                f"原始基准分辨率: {self.original_base_res} | "
                f"总缩放因子: {total_scale:.4f} | "
                f"缩放后模板尺寸: {scaled_template.shape[:2]}"
            )

            return scaled_template

        except Exception as e:
            self.logger.error(f"_scale_template_to_current_size 执行失败: {e}", exc_info=True)
            return template
        

    # ========== 3. 辅助函数：边缘提取 ==========
    def _to_edge(self, img: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        return cv2.Canny(gray, 30, 120)

    # ========== 4. 辅助函数：形状一致性校验 ==========
    def _check_shape_consistency(self, patch: np.ndarray, template: np.ndarray) -> bool:
        try:
            edge_p = self._to_edge(patch)
            edge_t = self._to_edge(template)
            contours_p = cv2.findContours(edge_p, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
            contours_t = cv2.findContours(edge_t, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
            if not contours_p or not contours_t:
                return True
            area_p = cv2.contourArea(max(contours_p, key=cv2.contourArea))
            area_t = cv2.contourArea(max(contours_t, key=cv2.contourArea))
            ratio = area_p / (area_t + 1e-8)
            return 0.7 < ratio < 1.3  # 宽松 ±30%
        except Exception:
            return True

    # ========== 5. 核心匹配逻辑（多尺度 + 自适应） ==========
    def match_template(
        self,
        image: np.ndarray,
        template: Union[str, np.ndarray],
        dpi_scale: float = 1.0,
        hwnd: Optional[int] = None,
        threshold: float = 0.8,
        scale_template: bool = True,
        roi: Optional[Tuple[int, int, int, int]] = None,
        is_base_roi: bool = False
    ) -> Optional[Tuple[int, int, int, int]]:
        try:
            # -------------------------- 1. 初始化 --------------------------
            if isinstance(template, str):
                template_img = self.get_template(template)
                if template_img is None:
                    self.logger.error(f"模板「{template}」不存在或加载失败")
                    return None
            else:
                template_img = template
                if template_img is None:
                    self.logger.error("自定义模板为None，匹配终止")
                    return None

            original_image = image.copy()
            template_name = template if isinstance(template, str) else "custom_template"
            template_name_safe = template_name.replace('/', '_').replace('\\', '_')

            roi_offset = (0, 0)
            if roi:
                roi_result = self.extract_roi_region(image, roi, is_base_roi)
                if len(roi_result) != 2:
                    self.logger.error(f"ROI提取返回值异常: {roi_result}，使用全图匹配")
                else:
                    image, roi_rect = roi_result
                    roi_offset = (roi_rect[0], roi_rect[1])

            # -------------------------- 2. 缩放基础模板（仅一次） --------------------------
            base_template = template_img
            if scale_template:
                base_template = self._scale_template_to_current_size(template_img, dpi_scale, hwnd)
                if base_template is None:
                    base_template = template_img
            base_template = base_template.astype(np.uint8)

            # -------------------------- 3. 多尺度匹配 --------------------------
            scales = [0.8, 0.9, 1.0, 1.1, 1.2]
            best_score = -1
            best_match = None

            gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
            gray_image = gray_image.astype(np.uint8)

            for scale in scales:
                scaled_temp = cv2.resize(base_template, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                h, w = scaled_temp.shape[:2]
                if h < self.min_template_size[0] or w < self.min_template_size[1]:
                    continue

                gray_temp = scaled_temp if len(scaled_temp.shape) == 2 else cv2.cvtColor(scaled_temp, cv2.COLOR_BGR2GRAY)
                gray_temp = gray_temp.astype(np.uint8)

                result = cv2.matchTemplate(gray_image, gray_temp, self.match_algorithms["gray"])
                if result.size == 0:
                    continue

                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                x, y = max_loc

                # 裁剪匹配区域用于形状校验
                if y + h > image.shape[0] or x + w > image.shape[1]:
                    continue
                patch = image[y:y+h, x:x+w]

                # 形状一致性校验（宽松）
                if not self._check_shape_consistency(patch, scaled_temp):
                    continue

                if max_val > best_score:
                    best_score = max_val
                    best_match = (x, y, w, h)

            # -------------------------- 4. 严格结果处理（仅当 ≥ threshold 才接受） --------------------------
            final_score = best_score
            if best_match and final_score >= threshold:
                match_x, match_y, templ_w, templ_h = best_match
            else:
                # 如果没有找到匹配项 或者 最佳分数低于阈值
                self.logger.debug(f"所有匹配未达标 | 最高分: {final_score:.4f} | 阈值: {threshold}")
                
                # === 关键修改：使用 best_match 的位置来保存调试图 ===
                if best_match is not None:
                    match_x, match_y, templ_w, templ_h = best_match
                else:
                    # 如果连 best_match 都是 None，则使用默认值
                    match_x, match_y, templ_w, templ_h = 0, 0, 10, 10

                save_path = os.path.join(self.debug_img_dir, f"{template_name_safe}_unmatched_{final_score:.4f}.png")
                self._save_match_debug_image(original_image, match_x, match_y, templ_w, templ_h, final_score, save_path)
                return None

            # 应用 ROI 偏移
            match_x += roi_offset[0]
            match_y += roi_offset[1]

            # 保存调试图
            save_filename = f"{template_name_safe}_match_{final_score:.4f}.png"
            save_path = os.path.join(self.debug_img_dir, save_filename)
            self._save_match_debug_image(original_image, match_x, match_y, templ_w, templ_h, final_score, save_path)

            self.logger.info(
                f"模板匹配成功 | 模板: {template_name} | 位置: ({match_x},{match_y}) | "
                f"尺寸: {templ_w}x{templ_h} | 分数: {final_score:.4f}"
            )

            return (match_x, match_y, templ_w, templ_h)

        except Exception as e:
            self.logger.error(f"模板匹配异常失败: {str(e)}", exc_info=True)
            return None

    def _create_default_logger(self) -> logging.Logger:
        logger = logging.getLogger("ImageProcessor")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def load_all_templates(self) -> None:
        """加载模板目录下所有支持格式的模板文件"""
        if not os.path.isdir(self.template_dir):
            self.logger.warning(f"模板目录不存在: {self.template_dir}")
            return

        for root, dirs, files in os.walk(self.template_dir):
            for filename in files:
                if filename.lower().endswith(TEMPLATE_EXTENSIONS):
                    rel_path = os.path.relpath(root, self.template_dir)
                    template_name = (
                        os.path.join(rel_path, os.path.splitext(filename)[0]).replace('\\', '/')
                        if rel_path != "." else os.path.splitext(filename)[0]
                    )
                    template_path = os.path.join(root, filename)
                    self.load_template(template_name, template_path)

    def get_template(self, template_name: str) -> Optional[np.ndarray]:
        loaded_names = list(self.templates.keys())
        self.logger.debug(f"获取模板: {template_name} | 已加载: {len(loaded_names)}")
        template = self.templates.get(template_name)
        if template is None:
            self.logger.warning(f"模板未找到，尝试重新加载: {template_name}")
            if self.load_template(template_name):
                template = self.templates.get(template_name)
        return template

    def save_template(self, template_name: str, image: np.ndarray) -> bool:
        try:
            template_path = os.path.join(self.template_dir, f"{template_name}.png")
            if len(image.shape) == 3:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            if image is None:
                self.logger.error("保存模板失败：图像为None")
                return False
            cv2.imwrite(template_path, image)
            self.load_template(template_name, template_path)
            self.logger.info(f"保存模板成功: {template_name} -> {template_path}")
            return True
        except Exception as e:
            self.logger.error(f"保存模板异常: {str(e)}", exc_info=True)
            return False

    def _save_match_debug_image(
        self,
        original_image: np.ndarray,
        match_x: int,
        match_y: int,
        templ_w: int,
        templ_h: int,
        match_confidence: float,
        save_path: str
    ) -> None:
        try:
            debug_image = cv2.cvtColor(original_image, cv2.COLOR_GRAY2BGR) if len(original_image.shape) == 2 else original_image.copy()
            cv2.rectangle(debug_image, (match_x, match_y), (match_x + templ_w, match_y + templ_h), (0, 0, 255), 2)
            center_x = match_x + templ_w // 2
            center_y = match_y + templ_h // 2
            cv2.circle(debug_image, (center_x, center_y), 3, (0, 255, 0), -1)
            text_lines = [
                f"Match: ({match_x}, {match_y})",
                f"Size: {templ_w}x{templ_h}",
                f"Center: ({center_x}, {center_y})",
                f"Confidence: {match_confidence:.4f}"
            ]
            text_y = max(0, match_y - 10)
            for i, line in enumerate(text_lines):
                y_pos = text_y - i * 20 if text_y - i * 20 > 0 else match_y + templ_h + 15 + i * 20
                cv2.putText(debug_image, line, (match_x, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
            info_text = f"Image: {debug_image.shape[1]}x{debug_image.shape[0]}"
            cv2.putText(debug_image, info_text, (debug_image.shape[1] - 200, debug_image.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.imwrite(save_path, debug_image)
            self.logger.info(f"调试图保存: {save_path} | 匹配度: {match_confidence:.4f}")
        except Exception as e:
            self.logger.error(f"保存调试图异常: {str(e)}", exc_info=True)

    def extract_roi_region(
        self,
        image: np.ndarray,
        roi: Tuple[int, int, int, int],
        is_base_roi: bool = False
    ) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        try:
            if image is None:
                self.logger.error("提取ROI失败：图像为None")
                raise ValueError("Input image cannot be None")
            roi_x, roi_y, roi_w, roi_h = roi
            if is_base_roi and self.coord_transformer:
                try:
                    converted_roi = self.coord_transformer.convert_original_rect_to_current_client(roi)
                    roi_x, roi_y, roi_w, roi_h = converted_roi
                except Exception as e:
                    self.logger.warning(f"ROI转换失败，使用原始ROI: {str(e)}")
            img_h, img_w = image.shape[:2]
            roi_x = max(0, min(roi_x, img_w - 1))
            roi_y = max(0, min(roi_y, img_h - 1))
            roi_w = max(1, min(roi_w, img_w - roi_x))
            roi_h = max(1, min(roi_h, img_h - roi_y))
            roi_image = image[roi_y:roi_y+roi_h, roi_x:roi_x+roi_w]
            self.logger.debug(f"提取ROI成功 | ROI: ({roi_x},{roi_y},{roi_w},{roi_h}) | 尺寸: {roi_image.shape[:2]}")
            return (roi_image, (roi_x, roi_y, roi_w, roi_h))
        except Exception as e:
            self.logger.error(f"提取ROI异常: {str(e)}", exc_info=True)
            if image is not None:
                return (image, (0, 0, image.shape[1], image.shape[0]))
            raise ValueError("Cannot extract ROI: input image is None")

    def get_center(self, rect: Union[Tuple[int, int, int, int], np.ndarray]) -> Tuple[int, int]:
        if rect is None:
            self.logger.warning("计算中心失败：矩形为None")
            return (0, 0)
        if isinstance(rect, np.ndarray):
            rect = tuple(rect.tolist())
        if not isinstance(rect, (tuple, list)) or len(rect) != 4:
            self.logger.warning(f"计算中心失败：无效矩形 {rect}")
            return (0, 0)
        try:
            x, y, w, h = map(int, rect)
            center_x = x + w // 2
            center_y = y + h // 2
            self.logger.debug(f"计算中心成功: {rect} -> ({center_x},{center_y})")
            return (center_x, center_y)
        except (ValueError, TypeError):
            self.logger.warning(f"计算中心失败：矩形值错误 {rect}")
            return (0, 0)

    def __len__(self) -> int:
        return len(self.templates)