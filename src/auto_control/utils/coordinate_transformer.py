from typing import Tuple, Optional, Union
import win32gui
import win32con
import win32api
import numpy as np

from src.auto_control.utils.display_context import RuntimeDisplayContext


class CoordinateTransformer:
    """坐标转换工具类：基于 RuntimeDisplayContext 完成各类坐标转换+公共矩形/ROI处理"""

    def __init__(self, display_context: RuntimeDisplayContext, logger):
        """
        初始化坐标转换器
        
        :param display_context: 显示上下文容器（包含所有显示参数）
        :param logger: 日志实例
        """
        self._display_context = display_context  # 持有上下文引用（实时感知更新）
        self.logger = logger
        self.logger.info(
            f"坐标转换器初始化 | 原始基准分辨率: {display_context.original_base_res}"
        )
        # 全屏判定误差容忍度
        self.FULLSCREEN_ERROR_TOLERANCE = 5
        # 默认ROI安全扩展像素（OCR用，ImageProcessor可关闭）
        self.DEFAULT_ROI_EXPAND_PIXEL = 10

    # ------------------------------ 原有方法保持不变 ------------------------------
    @property
    def display_context(self) -> "RuntimeDisplayContext":
        return self._display_context

    @property
    def is_fullscreen(self) -> bool:
        return self._check_fullscreen()

    def is_fullscreen_method(self) -> bool:
        return self._check_fullscreen()

    def _check_fullscreen(self) -> bool:
        ctx = self._display_context
        hwnd = ctx.hwnd
        if not hwnd:
            self.logger.warning("上下文未设置窗口句柄，无法判断全屏状态")
            return False

        try:
            win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(hwnd)
            win_width = win_right - win_left
            win_height = win_bottom - win_top
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            window_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            is_maximized = (window_style & win32con.WS_MAXIMIZE) != 0

            size_match = (
                abs(win_width - screen_width) < self.FULLSCREEN_ERROR_TOLERANCE and
                abs(win_height - screen_height) < self.FULLSCREEN_ERROR_TOLERANCE
            )
            position_match = (
                abs(win_left) < self.FULLSCREEN_ERROR_TOLERANCE and
                abs(win_top) < self.FULLSCREEN_ERROR_TOLERANCE
            )
            fullscreen = size_match and position_match

            self.logger.debug(
                f"全屏状态检查 | "
                f"窗口句柄: {hwnd} | 最大化: {is_maximized} | "
                f"窗口尺寸: {win_width}x{win_height} | 屏幕分辨率: {screen_width}x{screen_height} | "
                f"尺寸匹配: {size_match} | 位置匹配: {position_match} | 全屏判定: {fullscreen}"
            )
            return fullscreen
        except Exception as e:
            self.logger.error(f"检查全屏状态失败: {str(e)}", exc_info=True)
            return False

    def convert_original_to_current_client(self, x: int, y: int) -> Tuple[int, int]:
        ctx = self._display_context
        orig_w, orig_h = ctx.original_base_res
        curr_logical_w, curr_logical_h = ctx.client_logical_res
        if orig_w <= 0 or orig_h <= 0 or curr_logical_w <= 0 or curr_logical_h <= 0:
            self.logger.error(f"无效分辨率，无法转换坐标 | 原始: {orig_w}x{orig_h}, 当前逻辑: {curr_logical_w}x{curr_logical_h}")
            return (x, y)

        scale_x = curr_logical_w / orig_w
        scale_y = curr_logical_h / orig_h
        final_x = int(round(x * scale_x))
        final_y = int(round(y * scale_y))
        final_x = max(0, min(final_x, curr_logical_w - 1))
        final_y = max(0, min(final_y, curr_logical_h - 1))

        self.logger.debug(
            f"原始→客户区逻辑 | 原始: ({x},{y}) → 客户区逻辑: ({final_x},{final_y}) [缩放比 x:{scale_x:.2f}, y:{scale_y:.2f}]"
        )
        return (final_x, final_y)

    # ------------------------------ 核心修复：统一矩形缩放比（坐标+宽高用相同缩放比） ------------------------------
    def convert_original_rect_to_current_client(self, rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            self.logger.error(f"无效矩形尺寸: {rect}")
            return rect

        ctx = self._display_context
        orig_w, orig_h = ctx.original_base_res
        curr_logical_w, curr_logical_h = ctx.client_logical_res
        if orig_w <= 0 or orig_h <= 0 or curr_logical_w <= 0 or curr_logical_h <= 0:
            self.logger.error(f"无效分辨率，无法转换矩形 | 原始: {orig_w}x{orig_h}, 当前逻辑: {curr_logical_w}x{curr_logical_h}")
            return rect

        # 关键修复：坐标和宽高使用相同的缩放比（之前宽高用content_scale_ratio导致不一致）
        scale_x = curr_logical_w / orig_w
        scale_y = curr_logical_h / orig_h
        new_x = int(round(x * scale_x))
        new_y = int(round(y * scale_y))
        new_w = int(round(w * scale_x))  # 宽高用对应轴的缩放比，而非统一scale
        new_h = int(round(h * scale_y))

        # 边界限制（避免超出客户区逻辑尺寸）
        new_x = max(0, new_x)
        new_y = max(0, new_y)
        new_w = max(1, min(new_w, curr_logical_w - new_x))
        new_h = max(1, min(new_h, curr_logical_h - new_y))

        self.logger.debug(
            f"原始→客户区矩形 | 原始: {rect} → 客户区逻辑: ({new_x},{new_y},{new_w},{new_h}) [缩放比 x:{scale_x:.2f}, y:{scale_y:.2f}]"
        )
        return (new_x, new_y, new_w, new_h)

    def convert_client_logical_to_physical(self, x: int, y: int) -> Tuple[int, int]:
        ctx = self._display_context
        ratio = ctx.logical_to_physical_ratio

        phys_x = int(round(x * ratio))
        phys_y = int(round(y * ratio))
        phys_w, phys_h = ctx.client_physical_res
        phys_x = max(0, min(phys_x, phys_w - 1))
        phys_y = max(0, min(phys_y, phys_h - 1))

        self.logger.debug(
            f"客户区逻辑→物理 | 逻辑: ({x},{y}) → 物理: ({phys_x},{phys_y}) [比例: {ratio:.2f}]"
        )
        return (phys_x, phys_y)

    def convert_client_logical_to_screen_physical(self, x: int, y: int) -> Tuple[int, int]:
        ctx = self._display_context
        hwnd = ctx.hwnd
        if not hwnd:
            self.logger.error("上下文未设置窗口句柄，无法转换为屏幕坐标")
            return (x, y)

        phys_x, phys_y = self.convert_client_logical_to_physical(x, y)
        try:
            screen_x, screen_y = win32gui.ClientToScreen(hwnd, (phys_x, phys_y))
            self.logger.debug(
                f"客户区逻辑→屏幕物理 | 逻辑: ({x},{y}) → 物理: ({phys_x},{phys_y}) → 屏幕: ({screen_x},{screen_y})"
            )
            return (screen_x, screen_y)
        except Exception as e:
            self.logger.error(f"转换到屏幕坐标失败: {str(e)}")
            return (phys_x, phys_y)

    def convert_client_physical_to_logical(self, x: int, y: int) -> Tuple[int, int]:
        ctx = self._display_context
        ratio = ctx.logical_to_physical_ratio

        if ratio <= 0:
            self.logger.error(f"无效的逻辑-物理比例: {ratio}，无法转换坐标")
            return (x, y)

        logical_x = int(round(x / ratio))
        logical_y = int(round(y / ratio))
        logical_w, logical_h = ctx.client_logical_res
        logical_x = max(0, min(logical_x, logical_w - 1))
        logical_y = max(0, min(logical_y, logical_h - 1))

        self.logger.debug(
            f"客户区物理→逻辑 | 物理: ({x},{y}) → 逻辑: ({logical_x},{logical_y}) [比例: {ratio:.2f}]"
        )
        return (logical_x, logical_y)

    def convert_client_physical_rect_to_logical(self, rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            self.logger.error(f"无效矩形尺寸: {rect}")
            return rect

        new_x, new_y = self.convert_client_physical_to_logical(x, y)
        ctx = self._display_context
        ratio = ctx.logical_to_physical_ratio
        new_w = int(round(w / ratio)) if ratio > 0 else w
        new_h = int(round(h / ratio)) if ratio > 0 else h
        new_w = max(1, new_w)
        new_h = max(1, new_h)

        self.logger.debug(
            f"客户区物理矩形→逻辑 | 物理: {rect} → 逻辑: ({new_x},{new_y},{new_w},{new_h}) [比例: {ratio:.2f}]"
        )
        return (new_x, new_y, new_w, new_h)

    # ------------------------------ 新增公共方法（ROI+矩形处理） ------------------------------
    def validate_roi_format(self, roi: Union[Tuple[int, int, int, int], list]) -> Tuple[bool, Optional[str]]:
        """
        校验ROI格式有效性（通用校验，两个处理器共用）
        :param roi: 输入ROI (x, y, w, h)
        :return: (是否有效, 错误信息/None)
        """
        if not isinstance(roi, (tuple, list)) or len(roi) != 4:
            return False, f"ROI格式无效（需为4元组/列表），当前: {type(roi)} {roi}"
        
        x, y, w, h = roi
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            return False, f"ROI参数无效（x/y非负，w/h正数），当前: ({x}, {y}, {w}, {h})"
        
        return True, None

    def process_roi(
        self,
        roi: Union[Tuple[int, int, int, int], list],
        boundary_width: int,
        boundary_height: int,
        enable_expand: bool = False,
        expand_pixel: Optional[int] = None
    ) -> Tuple[Optional[Tuple[int, int, int, int]], Tuple[int, int]]:
        """
        通用ROI处理（整合格式校验、全屏/窗口转换、边界限制、安全扩展）
        :param roi: 输入ROI (x, y, w, h)：默认是基准分辨率坐标（全屏/窗口模式通用输入）
        :param boundary_width: 边界宽度（图像/客户区物理宽度，用于限制ROI）
        :param boundary_height: 边界高度（图像/客户区物理高度，用于限制ROI）
        :param enable_expand: 是否启用安全扩展（OCR启用，ImageProcessor禁用）
        :param expand_pixel: 扩展像素数（默认使用DEFAULT_ROI_EXPAND_PIXEL）
        :return: (处理后的ROI物理坐标/None, ROI偏移量(phys_x, phys_y))
        """
        # 1. 基础格式校验
        is_valid, err_msg = self.validate_roi_format(roi)
        if not is_valid:
            self.logger.warning(f"ROI校验失败：{err_msg}")
            return None, (0, 0)
        
        x, y, w, h = roi
        is_fullscreen = self.is_fullscreen
        ctx = self._display_context
        roi_offset_phys = (0, 0)

        try:
            # 2. 全屏/窗口模式转换：统一转为物理坐标
            if is_fullscreen:
                # 全屏模式：基准ROI直接作为物理坐标（全屏时基准分辨率=屏幕物理分辨率）
                rx_phys, ry_phys, rw_phys, rh_phys = x, y, w, h
                self.logger.debug(f"全屏模式 | 基准ROI直接作为物理ROI: ({rx_phys},{ry_phys},{rw_phys},{rh_phys})")
            else:
                # 窗口模式：步骤1→基准ROI → 当前客户区逻辑ROI（修复后缩放比一致）
                rx_log, ry_log, rw_log, rh_log = self.convert_original_rect_to_current_client(roi)
                
                # 步骤2→限制逻辑ROI在客户区内（避免转换后仍超出的极端情况）
                client_w_log, client_h_log = ctx.client_logical_res
                rx_log = max(0, rx_log)
                ry_log = max(0, ry_log)
                rw_log = min(rw_log, client_w_log - rx_log)
                rh_log = min(rh_log, client_h_log - ry_log)
                
                if rw_log <= 0 or rh_log <= 0:
                    raise ValueError(
                        f"逻辑ROI超出客户区范围 | 基准ROI: {roi} → 转换后逻辑ROI: ({rx_log},{ry_log},{rw_log},{rh_log}) | "
                        f"客户区逻辑尺寸: {client_w_log}x{client_h_log}"
                    )
                
                # 步骤3→逻辑ROI → 物理ROI
                rx_phys, ry_phys = self.convert_client_logical_to_physical(rx_log, ry_log)
                ratio = ctx.logical_to_physical_ratio
                rw_phys = int(round(rw_log * ratio))
                rh_phys = int(round(rh_log * ratio))
                self.logger.debug(
                    f"窗口模式 | 逻辑ROI: ({rx_log},{ry_log},{rw_log},{rh_log}) → 物理ROI: ({rx_phys},{ry_phys},{rw_phys},{rh_phys})"
                )

            # 3. 边界限制（避免ROI超出图像/客户区物理尺寸）
            rx_phys = max(0, rx_phys)
            ry_phys = max(0, ry_phys)
            rw_phys = min(rw_phys, boundary_width - rx_phys)
            rh_phys = min(rh_phys, boundary_height - ry_phys)
            
            if rw_phys <= 0 or rh_phys <= 0:
                raise ValueError(f"物理ROI无效（尺寸≤0）: ({rx_phys}, {ry_phys}, {rw_phys}, {rh_phys})")

            # 4. 安全扩展（仅OCR启用）
            if enable_expand:
                expand_pixel = expand_pixel or self.DEFAULT_ROI_EXPAND_PIXEL
                new_rx = max(0, rx_phys - expand_pixel)
                new_ry = max(0, ry_phys - expand_pixel)
                new_rw = min(boundary_width - new_rx, rw_phys + 2 * expand_pixel)
                new_rh = min(boundary_height - new_ry, rh_phys + 2 * expand_pixel)
                
                # 极端情况：扩展后无效，退回到边界限制后的ROI
                if new_rw <= 0 or new_rh <= 0:
                    new_rx, new_ry, new_rw, new_rh = rx_phys, ry_phys, rw_phys, rh_phys
                    self.logger.debug(f"ROI扩展后无效，退回到边界限制后的ROI: ({new_rx},{new_ry},{new_rw},{new_rh})")
                else:
                    self.logger.debug(
                        f"ROI安全扩展 | 原始: ({rx_phys},{ry_phys},{rw_phys},{rh_phys}) → "
                        f"扩展后: ({new_rx},{new_ry},{new_rw},{new_rh}) | 扩展像素: {expand_pixel}"
                    )
                
                processed_roi_phys = (new_rx, new_ry, new_rw, new_rh)
                roi_offset_phys = (new_rx, new_ry)
            else:
                processed_roi_phys = (rx_phys, ry_phys, rw_phys, rh_phys)
                roi_offset_phys = (rx_phys, ry_phys)

            return processed_roi_phys, roi_offset_phys

        except Exception as e:
            self.logger.error(f"ROI处理失败：{str(e)}，切换为全图处理")
            return None, (0, 0)

    def get_rect_center(self, rect: Union[Tuple[int, int, int, int], list, np.ndarray]) -> Tuple[int, int]:
        """
        通用矩形中心计算
        :param rect: 输入矩形 (x, y, w, h)
        :return: 中心坐标 (center_x, center_y)
        """
        # 处理numpy数组格式
        if isinstance(rect, np.ndarray):
            rect = tuple(rect.tolist())
        
        # 校验矩形有效性
        is_valid, err_msg = self.validate_roi_format(rect)
        if not is_valid:
            self.logger.warning(f"计算中心失败：{err_msg}")
            return (0, 0)
        
        try:
            x, y, w, h = map(int, rect)
            center_x = x + w // 2
            center_y = y + h // 2
            self.logger.debug(f"计算矩形中心 | 矩形: {rect} → 中心: ({center_x}, {center_y})")
            return (center_x, center_y)
        except (ValueError, TypeError):
            self.logger.warning(f"计算中心失败：矩形值错误 {rect}")
            return (0, 0)

    def limit_rect_to_boundary(
        self,
        rect: Tuple[int, int, int, int],
        boundary_width: int,
        boundary_height: int
    ) -> Tuple[int, int, int, int]:
        """
        限制矩形在指定边界内（通用逻辑，避免超出图像/客户区）
        :param rect: 输入矩形 (x, y, w, h)
        :param boundary_width: 边界宽度
        :param boundary_height: 边界高度
        :return: 限制后的矩形
        """
        x, y, w, h = rect
        # 限制坐标在边界内
        x = max(0, min(x, boundary_width - 1))
        y = max(0, min(y, boundary_height - 1))
        # 限制宽高在边界内
        w = max(1, min(w, boundary_width - x))
        h = max(1, min(h, boundary_height - y))
        return (x, y, w, h)

    def convert_client_logical_rect_to_screen_physical(
        self, 
        rect: Union[Tuple[int, int, int, int], list], 
        is_base_coord: bool = False
    ) -> Union[Tuple[int, int, int, int], Tuple[()]]:
        """
        将客户区逻辑矩形（或基准分辨率矩形）转换为屏幕物理像素矩形
        
        核心逻辑：
        1. 若输入为基准坐标（is_base_coord=True）：先转客户区逻辑矩形 → 再转屏幕物理矩形
        2. 若输入为客户区逻辑坐标：直接转屏幕物理矩形（应用屏幕缩放因子）
        3. 自动处理边界校验、尺寸有效性保证（避免缩放后宽高为0）
        
        :param rect: 输入矩形，格式 (x, y, w, h)
                    - is_base_coord=False（默认）：客户区逻辑坐标
                    - is_base_coord=True：基准分辨率坐标（原始录制分辨率）
        :param is_base_coord: 是否为基准分辨率坐标（默认False）
        :return: 屏幕物理像素矩形 (x, y, w, h)，无效输入时返回空元组
        """
        # 1. 基础校验（统一返回空元组，明确无效状态）
        if not isinstance(rect, (tuple, list)) or len(rect) != 4:
            self.logger.error(f"无效矩形输入：{rect}（需为4元组/列表），无法转换为屏幕物理坐标")
            return ()
        
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            self.logger.error(f"无效矩形尺寸：{rect}（w/h需为正数），无法转换为屏幕物理坐标")
            return ()

        # 2. 基准坐标 → 客户区逻辑坐标（如需）
        logical_rect = rect
        if is_base_coord:
            logical_rect = self.convert_original_rect_to_current_client(rect)
            self.logger.debug(f"基准坐标→客户区逻辑矩形 | 输入: {rect} → 输出: {logical_rect}")

        # 3. 获取缩放因子（客户区逻辑 → 屏幕物理）
        ctx = self._display_context
        scale_x, scale_y = ctx.scale_factors
        if scale_x <= 0 or scale_y <= 0:
            self.logger.error(f"无效屏幕缩放因子：({scale_x}, {scale_y})，无法转换为屏幕物理坐标")
            return ()

        # 4. 计算屏幕物理坐标（四舍五入为整数像素）
        screen_x = int(round(logical_rect[0] * scale_x))
        screen_y = int(round(logical_rect[1] * scale_y))
        screen_w = int(round(logical_rect[2] * scale_x))
        screen_h = int(round(logical_rect[3] * scale_y))

        # 5. 确保尺寸有效（避免缩放后为0，影响后续使用）
        screen_w = max(1, screen_w)
        screen_h = max(1, screen_h)

        screen_rect = (screen_x, screen_y, screen_w, screen_h)
        self.logger.debug(
            f"客户区逻辑→屏幕物理矩形 | 输入逻辑矩形: {logical_rect} | "
            f"屏幕缩放因子: ({scale_x:.2f}, {scale_y:.2f}) | "
            f"输出屏幕物理矩形: {screen_rect}"
        )
        return screen_rect

    # ------------------------------ 新增：1. 子图坐标→原图物理坐标（偏移计算） ------------------------------
    def apply_roi_offset_to_subcoord(
        self,
        sub_coord: Union[Tuple[int, int], Tuple[int, int, int, int]],
        roi_offset_phys: Tuple[int, int]
    ) -> Union[Tuple[int, int], Tuple[int, int, int, int]]:
        """
        子图内坐标 → 原图物理坐标（应用ROI偏移量）
        :param sub_coord: 子图内坐标（单个坐标：(x,y) / 矩形：(x,y,w,h)）
        :param roi_offset_phys: ROI在原图的物理偏移量 (offset_x, offset_y)
        :return: 原图物理坐标（格式与输入一致）
        """
        if not sub_coord or len(sub_coord) not in (2, 4):
            self.logger.error(f"无效子图坐标输入：{sub_coord}（需为2元组/4元组）")
            return sub_coord
        
        offset_x, offset_y = roi_offset_phys
        if len(sub_coord) == 2:  # 单个坐标
            orig_x = sub_coord[0] + offset_x
            orig_y = sub_coord[1] + offset_y
            result = (orig_x, orig_y)
        else:  # 矩形坐标
            orig_x = sub_coord[0] + offset_x
            orig_y = sub_coord[1] + offset_y
            orig_w = sub_coord[2]
            orig_h = sub_coord[3]
            result = (orig_x, orig_y, orig_w, orig_h)
        
        self.logger.debug(
            f"子图坐标→原图物理坐标 | 子图坐标: {sub_coord} | 偏移量: {roi_offset_phys} → 原图坐标: {result}"
        )
        return result

    # ------------------------------ 新增：2. 物理坐标→屏幕物理坐标（单个/矩形） ------------------------------
    def convert_client_physical_to_screen_physical(self, x: int, y: int) -> Tuple[int, int]:
        """
        客户区物理坐标 → 屏幕物理坐标（单个坐标）
        """
        ctx = self._display_context
        hwnd = ctx.hwnd
        if not hwnd:
            self.logger.error("上下文未设置窗口句柄，无法转换为屏幕坐标")
            return (x, y)
        
        try:
            screen_x, screen_y = win32gui.ClientToScreen(hwnd, (x, y))
            self.logger.debug(
                f"客户区物理→屏幕物理 | 物理: ({x},{y}) → 屏幕: ({screen_x},{screen_y})"
            )
            return (screen_x, screen_y)
        except Exception as e:
            self.logger.error(f"转换到屏幕坐标失败: {str(e)}")
            return (x, y)

    def convert_client_physical_rect_to_screen_physical(
        self,
        rect: Union[Tuple[int, int, int, int], list]
    ) -> Union[Tuple[int, int, int, int], Tuple[()]]:
        """
        客户区物理矩形 → 屏幕物理矩形
        """
        # 复用已有的矩形校验逻辑
        is_valid, err_msg = self.validate_roi_format(rect)
        if not is_valid:
            self.logger.error(f"无效物理矩形输入：{err_msg}")
            return ()
        
        x, y, w, h = rect
        screen_x, screen_y = self.convert_client_physical_to_screen_physical(x, y)
        # 宽高无需转换（物理尺寸与屏幕物理尺寸单位一致）
        screen_rect = (screen_x, screen_y, w, h)
        self.logger.debug(
            f"客户区物理矩形→屏幕物理矩形 | 物理矩形: {rect} → 屏幕矩形: {screen_rect}"
        )
        return screen_rect

    # ------------------------------ 新增：3. 全屏/窗口模式下的逻辑坐标统一转换 ------------------------------
    def get_unified_logical_rect(
        self,
        phys_rect: Union[Tuple[int, int, int, int], list]
    ) -> Union[Tuple[int, int, int, int], Tuple[()]]:
        """
        统一转换物理矩形为逻辑矩形（自动适配全屏/窗口模式）
        - 全屏模式：直接返回物理矩形（全屏时物理坐标=逻辑坐标）
        - 窗口模式：物理矩形→逻辑矩形
        """
        if not self.is_fullscreen:
            return self.convert_client_physical_rect_to_logical(phys_rect)
        else:
            # 全屏时校验矩形有效性（避免超出屏幕）
            screen_w, screen_h = self._display_context.screen_physical_res
            limited_rect = self.limit_rect_to_boundary(phys_rect, screen_w, screen_h)
            self.logger.debug(
                f"全屏模式→逻辑矩形 | 物理矩形: {phys_rect} → 限制后逻辑矩形: {limited_rect}"
            )
            return limited_rect

    # ------------------------------ 新增：4. 模板缩放比例计算（基于基准分辨率/ROI） ------------------------------
    def calculate_template_scale_ratio(
        self,
        target_phys_size: Tuple[int, int],
        has_roi: bool = False,
        roi_logical_size: Optional[Tuple[int, int]] = None
    ) -> float:
        """
        计算模板缩放比例（统一基于基准分辨率/ROI尺寸）
        :param target_phys_size: 目标物理尺寸（图像/子图的宽高：(w, h)）
        :param has_roi: 是否基于ROI计算（True=用ROI逻辑尺寸，False=用基准分辨率）
        :param roi_logical_size: ROI的逻辑尺寸（(w, h)，has_roi=True时必需）
        :return: 缩放比例（min(宽比例, 高比例)）
        """
        target_w, target_h = target_phys_size
        if target_w <= 0 or target_h <= 0:
            self.logger.error(f"无效目标物理尺寸：{target_phys_size}，返回默认比例1.0")
            return 1.0
        
        ctx = self._display_context
        orig_base_w, orig_base_h = ctx.original_base_res
        
        if has_roi and roi_logical_size:
            roi_log_w, roi_log_h = roi_logical_size
            if roi_log_w <= 0 or roi_log_h <= 0:
                self.logger.warning(f"无效ROI逻辑尺寸：{roi_logical_size}， fallback到基准分辨率计算")
                has_roi = False
        
        # 计算比例（优先ROI，无则用基准分辨率）
        if has_roi and roi_logical_size:
            scale_ratio_w = target_w / roi_log_w
            scale_ratio_h = target_h / roi_log_h
            self.logger.debug(
                f"基于ROI计算缩放比例 | 目标物理尺寸: {target_phys_size} | "
                f"ROI逻辑尺寸: {roi_logical_size} | 宽比例: {scale_ratio_w:.4f} | 高比例: {scale_ratio_h:.4f}"
            )
        else:
            scale_ratio_w = target_w / orig_base_w
            scale_ratio_h = target_h / orig_base_h
            self.logger.debug(
                f"基于基准分辨率计算缩放比例 | 目标物理尺寸: {target_phys_size} | "
                f"基准分辨率: {orig_base_w}x{orig_base_h} | 宽比例: {scale_ratio_w:.4f} | 高比例: {scale_ratio_h:.4f}"
            )
        
        scale_ratio = min(scale_ratio_w, scale_ratio_h)
        self.logger.debug(f"最终模板缩放比例: {scale_ratio:.4f}")
        return scale_ratio