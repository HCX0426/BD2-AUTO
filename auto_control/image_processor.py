import cv2
import numpy as np
import os
from typing import Optional, Tuple, Dict, List, Union
import logging
import win32gui

# 导入坐标转换器
from auto_control.config.image_config import TEMPLATE_DIR,TEMPLATE_EXTENSIONS
from auto_control.coordinate_transformer import CoordinateTransformer


class ImageProcessor:
    """图像处理器：修复基础分辨率模板适配窗口化问题（先缩放模板再匹配）"""
    
    def __init__(
        self,
        original_base_res: Tuple[int, int],
        original_dpi: float,
        logger: Optional[logging.Logger] = None,
        coord_transformer: Optional[CoordinateTransformer] = None,
        template_dir: str = TEMPLATE_DIR
    ):
        """
        初始化图像处理器
        :param original_base_res: 模板采集时的基准分辨率（默认1920×1080，与用户模板一致）
        :param original_dpi: 模板采集时的DPI缩放因子
        """
        self.logger = logger or self._create_default_logger()
        self.template_dir = template_dir
        self.templates: Dict[str, np.ndarray] = {}  # 存储模板图像: 名称 -> 图像矩阵
        self.coord_transformer = coord_transformer  # 坐标转换器实例
        self.original_base_res = original_base_res  # 模板原始基准分辨率
        self.original_dpi = original_dpi  # 模板采集时的DPI缩放因子
        
        # 确保模板目录存在
        if not os.path.exists(self.template_dir):
            os.makedirs(self.template_dir)
            self.logger.info(f"创建模板目录: {self.template_dir}")
        
        # 加载目录中的所有模板
        self.load_all_templates()
        self.logger.info(
            f"图像处理器初始化完成 | 加载模板数: {len(self.templates)} | "
            f"模板原始基准分辨率: {self.original_base_res} | "
            f"模板原始DPI: {self.original_dpi}"
        )

    def _create_default_logger(self) -> logging.Logger:
        """创建默认日志器（无外部日志时使用）"""
        logger = logging.getLogger("ImageProcessor")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def load_template(self, template_name: str, template_path: Optional[str] = None) -> bool:
        """加载单个模板图像（保持不变）"""
        try:
            # 确定模板路径
            if not template_path:
                template_path = os.path.join(self.template_dir, f"{template_name}.png")
            
            # 检查文件是否存在
            if not os.path.exists(template_path):
                self.logger.error(f"模板文件不存在: {template_path}")
                return False
            
            # 读取模板（灰度图，便于匹配）
            template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            if template is None:
                self.logger.error(f"无法读取模板文件: {template_path}（文件损坏或格式错误）")
                return False
            
            self.templates[template_name] = template
            return True
        except Exception as e:
            self.logger.error(f"加载模板失败: {str(e)}", exc_info=True)
            return False

    def load_all_templates(self) -> int:
        """加载模板目录中的所有PNG模板（包括子目录，保持不变）"""
        loaded = 0
        if not os.path.isdir(self.template_dir):
            self.logger.warning(f"模板目录不存在: {self.template_dir}")
            return 0
        
        # 递归搜索所有子目录中的PNG文件
        for root, dirs, files in os.walk(self.template_dir):
            for filename in files:
                if filename.lower().endswith(TEMPLATE_EXTENSIONS):
                    # 使用相对路径作为模板名称，避免重名冲突
                    rel_path = os.path.relpath(root, self.template_dir)
                    if rel_path == ".":
                        template_name = os.path.splitext(filename)[0]
                    else:
                        template_name = os.path.join(rel_path, os.path.splitext(filename)[0]).replace('\\', '/')
                    
                    template_path = os.path.join(root, filename)
                    if self.load_template(template_name, template_path):
                        loaded += 1
        return loaded

    def get_template(self, template_name: str) -> Optional[np.ndarray]:
        """获取已加载的模板（保持不变）"""
        loaded_names = list(self.templates.keys())
        self.logger.debug(f"尝试获取模板: {template_name} | 已加载模板数: {len(loaded_names)}")
        
        # 从字典获取模板（不存在则返回None）
        template = self.templates.get(template_name)
        
        if template is None:
            self.logger.warning(f"未找到模板: {template_name}（尝试重新加载）")
            # 尝试重新加载模板
            if self.load_template(template_name):
                template = self.templates.get(template_name)
                if template is not None:
                    self.logger.info(f"模板重新加载成功: {template_name} | 尺寸: {template.shape[:2]}")
                else:
                    self.logger.error(f"模板重新加载失败: {template_name}（加载后仍为None）")
            else:
                self.logger.error(f"模板重新加载失败: {template_name}（文件不存在或读取错误）")
        if template is not None:
            self.logger.debug(f"返回模板: {template_name} | 类型: {type(template)} | 形状: {template.shape}")
        else:
            self.logger.debug(f"返回模板: {template_name} | 结果: None")
        return template

    def save_template(self, template_name: str, image: np.ndarray) -> bool:
        """保存图像作为模板（保持不变）"""
        try:
            template_path = os.path.join(self.template_dir, f"{template_name}.png")
            # 确保是灰度图
            if len(image.shape) == 3:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            # 检查图像是否有效
            if image is None:
                self.logger.error("无法保存模板：输入图像为None")
                return False
            cv2.imwrite(template_path, image)
            # 立即加载新模板
            self.load_template(template_name, template_path)
            self.logger.info(f"模板保存成功: {template_name} -> {template_path} | 尺寸: {image.shape[:2]}")
            return True
        except Exception as e:
            self.logger.error(f"保存模板失败: {str(e)}", exc_info=True)
            return False

    def remove_template(self, template_name: str) -> bool:
        """删除模板（保持不变）"""
        if template_name in self.templates:
            del self.templates[template_name]
            # 删除文件
            template_path = os.path.join(self.template_dir, f"{template_name}.png")
            if os.path.exists(template_path):
                os.remove(template_path)
                self.logger.info(f"模板文件已删除: {template_path}")
            self.logger.info(f"模板已移除: {template_name}")
            return True
        self.logger.warning(f"无法删除模板: {template_name}（不存在）")
        return False

    def _scale_template_to_current_size(
        self, 
        template: np.ndarray, 
        current_dpi: float, 
        hwnd: Optional[int] = None,
        physical_screen_res: Optional[Tuple[int, int]] = None  # 新增：物理屏幕分辨率
    ) -> Optional[np.ndarray]:
        """
        核心修正：按窗口状态选择缩放基准
        - 全屏时：使用 physical_screen_res 作为缩放基准（需传入且有效）
        - 非全屏时：使用 coord_transformer._current_client_size 作为缩放基准
        """
        if not self.coord_transformer:
            self.logger.warning("无坐标转换器，无法缩放模板，使用原始尺寸")
            return template
        
        # -------------------------- 核心逻辑：按全屏状态选择缩放基准 --------------------------
        # 1. 先判断当前窗口是否为全屏
        is_fullscreen = False
        if hwnd and hasattr(self.coord_transformer, '_is_current_window_fullscreen'):
            is_fullscreen = self.coord_transformer._is_current_window_fullscreen(hwnd)
        self.logger.debug(f"窗口全屏状态: {is_fullscreen} | 传入物理屏幕分辨率: {physical_screen_res}")
        
        # 2. 根据全屏状态选择 curr_client_size（缩放基准）
        curr_client_size = None
        if is_fullscreen:
            # 全屏场景：必须使用物理屏幕分辨率（需校验有效性）
            if physical_screen_res is None:
                self.logger.error("全屏模式下必须传入物理屏幕分辨率（physical_screen_res），无法缩放模板")
                return template
            # 校验物理屏幕分辨率格式和值有效性
            if not isinstance(physical_screen_res, tuple) or len(physical_screen_res) != 2:
                self.logger.error(f"物理屏幕分辨率格式无效: {physical_screen_res}，需传入(宽, 高)元组（如(1920, 1080)）")
                return template
            phys_w, phys_h = physical_screen_res
            if not (isinstance(phys_w, int) and isinstance(phys_h, int) and phys_w > 0 and phys_h > 0):
                self.logger.error(f"物理屏幕分辨率值无效: {physical_screen_res}，宽高必须为正整数")
                return template
            # 全屏时确定缩放基准为物理屏幕分辨率
            curr_client_size = physical_screen_res
            self.logger.debug(f"全屏模式：使用物理屏幕分辨率作为缩放基准 -> {curr_client_size}（宽×高）")
        else:
            # 非全屏场景：使用坐标转换器的客户端尺寸作为缩放基准
            curr_client_size = self.coord_transformer._current_client_size
            # 校验客户端尺寸有效性
            curr_w, curr_h = curr_client_size
            if curr_w <= 0 or curr_h <= 0:
                self.logger.error(f"非全屏模式下客户端尺寸无效: {curr_client_size}，无法缩放模板")
                return template
            self.logger.debug(f"非全屏模式：使用客户端尺寸作为缩放基准 -> {curr_client_size}（宽×高）")
        # ------------------------------------------------------------------------------
        
        # 获取模板原始基准分辨率
        orig_base_w, orig_base_h = self.original_base_res
        curr_w, curr_h = curr_client_size
        
        # 计算分辨率缩放比例（按原始基准与当前基准的比例，保持宽高比）
        resolution_scale_ratio = min(curr_w / orig_base_w, curr_h / orig_base_h)
        
        # 计算DPI缩放比例（仅非全屏时生效，全屏时DPI缩放通常为1.0）
        dpi_scale_ratio = 1.0
        if not is_fullscreen:
            dpi_scale_ratio = self.original_dpi / current_dpi
            self.logger.debug(f"非全屏模式：DPI缩放比例 -> {dpi_scale_ratio:.2f}（原始DPI: {self.original_dpi}，当前DPI: {current_dpi}）")
        
        # 总缩放比例 = 分辨率比例 × DPI比例
        total_scale_ratio = resolution_scale_ratio * dpi_scale_ratio
        
        # 计算缩放后模板尺寸（确保为正整数，避免过小）
        scaled_template_w = int(round(template.shape[1] * total_scale_ratio))
        scaled_template_h = int(round(template.shape[0] * total_scale_ratio))
        scaled_template_w = max(10, scaled_template_w)  # 最小10px，避免匹配失效
        scaled_template_h = max(10, scaled_template_h)
        
        # 选择插值方式（缩小用INTER_AREA，放大用INTER_CUBIC，保证清晰度）
        interpolation = cv2.INTER_AREA if total_scale_ratio < 1.0 else cv2.INTER_CUBIC
        scaled_template = cv2.resize(template, (scaled_template_w, scaled_template_h), interpolation=interpolation)
        
        # 输出缩放详情日志
        self.logger.debug(
            f"模板缩放完成 | 原始尺寸: {template.shape[:2]} | 总缩放比例: {total_scale_ratio:.2f} | "
            f"缩放后尺寸: {scaled_template.shape[:2]} | 原始基准分辨率: {orig_base_w}x{orig_base_h}"
        )
        return scaled_template

    def match_template(
        self,
        image: np.ndarray,
        template: Union[str, np.ndarray],
        current_dpi: float = 1.0,
        hwnd: Optional[int] = None,
        threshold: float = 0.6,
        is_base_template: bool = True,
        preprocess_params: Optional[Dict] = None,
        physical_screen_res: Optional[Tuple[int, int]] = None
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        单模板匹配（修正逻辑）：
        - 需传入hwnd（窗口句柄）以判断全屏状态
        - 全屏时必须传入physical_screen_res（物理屏幕分辨率），否则匹配失败
        - 非全屏时使用客户端尺寸作为缩放基准，无需物理屏参数
        - 修正：返回的坐标已减去标题栏高度，为纯客户区坐标
        """
        try:
            # -------------------------- 前置校验：确保关键参数存在 --------------------------
            if hwnd is None:
                self.logger.error("模板匹配失败：必须传入hwnd（窗口句柄）以判断全屏状态")
                return None
            # 全屏场景下强制校验物理屏参数
            if hasattr(self.coord_transformer, '_is_current_window_fullscreen'):
                is_fullscreen = self.coord_transformer._is_current_window_fullscreen(hwnd)
                if is_fullscreen and physical_screen_res is None:
                    self.logger.error("全屏模式下模板匹配失败：必须传入physical_screen_res（物理屏幕分辨率）")
                    return None
            # ------------------------------------------------------------------------------
            
            # 1. 获取并验证模板图像
            if isinstance(template, str):
                template_img = self.get_template(template)
                if template_img is None:
                    self.logger.error(f"模板匹配失败：模板「{template}」不存在或加载错误")
                    return None
            else:
                template_img = template
                # 转换为灰度图（与后续处理统一）
                if len(template_img.shape) == 3:
                    template_img = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
                if template_img is None:
                    self.logger.error("模板匹配失败：传入的自定义模板图像为None")
                    return None
            
            # 2. 核心：按窗口状态缩放模板（传入物理屏参数）
            if is_base_template:
                template_img = self._scale_template_to_current_size(
                    template_img, current_dpi, hwnd, physical_screen_res  # 传递关键参数
                )
                if template_img is None:
                    self.logger.error("模板缩放失败，终止匹配")
                    return None
            
            # 3. 验证待匹配图像（截图）并转为灰度图
            if image is None:
                self.logger.error("模板匹配失败：待匹配图像（截图）为None")
                return None
            gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
            
            # 4. 计算标题栏高度（关键修正）- 使用您提供的方法
            title_bar_height = 0
            if not is_fullscreen and hwnd:
                try:
                    # 获取窗口矩形和客户区矩形（物理尺寸）
                    window_rect = win32gui.GetWindowRect(hwnd)
                    client_rect_phys = win32gui.GetClientRect(hwnd)
                    
                    # 计算窗口物理尺寸和客户区物理尺寸
                    window_w_phys = window_rect[2] - window_rect[0]  # 窗口物理宽度（含标题栏）
                    window_h_phys = window_rect[3] - window_rect[1]  # 窗口物理高度（含标题栏）
                    client_w_phys = client_rect_phys[2] - client_rect_phys[0]  # 客户区物理宽度
                    client_h_phys = client_rect_phys[3] - client_rect_phys[1]  # 客户区物理高度
                    
                    # 计算标题栏高度 = 窗口物理高度 - 客户区物理高度
                    title_bar_height = window_h_phys - client_h_phys
                    
                    # 合理性校验：标题栏高度应该在合理范围内（正常20-50px）
                    if title_bar_height < 0 or title_bar_height > 100:
                        self.logger.warning(f"标题栏高度异常: {title_bar_height}px，使用默认值0")
                        title_bar_height = 0
                    else:
                        self.logger.debug(f"标题栏高度计算: 窗口高{window_h_phys} - 客户区高{client_h_phys} = {title_bar_height}px")
                        
                except Exception as e:
                    self.logger.warning(f"计算标题栏高度失败: {str(e)}，使用默认值0")
            
            # 5. 校验模板尺寸是否小于截图尺寸（匹配前提）
            img_h, img_w = gray_image.shape
            templ_h, templ_w = template_img.shape
            if templ_w > img_w or templ_h > img_h:
                self.logger.error(
                    f"模板尺寸超过截图尺寸，无法匹配 | 模板: {templ_w}x{templ_h} | 截图: {img_w}x{img_h}"
                )
                return None
            
            # 6. 图像预处理（模板与截图统一处理，避免差异）
            default_preprocess = {
                "blur": True, "blur_ksize": (3, 3),
                "threshold": True, "adaptive_threshold": True,
                "block_size": 11, "c": 2
            }
            preprocess_cfg = {**default_preprocess, **(preprocess_params or {})}
            processed_image = self.preprocess_image(gray_image, **preprocess_cfg)
            processed_template = self.preprocess_image(template_img, **preprocess_cfg)
            
            # 7. 执行模板匹配（使用归一化相关系数，适合明暗变化场景）
            result = cv2.matchTemplate(processed_image, processed_template, cv2.TM_CCOEFF_NORMED)
            max_val = np.max(result) if result.size > 0 else 0.0  # 最大匹配度
            
            # 8. 筛选有效匹配（高于阈值）
            if max_val < threshold:
                self.logger.debug(
                    f"未找到有效匹配 | 模板: {template if isinstance(template, str) else '自定义'} | "
                    f"最大匹配度: {max_val:.4f} < 阈值: {threshold}"
                )
                return None
            
            # 9. 定位最佳匹配位置（转换为(x,y)坐标，result默认是(y,x)）
            max_loc = np.unravel_index(np.argmax(result), result.shape)
            match_x, match_y = max_loc[1], max_loc[0]
            
            # 10. 关键修正：减去标题栏高度，得到纯客户区坐标
            if not is_fullscreen and title_bar_height > 0:
                original_y = match_y
                match_y = max(0, match_y - title_bar_height)  # 确保不会变成负数
                self.logger.debug(f"标题栏高度修正: Y坐标 {original_y} -> {match_y} (减去{title_bar_height}px)")

            # self._save_match_debug_image(
            #     image, template_img, match_x, match_y, templ_w, templ_h, 
            #     max_val, "debug_match_result.png")
            
            self.logger.info(
                f"模板匹配成功 | 模板: {template if isinstance(template, str) else '自定义'} | "
                f"匹配位置: ({match_x},{match_y}) | 模板尺寸: {templ_w}x{templ_h} | "
                f"匹配度: {max_val:.4f} | 标题栏修正: -{title_bar_height}px | "
                f"全屏状态: {is_fullscreen}"
            )
            
            # 11. 返回匹配区域（x, y, 宽, 高），便于后续计算中心坐标
            return (match_x, match_y, templ_w, templ_h)
        except Exception as e:
            self.logger.error(f"模板匹配异常失败: {str(e)}", exc_info=True)
            return None
        
    def _save_match_debug_image(
        self,
        original_image: np.ndarray,
        template_img: np.ndarray,
        match_x: int,
        match_y: int,
        templ_w: int,
        templ_h: int,
        match_confidence: float,
        save_path: str
    ) -> None:
        """保存匹配结果的调试图片，用矩形框标出匹配位置并显示坐标信息"""
        try:
            # 创建原图的彩色副本用于绘制
            if len(original_image.shape) == 2:
                debug_image = cv2.cvtColor(original_image, cv2.COLOR_GRAY2BGR)
            else:
                debug_image = original_image.copy()
            
            # 绘制匹配位置的矩形框（红色，2像素宽）
            cv2.rectangle(
                debug_image,
                (match_x, match_y),
                (match_x + templ_w, match_y + templ_h),
                (0, 0, 255),  # 红色 (BGR)
                2
            )
            
            # 计算中心点坐标
            center_x = match_x + templ_w // 2
            center_y = match_y + templ_h // 2
            
            # 绘制中心点（绿色圆点）
            cv2.circle(debug_image, (center_x, center_y), 3, (0, 255, 0), -1)  # 绿色实心圆
            
            # 添加坐标信息文本（多行显示）
            text_lines = [
                f"Match: ({match_x}, {match_y})",
                f"Size: {templ_w}x{templ_h}",
                f"Center: ({center_x}, {center_y})",
                f"Confidence: {match_confidence:.4f}"
            ]
            
            # 设置文本位置和样式
            text_y = max(0, match_y - 10)  # 在矩形框上方显示
            for i, line in enumerate(text_lines):
                y_position = text_y - i * 20  # 每行向上偏移20像素
                if y_position < 0:  # 如果超出图像顶部，显示在矩形框下方
                    y_position = match_y + templ_h + 15 + i * 20
                
                cv2.putText(
                    debug_image,
                    line,
                    (match_x, y_position),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 0, 255),  # 红色
                    1,
                    cv2.LINE_AA
                )
            
            # 在图像右下角添加全局信息
            info_text = f"Image: {debug_image.shape[1]}x{debug_image.shape[0]}"
            cv2.putText(
                debug_image,
                info_text,
                (debug_image.shape[1] - 200, debug_image.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (255, 255, 255),  # 白色
                1,
                cv2.LINE_AA
            )
            
            # 保存图片
            cv2.imwrite(save_path, debug_image)
            self.logger.info(
                f"调试图片已保存: {save_path} | "
                f"匹配位置: ({match_x},{match_y}) | "
                f"中心点: ({center_x},{center_y}) | "
                f"匹配度: {match_confidence:.4f}"
            )
            
        except Exception as e:
            self.logger.error(f"保存调试图片失败: {str(e)}", exc_info=True)

    def get_roi_region(
        self,
        image: np.ndarray,
        roi: Tuple[int, int, int, int],
        is_base_roi: bool = False
    ) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        """修复ROI转换方法名错误，保持不变"""
        try:
            if image is None:
                self.logger.error("获取ROI失败：输入图像为None")
                raise ValueError("Input image cannot be None")
            
            roi_x, roi_y, roi_w, roi_h = roi
            
            # 基准ROI（1920×1080）转换为当前客户端尺寸
            if is_base_roi and self.coord_transformer:
                try:
                    converted_roi = self.coord_transformer.convert_original_rect_to_current_client(roi)
                    roi_x, roi_y, roi_w, roi_h = converted_roi
                    self.logger.debug(f"基准ROI转换成功: {roi} -> {converted_roi}")
                except Exception as e:
                    self.logger.warning(f"ROI转换失败，使用原始ROI: {str(e)}")
            
            # 确保ROI在图像范围内（防止越界报错）
            img_h, img_w = image.shape[:2]
            roi_x = max(0, min(roi_x, img_w - 1))
            roi_y = max(0, min(roi_y, img_h - 1))
            roi_w = max(1, min(roi_w, img_w - roi_x))
            roi_h = max(1, min(roi_h, img_h - roi_y))
            
            # 提取ROI区域
            roi_image = image[roi_y:roi_y+roi_h, roi_x:roi_x+roi_w]
            self.logger.debug(f"获取ROI成功 | 最终ROI: ({roi_x},{roi_y},{roi_w},{roi_h}) | ROI尺寸: {roi_image.shape[:2]}")
            return (roi_image, (roi_x, roi_y, roi_w, roi_h))
        except Exception as e:
            self.logger.error(f"获取ROI异常失败: {str(e)}", exc_info=True)
            if image is not None:
                full_roi = (0, 0, image.shape[1], image.shape[0])
                return (image, full_roi)
            raise ValueError("Cannot return ROI: input image is None")

    def find_multiple_matches(
        self,
        image: np.ndarray,
        template: Union[str, np.ndarray],
        current_dpi: float = 1.0,
        hwnd: Optional[int] = None,  # 必须传入：判断全屏状态
        threshold: float = 0.8,
        max_matches: int = 10,
        is_base_template: bool = True,
        physical_screen_res: Optional[Tuple[int, int]] = None  # 全屏时必填
    ) -> List[Tuple[int, int, int, int]]:
        """多模板匹配（同步修正逻辑，与单匹配保持一致）"""
        matches = []
        try:
            # -------------------------- 前置校验：关键参数 --------------------------
            if hwnd is None:
                self.logger.error("多模板匹配失败：必须传入hwnd（窗口句柄）以判断全屏状态")
                return matches
            # 全屏时强制校验物理屏参数
            is_fullscreen = False
            if hasattr(self.coord_transformer, '_is_current_window_fullscreen'):
                is_fullscreen = self.coord_transformer._is_current_window_fullscreen(hwnd)
                if is_fullscreen and physical_screen_res is None:
                    self.logger.error("全屏模式下多匹配失败：必须传入physical_screen_res（物理屏幕分辨率）")
                    return matches
            # ------------------------------------------------------------------------------
            
            # 1. 获取并验证模板
            if isinstance(template, str):
                template_img = self.get_template(template)
                if template_img is None:
                    self.logger.error(f"多匹配失败：模板「{template}」不存在或加载错误")
                    return matches
            else:
                template_img = template
                if len(template_img.shape) == 3:
                    template_img = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
                if template_img is None:
                    self.logger.error("多匹配失败：自定义模板图像为None")
                    return matches
            
            # 2. 按窗口状态缩放模板
            if is_base_template:
                template_img = self._scale_template_to_current_size(
                    template_img, current_dpi, hwnd, physical_screen_res
                )
                if template_img is None:
                    self.logger.error("模板缩放失败，终止多匹配")
                    return matches
            
            # 3. 处理待匹配图像
            if image is None:
                self.logger.error("多匹配失败：待匹配图像为None")
                return matches
            gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
            
            # 4. 校验模板与截图尺寸
            img_h, img_w = gray_image.shape
            templ_h, templ_w = template_img.shape
            if templ_w > img_w or templ_h > img_h:
                self.logger.error(
                    f"多匹配失败：模板尺寸({templ_w}x{templ_h})超过截图尺寸({img_w}x{img_h})"
                )
                return matches
            
            # 5. 执行模板匹配
            result = cv2.matchTemplate(gray_image, template_img, cv2.TM_CCOEFF_NORMED)
            # 筛选所有高于阈值的匹配位置（转换为(x,y)）
            match_locations = list(zip(*np.where(result >= threshold)[::-1]))
            if not match_locations:
                self.logger.debug(f"多匹配未找到有效区域 | 阈值: {threshold} | 模板: {template if isinstance(template, str) else '自定义'}")
                return matches
            
            # 6. 去重（避免重叠匹配，基于模板尺寸的1/2作为重叠阈值）
            used_positions = []
            for (x, y) in match_locations:
                # 检查当前位置是否与已保留位置重叠
                is_overlap = any(
                    abs(x - ox) < templ_w//2 and abs(y - oy) < templ_h//2
                    for (ox, oy, _, _) in used_positions
                )
                if not is_overlap:
                    used_positions.append((x, y, templ_w, templ_h))
                    self.logger.debug(f"多匹配添加区域: ({x},{y}) | 尺寸: {templ_w}x{templ_h} | 当前数量: {len(used_positions)}")
                    # 达到最大匹配数则停止
                    if len(used_positions) >= max_matches:
                        break
            
            # 7. 输出结果日志
            self.logger.info(
                f"多模板匹配完成 | 模板: {template if isinstance(template, str) else '自定义'} | "
                f"有效匹配数: {len(used_positions)}/{len(match_locations)} | 最大匹配数限制: {max_matches} | "
                f"全屏状态: {is_fullscreen}"
            )
            return used_positions
        except Exception as e:
            self.logger.error(f"多模板匹配异常失败: {str(e)}", exc_info=True)
            return matches

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
        """图像预处理（保持不变，确保模板与截图处理一致）"""
        try:
            if image is None:
                self.logger.error("预处理失败：输入图像为None")
                raise ValueError("Input image cannot be None")
            
            result = image.copy()
            # 1. 灰度化（减少计算量，统一通道）
            if gray and len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            # 2. 高斯模糊（去噪，平滑细节）
            if blur and blur_ksize[0] > 1 and blur_ksize[1] > 1:
                # 确保卷积核为奇数（高斯模糊要求）
                ksize = (
                    blur_ksize[0] if blur_ksize[0] % 2 == 1 else blur_ksize[0] + 1,
                    blur_ksize[1] if blur_ksize[1] % 2 == 1 else blur_ksize[1] + 1
                )
                result = cv2.GaussianBlur(result, ksize, 0)
            # 3. 二值化（增强对比度，突出目标）
            if threshold:
                if adaptive_threshold:
                    # 自适应阈值：适合明暗不均场景（如游戏画面）
                    result = cv2.adaptiveThreshold(
                        result, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY,
                        block_size if block_size % 2 == 1 else block_size + 1,
                        c
                    )
                else:
                    # 固定阈值（备用）
                    _, result = cv2.threshold(result, 127, 255, cv2.THRESH_BINARY)
            return result
        except Exception as e:
            self.logger.error(f"图像预处理异常: {str(e)}", exc_info=True)
            return image if image is not None else np.array([])

    def get_center(self, rect: Union[Tuple[int, int, int, int], np.ndarray]) -> Tuple[int, int]:
        """计算矩形中心坐标（保持不变）"""
        if rect is None:
            self.logger.warning("计算中心失败：矩形参数为None")
            return (0, 0)
        # 转换numpy数组为元组
        if isinstance(rect, np.ndarray):
            rect = tuple(rect.tolist())
        # 校验矩形格式
        if not isinstance(rect, (tuple, list)) or len(rect) != 4:
            self.logger.warning(f"计算中心失败：矩形格式无效 {rect}（需4元素元组/列表）")
            return (0, 0)
        # 计算中心
        try:
            x, y, w, h = map(int, rect)
            center_x = x + w // 2
            center_y = y + h // 2
            self.logger.debug(f"矩形中心计算完成: {rect} -> ({center_x},{center_y})")
            return (center_x, center_y)
        except (ValueError, TypeError):
            self.logger.warning(f"计算中心失败：矩形包含非数字值 {rect}")
            return (0, 0)

    def __len__(self) -> int:
        """返回已加载模板数量（保持不变）"""
        return len(self.templates)