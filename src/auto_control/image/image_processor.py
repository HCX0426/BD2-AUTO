import datetime
import logging
import os
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

# 导入坐标转换器
from src.auto_control.config.auto_config import TEMPLATE_EXTENSIONS
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.core.path_manager import path_manager

class ImageProcessor:
    """图像处理器：通用模板匹配优化（支持窗口化 + DPI缩放 + 多尺度匹配）

    注意：所有模板必须在目标应用全屏运行时录制，
    且 original_base_res 必须设置为录制时的物理屏幕分辨率（如 1920x1080）。
    窗口模式下运行时会自动根据 DPI 和客户区尺寸进行适配。
    """

    def __init__(
        self,
        original_base_res: Tuple[int, int],
        logger: Optional[logging.Logger] = None,
        coord_transformer: Optional[CoordinateTransformer] = None,
        template_dir: str = None
    ) -> None:
        """初始化图像处理器

        Args:
            original_base_res: 原始基准分辨率 (width, height)
            logger: 日志记录器实例
            coord_transformer: 坐标转换器实例
            template_dir: 模板目录路径
        """
        self.logger = logger or self._create_default_logger()
        self.template_dir = path_manager.get("task_template")
        self.templates: Dict[str, np.ndarray] = {}
        self.coord_transformer = coord_transformer
        self.original_base_res = original_base_res

        # 调试目录
        self.debug_img_dir = path_manager.get("match_temple_debug")

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

    def load_template(self, template_name: str, template_path: Optional[str] = None) -> bool:
        """加载原始彩色模板图像。

        Args:
            template_name: 模板名称
            template_path: 模板文件路径，如果为None则根据模板名称自动构建路径

        Returns:
            bool: 加载成功返回True，否则返回False
        """
        try:
            if not template_path:
                template_path = os.path.join(self.template_dir, f"{template_name}.png")
            if not os.path.exists(template_path):
                self.logger.error(f"模板不存在: {template_path}")
                return False

            # 直接加载彩色图像
            template_color = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template_color is None:
                self.logger.error(f"读取模板失败 (可能不是有效的图像文件): {template_path}")
                return False

            # 以 BGR 格式存储
            self.templates[template_name] = template_color
            # self.logger.debug(f"加载模板成功: {template_name} | 尺寸: {template_color.shape[:2]} (H, W)")
            return True
        except Exception as e:
            self.logger.error(f"加载模板异常: {str(e)}", exc_info=True)
            return False

    def _scale_template_to_current_size(
        self,
        template: np.ndarray,
        dpi_scale: float,
        hwnd: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        """将模板缩放到匹配当前显示大小和 DPI 的尺寸。

        注意：此方法假设 coord_transformer._current_client_size 存储的是逻辑像素尺寸。

        Args:
            template: 原始模板图像
            dpi_scale: DPI缩放因子
            hwnd: 窗口句柄

        Returns:
            Optional[np.ndarray]: 缩放后的模板图像，如果失败则返回None
        """

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

            # 如果是全屏模式，可能需要考虑高度比例
            if is_fullscreen:
                # 先保持一致
                pass

            # === 6. 验证并应用最终缩放 ===
            if total_scale <= 0:
                self.logger.error(f"无效的总缩放因子: {total_scale}")
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
            self.logger.error(f"执行失败: {e}", exc_info=True)
            return template

    def match_template(
        self,
        image: np.ndarray,
        template: Union[str, np.ndarray],
        dpi_scale: float = 1.0,
        hwnd: Optional[int] = None,
        threshold: float = 0.9,
        scale_template: bool = True,
        roi: Optional[Tuple[int, int, int, int]] = None,
        is_base_roi: bool = False
    ) -> Optional[Tuple[int, int, int, int]]:
        """改进版模板匹配，按速度和鲁棒性组合多种方法。
        在每个尺度上尝试多种匹配方法，并收集所有高于阈值的结果。

        Args:
            image: 输入图像（BGR格式）
            template: 模板名称或模板图像数组
            dpi_scale: DPI缩放因子，默认为1.0
            hwnd: 窗口句柄，默认为None
            threshold: 匹配阈值，默认为0.9
            scale_template: 是否缩放模板，默认为True
            roi: 感兴趣区域 (x, y, w, h)，默认为None
            is_base_roi: ROI是否基于原始基准分辨率，默认为False

        Returns:
            Optional[Tuple[int, int, int, int]]: 匹配位置 (x, y, w, h)，如果未找到匹配则返回None
        """
        try:
            if isinstance(template, str):
                template_bgr = self.get_template(template)
                if template_bgr is None:
                    self.logger.error(f"模板「{template}」不存在或加载失败")
                    return None
            else:
                template_bgr = template
                if template_bgr is None:
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

            base_template_bgr = template_bgr
            if scale_template:
                scaled_template = self._scale_template_to_current_size(template_bgr, dpi_scale, hwnd)
                if scaled_template is not None:
                    base_template_bgr = scaled_template

            if len(image.shape) == 3:
                image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                image_gray = image
            image_gray = image_gray.astype(np.uint8)

            # --- 5. 多尺度匹配准备 ---
            scales = [0.8, 0.9, 1.0, 1.1, 1.2]
            all_matches = []  # 存储 (score, (x, y, w, h), method_name)
            early_stop_threshold = 0.95  # 如果找到分数高于此值的匹配，可考虑提前停止后续尺度

            # --- 6. 按尺度循环执行匹配 ---
            for scale in scales:
                h_orig, w_orig = base_template_bgr.shape[:2]
                scaled_w = max(1, int(round(w_orig * scale)))
                scaled_h = max(1, int(round(h_orig * scale)))

                if scaled_h < self.min_template_size[0] or scaled_w < self.min_template_size[1]:
                    continue

                scaled_template_gray = cv2.resize(cv2.cvtColor(base_template_bgr, cv2.COLOR_BGR2GRAY) if len(
                    base_template_bgr.shape) == 3 else base_template_bgr, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)
                scaled_template_bgr = cv2.resize(base_template_bgr, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)

                methods_to_try = [
                    ("Gray", lambda: self._match_gray(image_gray, scaled_template_gray)),
                    ("Color", lambda: self._match_color(image, scaled_template_bgr)),  # 注意传入的是原图 image 和彩色模板
                    ("Edge", lambda: self._match_edge(image_gray, scaled_template_gray)),
                    ("ORB", lambda: self._match_orb(image_gray, scaled_template_gray))
                ]

                found_high_confidence_match_in_this_scale = False

                for method_name, method_func in methods_to_try:
                    try:
                        score, location_data = method_func()

                        if method_name == "ORB":
                            if score >= threshold:
                                all_matches.append((score, location_data, method_name))
                                if score >= early_stop_threshold:
                                    found_high_confidence_match_in_this_scale = True
                                    break
                        else:
                            if score >= threshold:
                                x, y = location_data
                                all_matches.append((score, (x, y, scaled_w, scaled_h), method_name))
                                if score >= early_stop_threshold:
                                    found_high_confidence_match_in_this_scale = True
                                    break

                    except Exception as e:
                        self.logger.warning(f"匹配方法 {method_name} 在尺度 {scale} 执行时出错: {e}")

                if found_high_confidence_match_in_this_scale:
                    break  # 提前停止后续尺度匹配

            if not all_matches:
                return None

            best_match = max(all_matches, key=lambda item: item[0])
            final_score, final_bbox, method_used = best_match
            match_x, match_y, templ_w, templ_h = final_bbox

            match_x += roi_offset[0]
            match_y += roi_offset[1]
            
            # 获取当前时间并格式化为时分秒
            current_time = datetime.datetime.now().strftime("%H%M%S")
            save_filename = f"{template_name_safe}_match_{final_score:.4f}_{method_used}_{current_time}.png"
            save_path = os.path.join(self.debug_img_dir, save_filename)
            self._save_match_debug_image(original_image, match_x, match_y, templ_w, templ_h, final_score, save_path)

            self.logger.info(
                f"模板匹配成功 | 模板: {template_name} | 方法: {method_used} | 位置: ({match_x},{match_y}) | 尺寸: {templ_w}x{templ_h} | 分数: {final_score:.4f}")

            return (match_x, match_y, templ_w, templ_h)

        except Exception as e:
            self.logger.error(f"模板匹配异常失败: {str(e)}", exc_info=True)
            return None

    def _create_default_logger(self) -> logging.Logger:
        """创建默认日志记录器

        Returns:
            logging.Logger: 默认日志记录器实例
        """
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
        """获取指定名称的模板

        Args:
            template_name: 模板名称

        Returns:
            Optional[np.ndarray]: 模板图像数组，如果未找到则返回None
        """
        loaded_names = list(self.templates.keys())
        self.logger.debug(f"获取模板: {template_name} | 已加载: {len(loaded_names)}")
        template = self.templates.get(template_name)
        if template is None:
            self.logger.warning(f"模板未找到，尝试重新加载: {template_name}")
            if self.load_template(template_name):
                template = self.templates.get(template_name)
        return template

    def save_template(self, template_name: str, image: np.ndarray) -> bool:
        """保存模板图像"""
        try:
            template_path = os.path.join(self.template_dir, f"{template_name}.png")

            if image is None:
                self.logger.error("保存模板失败：图像为None")
                return False

            # 确保图像是 uint8 格式
            if image.dtype != np.uint8:
                image = np.clip(image, 0, 255).astype(np.uint8)

            cv2.imwrite(template_path, image)
            self.load_template(template_name, template_path)
            self.logger.info(f"保存模板成功: {template_name} -> {template_path} | 尺寸: {image.shape}")
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
        """保存匹配调试图像

        Args:
            original_image: 原始图像
            match_x: 匹配位置x坐标
            match_y: 匹配位置y坐标
            templ_w: 模板宽度
            templ_h: 模板高度
            match_confidence: 匹配置信度
            save_path: 保存路径
        """
        try:
            debug_image = cv2.cvtColor(original_image, cv2.COLOR_GRAY2BGR) if len(
                original_image.shape) == 2 else original_image.copy()
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
                cv2.putText(debug_image, line, (match_x, y_pos),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
            info_text = f"Image: {debug_image.shape[1]}x{debug_image.shape[0]}"
            cv2.putText(debug_image, info_text, (debug_image.shape[1] - 200, debug_image.shape[0] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
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
        """提取感兴趣区域

        Args:
            image: 输入图像
            roi: 感兴趣区域 (x, y, w, h)
            is_base_roi: ROI是否基于原始基准分辨率

        Returns:
            Tuple[np.ndarray, Tuple[int, int, int, int]]: (裁剪后的图像, (x_offset, y_offset, width, height))

        Raises:
            ValueError: 当输入图像为None时抛出
        """
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
        """计算矩形中心点

        Args:
            rect: 矩形 (x, y, w, h)

        Returns:
            Tuple[int, int]: 中心点坐标 (x, y)
        """
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

    def _to_edge(self, img: np.ndarray) -> np.ndarray:
        """提取图像边缘

        Args:
            img: 输入图像

        Returns:
            np.ndarray: 边缘图像
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        return cv2.Canny(gray, 30, 120)

    def _match_gray(
        self,
        image_gray: np.ndarray,
        template_gray: np.ndarray,
        mask: Optional[np.ndarray] = None
    ) -> Tuple[float, Tuple[int, int]]:
        """灰度模板匹配 (最快)

        Args:
            image_gray: 灰度图像
            template_gray: 灰度模板
            mask: 掩码图像

        Returns:
            Tuple[float, Tuple[int, int]]: (最大匹配值, 最佳匹配位置)
        """
        try:
            # 使用归一化相关系数匹配
            res = cv2.matchTemplate(image_gray, template_gray, cv2.TM_CCOEFF_NORMED, mask=mask)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            return max_val, max_loc
        except Exception as e:
            self.logger.error(f"_match_gray 执行失败: {e}", exc_info=True)
            return -1, (0, 0)

    def _match_color(
        self,
        image_bgr: np.ndarray,
        template_bgr: np.ndarray,
        mask: Optional[np.ndarray] = None
    ) -> Tuple[float, Tuple[int, int]]:
        """彩色模板匹配 (较快)

        Args:
            image_bgr: BGR图像
            template_bgr: BGR模板
            mask: 掩码图像

        Returns:
            Tuple[float, Tuple[int, int]]: (平均匹配值, 最佳匹配位置)
        """
        try:
            # 分别匹配三个通道，然后取平均
            scores = []
            locs = []
            for i in range(3):  # B, G, R
                res = cv2.matchTemplate(image_bgr[:, :, i], template_bgr[:, :, i], cv2.TM_CCOEFF_NORMED, mask=mask)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                scores.append(max_val)
                locs.append(max_loc)

            # 简单平均分数和位置 (可以根据需要加权)
            avg_score = np.mean(scores)
            # 位置通常是一致的，取第一个即可，或做更复杂的聚合
            avg_loc = locs[0]

            return float(avg_score), avg_loc
        except Exception as e:
            self.logger.error(f"_match_color 执行失败: {e}", exc_info=True)
            return -1, (0, 0)

    def _match_edge(
        self,
        image_gray: np.ndarray,
        template_gray: np.ndarray
    ) -> Tuple[float, Tuple[int, int]]:
        """基于边缘的模板匹配 (中等速度)

        Args:
            image_gray: 灰度图像
            template_gray: 灰度模板

        Returns:
            Tuple[float, Tuple[int, int]]: (最大匹配值, 最佳匹配位置)
        """
        try:
            # 提取边缘
            edge_img = self._to_edge(image_gray)
            edge_tpl = self._to_edge(template_gray)

            # 边缘匹配
            res = cv2.matchTemplate(edge_img, edge_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            return max_val, max_loc
        except Exception as e:
            self.logger.error(f"_match_edge 执行失败: {e}", exc_info=True)
            return -1, (0, 0)

    def _match_orb(
        self,
        image_gray: np.ndarray,
        template_gray: np.ndarray
    ) -> Tuple[float, Tuple[int, int, int, int]]:
        """ORB 特征点匹配 (较慢但鲁棒)

        Args:
            image_gray: 灰度图像
            template_gray: 灰度模板

        Returns:
            Tuple[float, Tuple[int, int, int, int]]: (置信度分数, (x, y, w, h)) 或 (-1, (0,0,0,0)) 如果失败
        """
        try:
            # 初始化 ORB 检测器
            orb = cv2.ORB_create(nfeatures=500)  # 可调参数
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

            # 检测关键点和描述符
            kp1, des1 = orb.detectAndCompute(template_gray, None)
            kp2, des2 = orb.detectAndCompute(image_gray, None)

            if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
                self.logger.debug("ORB匹配失败：模板或图像中未检测到足够特征点")
                return -1, (0, 0, 0, 0)

            # 特征点匹配
            matches = bf.match(des1, des2)
            if len(matches) < 10:  # 最少匹配点数
                self.logger.debug(f"ORB匹配点数不足: {len(matches)}")
                return -1, (0, 0, 0, 0)

            # 按距离排序
            matches = sorted(matches, key=lambda x: x.distance)

            # 提取匹配点坐标
            src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
            dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

            # 使用 RANSAC 查找单应性变换矩阵
            M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
            matches_mask = mask.ravel().tolist()

            if M is None or sum(matches_mask) < 10:  # 有效内点数
                self.logger.debug("ORB RANSAC 内点数不足")
                return -1, (0, 0, 0, 0)

            # 计算模板在图像中的边界框
            h, w = template_gray.shape
            pts = np.float32([[0, 0], [0, h - 1], [w - 1, h - 1], [w - 1, 0]]).reshape(-1, 1, 2)
            dst = cv2.perspectiveTransform(pts, M)

            x_min = int(np.min(dst[:, :, 0]))
            x_max = int(np.max(dst[:, :, 0]))
            y_min = int(np.min(dst[:, :, 1]))
            y_max = int(np.max(dst[:, :, 1]))

            # 计算置信度 (可以用内点比例等衡量)
            confidence = sum(matches_mask) / len(matches_mask) if len(matches_mask) > 0 else 0

            # 可以根据匹配点数量、内点比例等进一步调整 confidence
            # 这里简单地将其映射到 0-1 范围，例如乘以一个系数
            adjusted_confidence = min(1.0, confidence * 2)  # 简单放大

            return adjusted_confidence, (x_min, y_min, x_max - x_min, y_max - y_min)

        except Exception as e:
            self.logger.error(f"_match_orb 执行失败: {e}", exc_info=True)
            return -1, (0, 0, 0, 0)

    def find_color_location(
        self,
        image: np.ndarray,
        target_color: Union[Tuple[int, int, int], List[Tuple[int, int, int]], np.ndarray],  # 支持单个BGR颜色、颜色列表或颜色掩码图像
        roi: Optional[Tuple[int, int, int, int]] = None,
        tolerance: int = 20,  # 颜色容差
        is_base_roi: bool = False  # 是否需要坐标转换
    ) -> Optional[Tuple[int, int, int, int]]:
        """在图像指定区域内查找目标颜色或颜色集合的位置。

        Args:
            image: 输入的BGR图像。
            target_color: 要查找的目标颜色。
                - 单个BGR元组: (B, G, R)
                - BGR颜色元组列表: [(B1, G1, R1), (B2, G2, R2), ...]
                - 二值掩码图像 (np.ndarray): 与image同尺寸，非零处为目标颜色区域。
            roi: 搜索区域 (x, y, w, h)。默认为None，表示全图搜索。
            tolerance: 颜色容差（用于范围匹配）。默认为20。
            is_base_roi: roi坐标是否基于原始基准分辨率，需要转换。默认False。

        Returns:
            Optional[Tuple[int, int, int, int]]: 如果找到，返回匹配区域的 (x, y, w, h)；否则返回None。
        """
        try:
            roi_offset = (0, 0)
            # 1. ROI 提取
            if roi:
                extracted_result = self.extract_roi_region(image, roi, is_base_roi)
                if isinstance(extracted_result, tuple) and len(extracted_result) >= 2:
                    image, roi_rect = extracted_result
                    roi_offset = (roi_rect[0], roi_rect[1])
                else:
                    self.logger.error("ROI提取失败，使用全图进行颜色匹配。")
                    # 不返回，继续使用全图 image

            # 2. 颜色匹配逻辑
            matched_mask = None
            if isinstance(target_color, (tuple, list)) and len(target_color) > 0:
                # 处理单个颜色或颜色列表
                if isinstance(target_color[0], int):  # 单个 (B, G, R) 元组
                    target_colors = [target_color]
                else:  # 颜色元组列表
                    target_colors = target_color

                matched_mask = np.zeros(image.shape[:2], dtype=np.uint8)
                for color in target_colors:
                    # 定义颜色范围
                    b, g, r = color
                    lower_bound = np.array([max(0, b - tolerance), max(0, g - tolerance), max(0, r - tolerance)])
                    upper_bound = np.array([min(255, b + tolerance), min(255, g + tolerance), min(255, r + tolerance)])

                    # 创建该颜色的掩码并合并
                    color_mask = cv2.inRange(image, lower_bound, upper_bound)
                    matched_mask = cv2.bitwise_or(matched_mask, color_mask)

            elif isinstance(target_color, np.ndarray) and target_color.ndim == 2:  # 掩码图像
                # 假设 target_color 是一个与 image 同尺寸的二值掩码
                if target_color.shape[:2] == image.shape[:2]:  # 检查尺寸
                    matched_mask = target_color
                else:
                    self.logger.error("提供的颜色掩码图像尺寸与目标图像不匹配。")
                    return None
            else:
                self.logger.error("无效的 target_color 参数类型或格式。")
                return None

            # 3. 查找轮廓或最大连通域
            if matched_mask is not None and np.any(matched_mask):
                # 可选：形态学操作去噪 (可根据需要启用)
                # kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
                # matched_mask = cv2.morphologyEx(matched_mask, cv2.MORPH_OPEN, kernel)

                contours, _ = cv2.findContours(matched_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if contours:
                    # 找到最大的轮廓（或其他策略，如最近的轮廓等）
                    largest_contour = max(contours, key=cv2.contourArea)
                    x, y, w, h = cv2.boundingRect(largest_contour)

                    # 4. 应用ROI偏移
                    final_x = x + roi_offset[0]
                    final_y = y + roi_offset[1]

                    self.logger.debug(f"颜色匹配成功: 位置({final_x}, {final_y}), 尺寸({w}, {h})")
                    return (final_x, final_y, w, h)

            self.logger.debug("在指定区域内未找到匹配的颜色。")
            return None

        except Exception as e:
            self.logger.error(f"find_color_location 执行失败: {e}", exc_info=True)
            return None
