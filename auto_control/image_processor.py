import cv2
import numpy as np
import os
from typing import Optional, Tuple, Dict, List, Union
import logging
import win32gui

# 导入坐标转换器
from auto_control.config.image_config import TEMPLATE_DIR, TEMPLATE_EXTENSIONS
from auto_control.coordinate_transformer import CoordinateTransformer


class ImageProcessor:
    """图像处理器：通用模板匹配优化（支持窗口化 + DPI缩放 + 多尺度匹配）"""

    def __init__(
        self,
        original_base_res: Tuple[int, int],
        original_dpi: float,
        logger: Optional[logging.Logger] = None,
        coord_transformer: Optional[CoordinateTransformer] = None,
        template_dir: str = TEMPLATE_DIR
    ):
        self.logger = logger or self._create_default_logger()
        self.template_dir = template_dir
        self.templates: Dict[str, np.ndarray] = {}
        self.coord_transformer = coord_transformer
        self.original_base_res = original_base_res
        self.original_dpi = original_dpi

        # 调试目录
        self.debug_img_dir = os.path.join(os.getcwd(), "debug", "image")
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
            f"原始基准分辨率: {self.original_base_res} | 原始DPI: {self.original_dpi}"
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
        current_dpi_scale: float,
        hwnd: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        if not self.coord_transformer:
            return template

        logical_w, logical_h = self.coord_transformer._current_client_size

        # === 关键：使用 CoordinateTransformer 判断是否全屏 ===
        is_fullscreen = self.coord_transformer._is_current_window_fullscreen(hwnd)

        # === 确定物理客户区尺寸 ===
        if is_fullscreen:
            physical_w, physical_h = logical_w, logical_h
            self.logger.debug("检测到全屏模式，物理尺寸 = 逻辑尺寸")
        else:
            # 窗口化：逻辑尺寸 / DPI = 物理像素尺寸
            physical_w = int(round(logical_w / current_dpi_scale))
            physical_h = int(round(logical_h / current_dpi_scale))

        if physical_w <= 0 or physical_h <= 0:
            self.logger.error(f"无效物理客户区: ({physical_w}, {physical_h})")
            return template

        orig_base_w, orig_base_h = self.original_base_res

        res_scale_x = physical_w / orig_base_w
        res_scale_y = physical_h / orig_base_h
        # 全屏时不需要再乘 DPI（因为物理尺寸已正确）
        total_scale = min(res_scale_x, res_scale_y) * (1.0 if is_fullscreen else current_dpi_scale)

        scaled_w = max(self.min_template_size[0], int(round(template.shape[1] * total_scale)))
        scaled_h = max(self.min_template_size[1], int(round(template.shape[0] * total_scale)))

        interpolation = cv2.INTER_CUBIC if total_scale >= 1.0 else cv2.INTER_AREA
        scaled_template = cv2.resize(template, (scaled_w, scaled_h), interpolation=interpolation)

        self.logger.debug(
            f"模板缩放完成 | "
            f"模式: {'全屏' if is_fullscreen else '窗口'} | "
            f"DPI比例: {current_dpi_scale:.2f} | "
            f"物理客户区: ({physical_w}, {physical_h}) | "
            f"分辨率比例: ({res_scale_x:.3f}, {res_scale_y:.3f}) | "
            f"总比例: {total_scale:.4f} | "
            f"缩放后尺寸: {scaled_template.shape[:2]}"
        )
        return scaled_template
        

    # ========== 3. 辅助函数：边缘提取 ==========
    def _to_edge(self, img: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        return cv2.Canny(gray, 30, 120)

    # ========== 4. 辅助函数：形状一致性校验（替代 Hu 矩） ==========
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
        current_dpi: float = 1.0,
        hwnd: Optional[int] = None,
        threshold: float = 0.8,  # 默认提高到 0.8
        is_base_template: bool = True,
        preprocess_params: Optional[Dict] = None,
        physical_screen_res: Optional[Tuple[int, int]] = None,
        roi: Optional[Tuple[int, int, int, int]] = None,
        is_base_roi: bool = False,
        use_two_stage: bool = True,
        top_k_candidates: int = 3,
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
            if is_base_template:
                base_template = self._scale_template_to_current_size(template_img, current_dpi, hwnd)
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
                self.logger.debug(f"所有匹配未达标 | 最高分: {final_score:.4f} | 阈值: {threshold}")
                save_path = os.path.join(self.debug_img_dir, f"{template_name_safe}_unmatched_{final_score:.4f}.png")
                self._save_match_debug_image(original_image, 0, 0, 10, 10, final_score, save_path)
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

    # ========== 保留原有其他方法（无需修改） ==========
    def _create_default_logger(self) -> logging.Logger:
        logger = logging.getLogger("ImageProcessor")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def load_all_templates(self) -> int:
        loaded = 0
        if not os.path.isdir(self.template_dir):
            self.logger.warning(f"模板目录不存在: {self.template_dir}")
            return 0
        for root, dirs, files in os.walk(self.template_dir):
            for filename in files:
                if filename.lower().endswith(TEMPLATE_EXTENSIONS):
                    rel_path = os.path.relpath(root, self.template_dir)
                    template_name = os.path.join(rel_path, os.path.splitext(filename)[0]).replace('\\', '/') if rel_path != "." else os.path.splitext(filename)[0]
                    template_path = os.path.join(root, filename)
                    if self.load_template(template_name, template_path):
                        loaded += 1
        return loaded

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

    def preprocess_image(
        self,
        image: np.ndarray,
        gray: bool = True,
        blur: bool = True,
        blur_ksize: Tuple[int, int] = (3, 3),
        threshold: bool = True,
        adaptive_threshold: bool = True,
        block_size: int = 11,
        c: int = 2
    ) -> np.ndarray:
        try:
            if image is None:
                self.logger.error("预处理失败：图像为None")
                raise ValueError("Input image cannot be None")
            result = image.copy()
            if gray and len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            if blur and blur_ksize[0] > 1 and blur_ksize[1] > 1:
                ksize = (blur_ksize[0] if blur_ksize[0] % 2 == 1 else blur_ksize[0] + 1, blur_ksize[1] if blur_ksize[1] % 2 == 1 else blur_ksize[1] + 1)
                result = cv2.GaussianBlur(result, ksize, 0)
            if threshold:
                if adaptive_threshold:
                    block_size = block_size if block_size % 2 == 1 else block_size + 1
                    result = cv2.adaptiveThreshold(result, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, c)
                else:
                    _, result = cv2.threshold(result, 127, 255, cv2.THRESH_BINARY)
            return result
        except Exception as e:
            self.logger.error(f"预处理异常: {str(e)}", exc_info=True)
            return image if image is not None else np.array([])

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