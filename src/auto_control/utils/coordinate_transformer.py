from typing import Tuple, Optional, Union, List
import win32gui
import win32con
import win32api
import numpy as np
import time

from src.auto_control.utils.display_context import RuntimeDisplayContext


class CoordinateTransformer:
    """
    坐标与ROI处理核心工具类，基于RuntimeDisplayContext实现全链路坐标转换。
    核心能力：
    1. 坐标体系转换：基准坐标↔客户区逻辑坐标↔客户区物理坐标↔屏幕物理坐标
    2. 矩形/ROI处理：格式校验、边界限制、安全扩展、全屏/窗口模式适配
    3. 辅助工具：矩形中心计算、模板缩放比计算、子图坐标偏移修正
    依赖：强依赖RuntimeDisplayContext的实时显示参数，感知窗口/屏幕状态变化
    """
    # 常量定义（核心参数，标注用途与取值依据）
    FULLSCREEN_ERROR_TOLERANCE: int = 5
    """全屏判定误差容忍度（像素）：兼容系统边框误差，差值小于该值判定为全屏"""
    DEFAULT_ROI_EXPAND_PIXEL: int = 10
    """ROI默认安全扩展像素（OCR专用）：避免目标边缘超出ROI导致识别失败"""
    FULLSCREEN_CACHE_DURATION: float = 0.5
    """全屏状态缓存时长（秒）：减少系统API调用频次，提升性能"""

    def __init__(self, display_context: RuntimeDisplayContext, logger):
        """
        初始化坐标转换器
        
        Args:
            display_context: 显示上下文容器（存储窗口/屏幕参数，实时更新）
            logger: 日志实例（输出转换过程、错误信息）
        """
        self._display_context = display_context  # 持有引用保证参数实时性
        self.logger = logger
        # 全屏状态缓存初始化
        self._fullscreen_cache: Optional[bool] = None
        self._fullscreen_cache_time: float = 0.0
        
        self.logger.info(
            f"坐标转换器初始化完成 | 原始基准分辨率: {display_context.original_base_res} | "
            f"全屏缓存时长: {self.FULLSCREEN_CACHE_DURATION * 1000}ms"
        )

    # ------------------------------ 内部辅助工具（复用通用逻辑）------------------------------
    def _ensure_positive_size(self, w: int, h: int) -> Tuple[int, int]:
        """确保矩形宽高大于0，最小为1"""
        return max(1, w), max(1, h)

    def _ensure_coords_in_boundary(self, x: int, y: int, boundary_w: int, boundary_h: int) -> Tuple[int, int]:
        """限制坐标在指定边界内 [0, boundary-1]"""
        return max(0, min(x, boundary_w - 1)), max(0, min(y, boundary_h - 1))

    def _ensure_rect_in_boundary(self, rect: Tuple[int, int, int, int], boundary_w: int, boundary_h: int) -> Tuple[int, int, int, int]:
        """限制矩形完全在指定边界内，保证尺寸≥1"""
        x, y, w, h = rect
        x, y = self._ensure_coords_in_boundary(x, y, boundary_w, boundary_h)
        w = max(1, min(w, boundary_w - x))
        h = max(1, min(h, boundary_h - y))
        return (x, y, w, h)

    def _convert_numpy_to_tuple(self, item: Union[Tuple, List, np.ndarray]) -> Union[Tuple, List]:
        """统一转换numpy数组为tuple/list，兼容多格式输入"""
        if isinstance(item, np.ndarray):
            return tuple(item.tolist())
        return item

    # ------------------------------ 基础属性（简化参数访问）------------------------------
    @property
    def display_context(self) -> RuntimeDisplayContext:
        """获取实时显示上下文"""
        return self._display_context

    @property
    def is_fullscreen(self) -> bool:
        """当前窗口全屏状态（带缓存的判定结果）"""
        return self._check_fullscreen()

    # ------------------------------ 全屏状态判定（带缓存优化）------------------------------
    def _check_fullscreen(self) -> bool:
        """
        精确判定窗口全屏状态，500ms内复用缓存结果
        
        Returns:
            bool: True=全屏，False=窗口/判定失败
        """
        # 缓存有效性检查
        current_time = time.time()
        cache_valid = (
            self._fullscreen_cache is not None 
            and (current_time - self._fullscreen_cache_time) < self.FULLSCREEN_CACHE_DURATION
        )
        
        if cache_valid:
            self.logger.debug(
                f"全屏判定：使用缓存 | 缓存时长: {(current_time - self._fullscreen_cache_time)*1000:.1f}ms | "
                f"结果: {self._fullscreen_cache}"
            )
            return self._fullscreen_cache

        ctx = self._display_context
        hwnd = ctx.hwnd
        if not hwnd:
            self.logger.warning("全屏判定失败：未设置窗口句柄")
            self._fullscreen_cache = False
            self._fullscreen_cache_time = current_time
            return False

        try:
            # 获取窗口与屏幕基础参数
            win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(hwnd)
            win_width = win_right - win_left
            win_height = win_bottom - win_top
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            
            # 区分最大化与真全屏
            window_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            is_maximized = (window_style & win32con.WS_MAXIMIZE) != 0

            # 尺寸+位置双重校验
            size_match = (
                abs(win_width - screen_width) < self.FULLSCREEN_ERROR_TOLERANCE
                and abs(win_height - screen_height) < self.FULLSCREEN_ERROR_TOLERANCE
            )
            position_match = (
                abs(win_left) < self.FULLSCREEN_ERROR_TOLERANCE
                and abs(win_top) < self.FULLSCREEN_ERROR_TOLERANCE
            )
            fullscreen = size_match and position_match

            self.logger.debug(
                f"全屏判定：执行校验 | 句柄: {hwnd} | 最大化: {is_maximized} | "
                f"窗口尺寸: {win_width}x{win_height} | 屏幕尺寸: {screen_width}x{screen_height} | "
                f"尺寸匹配: {size_match} | 位置匹配: {position_match} | 结果: {fullscreen}"
            )

            # 更新缓存
            self._fullscreen_cache = fullscreen
            self._fullscreen_cache_time = current_time
            return fullscreen
        except Exception as e:
            self.logger.error(f"全屏判定异常: {str(e)}", exc_info=True)
            self._fullscreen_cache = False
            self._fullscreen_cache_time = current_time
            return False

    def refresh_fullscreen_cache(self) -> bool:
        """
        手动刷新全屏状态缓存（立即执行实际判定）
        
        Args:
            无
        Returns:
            bool: 最新全屏判定结果
        """
        self.logger.info("手动刷新全屏状态缓存")
        current_time = time.time()
        ctx = self._display_context
        hwnd = ctx.hwnd
        fullscreen = False

        if not hwnd:
            self.logger.warning("全屏缓存刷新失败：未设置窗口句柄")
        else:
            try:
                win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(hwnd)
                win_width = win_right - win_left
                win_height = win_bottom - win_top
                screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
                screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
                
                window_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                is_maximized = (window_style & win32con.WS_MAXIMIZE) != 0

                size_match = (
                    abs(win_width - screen_width) < self.FULLSCREEN_ERROR_TOLERANCE
                    and abs(win_height - screen_height) < self.FULLSCREEN_ERROR_TOLERANCE
                )
                position_match = (
                    abs(win_left) < self.FULLSCREEN_ERROR_TOLERANCE
                    and abs(win_top) < self.FULLSCREEN_ERROR_TOLERANCE
                )
                fullscreen = size_match and position_match
            except Exception as e:
                self.logger.error(f"全屏缓存刷新异常: {str(e)}", exc_info=True)
                fullscreen = False

        self._fullscreen_cache = fullscreen
        self._fullscreen_cache_time = current_time
        self.logger.debug(f"全屏缓存刷新完成 | 最新结果: {fullscreen}")
        return fullscreen

    # ------------------------------ 点坐标转换（基础转换链路）------------------------------
    def convert_original_to_current_client(self, x: int, y: int) -> Tuple[int, int]:
        """
        原始基准坐标 → 客户区逻辑坐标（按轴对齐缩放，适配窗口大小）
        
        Args:
            x: 原始基准X坐标（基于original_base_res）
            y: 原始基准Y坐标（基于original_base_res）
        Returns:
            Tuple[int, int]: 客户区逻辑坐标（确保在客户区内）
        """
        ctx = self._display_context
        orig_w, orig_h = ctx.original_base_res
        curr_logical_w, curr_logical_h = ctx.client_logical_res

        # 无效参数保护
        if orig_w <= 0 or orig_h <= 0 or curr_logical_w <= 0 or curr_logical_h <= 0:
            self.logger.error(
                f"坐标转换失败：无效分辨率 | 原始: {orig_w}x{orig_h} | 逻辑: {curr_logical_w}x{curr_logical_h}"
            )
            return (x, y)

        # 轴对齐缩放
        scale_x = curr_logical_w / orig_w
        scale_y = curr_logical_h / orig_h
        final_x = int(round(x * scale_x))
        final_y = int(round(y * scale_y))
        # 边界限制
        final_x, final_y = self._ensure_coords_in_boundary(final_x, final_y, curr_logical_w, curr_logical_h)

        self.logger.debug(
            f"坐标转换：原始→逻辑 | 输入: ({x},{y}) → 输出: ({final_x},{final_y}) | "
            f"缩放比: X={scale_x:.2f}, Y={scale_y:.2f}"
        )
        return (final_x, final_y)

    def convert_client_logical_to_physical(self, x: int, y: int) -> Tuple[int, int]:
        """
        客户区逻辑坐标 → 客户区物理坐标（适配DPI缩放）
        
        Args:
            x: 客户区逻辑X坐标
            y: 客户区逻辑Y坐标
        Returns:
            Tuple[int, int]: 客户区物理坐标（确保在物理客户区内）
        """
        ctx = self._display_context
        ratio = ctx.logical_to_physical_ratio
        phys_w, phys_h = ctx.client_physical_res

        # 缩放+边界限制
        phys_x = int(round(x * ratio))
        phys_y = int(round(y * ratio))
        phys_x, phys_y = self._ensure_coords_in_boundary(phys_x, phys_y, phys_w, phys_h)

        self.logger.debug(
            f"坐标转换：逻辑→物理 | 输入: ({x},{y}) → 输出: ({phys_x},{phys_y}) | 转换比: {ratio:.2f}"
        )
        return (phys_x, phys_y)

    def convert_client_physical_to_logical(self, x: int, y: int) -> Tuple[int, int]:
        """
        客户区物理坐标 → 客户区逻辑坐标（逆DPI缩放）
        
        Args:
            x: 客户区物理X坐标
            y: 客户区物理Y坐标
        Returns:
            Tuple[int, int]: 客户区逻辑坐标（确保在逻辑客户区内）
        """
        ctx = self._display_context
        ratio = ctx.logical_to_physical_ratio

        # 无效比例保护
        if ratio <= 0:
            self.logger.error(f"坐标转换失败：无效转换比 {ratio}")
            return (x, y)

        # 逆缩放
        logical_x = int(round(x / ratio))
        logical_y = int(round(y / ratio))
        # 边界限制
        logical_w, logical_h = ctx.client_logical_res
        logical_x, logical_y = self._ensure_coords_in_boundary(logical_x, logical_y, logical_w, logical_h)

        self.logger.debug(
            f"坐标转换：物理→逻辑 | 输入: ({x},{y}) → 输出: ({logical_x},{logical_y}) | 转换比: {ratio:.2f}"
        )
        return (logical_x, logical_y)

    def convert_client_logical_to_screen_physical(self, x: int, y: int) -> Tuple[int, int]:
        """
        客户区逻辑坐标 → 屏幕全局物理坐标（窗口内→全局映射）
        
        Args:
            x: 客户区逻辑X坐标
            y: 客户区逻辑Y坐标
        Returns:
            Tuple[int, int]: 屏幕全局物理坐标（转换失败返回客户区物理坐标）
        """
        ctx = self._display_context
        hwnd = ctx.hwnd
        if not hwnd:
            self.logger.error("坐标转换失败：未设置窗口句柄")
            return (x, y)

        # 逻辑→客户区物理→屏幕全局
        phys_x, phys_y = self.convert_client_logical_to_physical(x, y)
        try:
            screen_x, screen_y = win32gui.ClientToScreen(hwnd, (phys_x, phys_y))
            self.logger.debug(
                f"坐标转换：逻辑→屏幕物理 | 逻辑: ({x},{y}) → 客户区物理: ({phys_x},{phys_y}) → 全局: ({screen_x},{screen_y})"
            )
            return (screen_x, screen_y)
        except Exception as e:
            self.logger.error(f"坐标转换异常：客户区→屏幕映射失败 {str(e)}")
            return (phys_x, phys_y)

    def convert_client_physical_to_screen_physical(self, x: int, y: int) -> Tuple[int, int]:
        """
        客户区物理坐标 → 屏幕全局物理坐标（直接映射）
        
        Args:
            x: 客户区物理X坐标
            y: 客户区物理Y坐标
        Returns:
            Tuple[int, int]: 屏幕全局物理坐标（转换失败返回原坐标）
        """
        ctx = self._display_context
        hwnd = ctx.hwnd
        if not hwnd:
            self.logger.error("坐标转换失败：未设置窗口句柄")
            return (x, y)
        
        try:
            screen_x, screen_y = win32gui.ClientToScreen(hwnd, (x, y))
            self.logger.debug(
                f"坐标转换：物理→屏幕物理 | 输入: ({x},{y}) → 输出: ({screen_x},{screen_y})"
            )
            return (screen_x, screen_y)
        except Exception as e:
            self.logger.error(f"坐标转换异常：客户区→屏幕映射失败 {str(e)}")
            return (x, y)

    # ------------------------------ 矩形坐标转换（含边界修复）------------------------------
    def convert_original_rect_to_current_client(self, rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """
        原始基准矩形 → 客户区逻辑矩形（轴对齐缩放，避免变形）
        
        Args:
            rect: 原始基准矩形 (x, y, w, h)（基于original_base_res）
        Returns:
            Tuple[int, int, int, int]: 客户区逻辑矩形（尺寸≥1，在客户区内）
        """
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            self.logger.error(f"矩形转换失败：无效尺寸 {rect}")
            return rect

        ctx = self._display_context
        orig_w, orig_h = ctx.original_base_res
        curr_logical_w, curr_logical_h = ctx.client_logical_res

        # 无效参数保护
        if orig_w <= 0 or orig_h <= 0 or curr_logical_w <= 0 or curr_logical_h <= 0:
            self.logger.error(
                f"矩形转换失败：无效分辨率 | 原始: {orig_w}x{orig_h} | 逻辑: {curr_logical_w}x{curr_logical_h}"
            )
            return rect

        # 轴对齐缩放（坐标+宽高统一比例）
        scale_x = curr_logical_w / orig_w
        scale_y = curr_logical_h / orig_h
        new_x = int(round(x * scale_x))
        new_y = int(round(y * scale_y))
        new_w = int(round(w * scale_x))
        new_h = int(round(h * scale_y))

        # 边界限制
        new_x = max(0, new_x)
        new_y = max(0, new_y)
        new_w, new_h = self._ensure_positive_size(new_w, new_h)
        new_w = min(new_w, curr_logical_w - new_x)
        new_h = min(new_h, curr_logical_h - new_y)

        self.logger.debug(
            f"矩形转换：原始→逻辑 | 输入: {rect} → 输出: ({new_x},{new_y},{new_w},{new_h}) | "
            f"缩放比: X={scale_x:.2f}, Y={scale_y:.2f}"
        )
        return (new_x, new_y, new_w, new_h)

    def convert_client_physical_rect_to_logical(self, rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """
        客户区物理矩形 → 客户区逻辑矩形（逆DPI缩放）
        
        Args:
            rect: 客户区物理矩形 (x, y, w, h)
        Returns:
            Tuple[int, int, int, int]: 客户区逻辑矩形（尺寸≥1）
        """
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            self.logger.error(f"矩形转换失败：无效尺寸 {rect}")
            return rect

        # 坐标转换
        new_x, new_y = self.convert_client_physical_to_logical(x, y)
        # 宽高转换
        ctx = self._display_context
        ratio = ctx.logical_to_physical_ratio
        new_w = int(round(w / ratio)) if ratio > 0 else w
        new_h = int(round(h / ratio)) if ratio > 0 else h
        # 尺寸有效性保证
        new_w, new_h = self._ensure_positive_size(new_w, new_h)

        self.logger.debug(
            f"矩形转换：物理→逻辑 | 输入: {rect} → 输出: ({new_x},{new_y},{new_w},{new_h}) | 转换比: {ratio:.2f}"
        )
        return (new_x, new_y, new_w, new_h)

    def convert_client_logical_rect_to_screen_physical(
        self,
        rect: Union[Tuple[int, int, int, int], List[int]],
        is_base_coord: bool = False
    ) -> Union[Tuple[int, int, int, int], Tuple[()]]:
        """
        客户区逻辑矩形（或基准矩形）→ 屏幕全局物理矩形
        
        Args:
            rect: 输入矩形 (x, y, w, h)
            is_base_coord: 是否为原始基准坐标（默认False）
        Returns:
            Union[Tuple[int, int, int, int], Tuple[()]]: 屏幕全局物理矩形，无效输入返回空元组
        """
        # 格式校验
        is_valid, err_msg = self.validate_roi_format(rect)
        if not is_valid:
            self.logger.error(f"矩形转换失败：{err_msg}")
            return ()

        x, y, w, h = rect

        # 基准→逻辑（如需）
        logical_rect = rect
        if is_base_coord:
            logical_rect = self.convert_original_rect_to_current_client(rect)
            self.logger.debug(f"矩形转换前置：基准→逻辑 | 输入: {rect} → 输出: {logical_rect}")

        # 逻辑→物理转换
        ctx = self._display_context
        ratio = ctx.logical_to_physical_ratio
        if ratio <= 0:
            self.logger.error(f"矩形转换失败：无效转换比 {ratio}")
            return ()

        phys_x = int(round(logical_rect[0] * ratio))
        phys_y = int(round(logical_rect[1] * ratio))
        phys_w = int(round(logical_rect[2] * ratio))
        phys_h = int(round(logical_rect[3] * ratio))
        phys_w, phys_h = self._ensure_positive_size(phys_w, phys_h)

        # 物理→屏幕全局
        screen_x, screen_y = self.convert_client_physical_to_screen_physical(phys_x, phys_y)
        screen_rect = (screen_x, screen_y, phys_w, phys_h)

        self.logger.debug(
            f"矩形转换：逻辑→屏幕物理 | 逻辑矩形: {logical_rect} | 转换比: {ratio:.2f} | 屏幕矩形: {screen_rect}"
        )
        return screen_rect

    def convert_client_physical_rect_to_screen_physical(
        self,
        rect: Union[Tuple[int, int, int, int], List[int]]
    ) -> Union[Tuple[int, int, int, int], Tuple[()]]:
        """
        客户区物理矩形 → 屏幕全局物理矩形（坐标映射，宽高不变）
        
        Args:
            rect: 客户区物理矩形 (x, y, w, h)
        Returns:
            Union[Tuple[int, int, int, int], Tuple[()]]: 屏幕全局物理矩形，无效输入返回空元组
        """
        # 格式校验
        is_valid, err_msg = self.validate_roi_format(rect)
        if not is_valid:
            self.logger.error(f"矩形转换失败：{err_msg}")
            return ()
        
        x, y, w, h = rect
        # 坐标转换
        screen_x, screen_y = self.convert_client_physical_to_screen_physical(x, y)
        screen_rect = (screen_x, screen_y, w, h)

        self.logger.debug(
            f"矩形转换：物理→屏幕物理 | 输入: {rect} → 输出: {screen_rect}"
        )
        return screen_rect

    # ------------------------------ ROI专项处理（通用逻辑）------------------------------
    def validate_roi_format(self, roi: Union[Tuple[int, int, int, int], List[int], np.ndarray]) -> Tuple[bool, Optional[str]]:
        """
        通用ROI格式校验
        
        Args:
            roi: 待校验ROI (x, y, w, h)
        Returns:
            Tuple[bool, Optional[str]]: (校验结果, 错误信息/None)
        """
        roi = self._convert_numpy_to_tuple(roi)
        
        # 格式长度校验
        if not isinstance(roi, (tuple, list)) or len(roi) != 4:
            return False, f"格式错误（需4元组/列表）→ 类型: {type(roi)}, 内容: {roi}"
        
        # 数值有效性校验
        x, y, w, h = roi
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            return False, f"参数错误（x/y≥0，w/h>0）→ {roi}"
        
        return True, None

    def process_roi(
        self,
        roi: Union[Tuple[int, int, int, int], List[int], np.ndarray],
        boundary_width: int,
        boundary_height: int,
        enable_expand: bool = False,
        expand_pixel: Optional[int] = None
    ) -> Tuple[Optional[Tuple[int, int, int, int]], Tuple[int, int]]:
        """
        通用ROI全流程处理（格式校验→模式适配→边界限制→安全扩展）
        
        Args:
            roi: 输入ROI (x, y, w, h)（基于原始基准分辨率）
            boundary_width: ROI边界宽度（物理像素）
            boundary_height: ROI边界高度（物理像素）
            enable_expand: 是否启用安全扩展（OCR专用）
            expand_pixel: 扩展像素数（默认使用DEFAULT_ROI_EXPAND_PIXEL）
        Returns:
            Tuple[Optional[Tuple[int, int, int, int]], Tuple[int, int]]: 
                (处理后的物理ROI/None, ROI在边界内的物理偏移量)
        """
        # 格式校验
        is_valid, err_msg = self.validate_roi_format(roi)
        if not is_valid:
            self.logger.warning(f"ROI处理失败：{err_msg}")
            return None, (0, 0)
        
        x, y, w, h = roi
        is_fullscreen = self.is_fullscreen
        ctx = self._display_context
        roi_offset_phys = (0, 0)

        try:
            # 全屏/窗口模式适配
            if is_fullscreen:
                # 全屏：基准ROI=屏幕物理ROI
                rx_phys, ry_phys, rw_phys, rh_phys = x, y, w, h
                self.logger.debug(f"ROI处理：全屏模式 → 物理ROI: {rx_phys},{ry_phys},{rw_phys},{rh_phys}")
            else:
                # 窗口：基准→逻辑→物理
                rx_log, ry_log, rw_log, rh_log = self.convert_original_rect_to_current_client(roi)
                # 逻辑ROI边界限制
                client_w_log, client_h_log = ctx.client_logical_res
                rx_log = max(0, rx_log)
                ry_log = max(0, ry_log)
                rw_log = min(rw_log, client_w_log - rx_log)
                rh_log = min(rh_log, client_h_log - ry_log)
                # 逻辑→物理
                rx_phys, ry_phys = self.convert_client_logical_to_physical(rx_log, ry_log)
                ratio = ctx.logical_to_physical_ratio
                rw_phys = int(round(rw_log * ratio))
                rh_phys = int(round(rh_log * ratio))
                self.logger.debug(
                    f"ROI处理：窗口模式 → 基准ROI: {roi} → 逻辑ROI: ({rx_log},{ry_log},{rw_log},{rh_log}) → "
                    f"物理ROI: ({rx_phys},{ry_phys},{rw_phys},{rh_phys})"
                )

            # 物理ROI边界限制
            rx_phys = max(0, rx_phys)
            ry_phys = max(0, ry_phys)
            rw_phys = min(rw_phys, boundary_width - rx_phys)
            rh_phys = min(rh_phys, boundary_height - ry_phys)
            
            if rw_phys <= 0 or rh_phys <= 0:
                raise ValueError(f"物理ROI尺寸无效 → ({rx_phys},{ry_phys},{rw_phys},{rh_phys})")

            # 安全扩展
            if enable_expand:
                expand_pixel = expand_pixel or self.DEFAULT_ROI_EXPAND_PIXEL
                new_rx = max(0, rx_phys - expand_pixel)
                new_ry = max(0, ry_phys - expand_pixel)
                new_rw = min(boundary_width - new_rx, rw_phys + 2 * expand_pixel)
                new_rh = min(boundary_height - new_ry, rh_phys + 2 * expand_pixel)
                
                # 极端情况回退
                if new_rw <= 0 or new_rh <= 0:
                    new_rx, new_ry, new_rw, new_rh = rx_phys, ry_phys, rw_phys, rh_phys
                    self.logger.debug(f"ROI扩展失败，回退原始物理ROI: {new_rx},{new_ry},{new_rw},{new_rh}")
                else:
                    self.logger.debug(
                        f"ROI扩展：原始: ({rx_phys},{ry_phys},{rw_phys},{rh_phys}) → "
                        f"扩展后: ({new_rx},{new_ry},{new_rw},{new_rh}) | 扩展像素: {expand_pixel}"
                    )
                
                processed_roi_phys = (new_rx, new_ry, new_rw, new_rh)
                roi_offset_phys = (new_rx, new_ry)
            else:
                processed_roi_phys = (rx_phys, ry_phys, rw_phys, rh_phys)
                roi_offset_phys = (rx_phys, ry_phys)

            return processed_roi_phys, roi_offset_phys

        except Exception as e:
            self.logger.error(f"ROI处理异常：{str(e)}，切换为全图处理", exc_info=True)
            return None, (0, 0)

    # ------------------------------ 通用矩形工具 ------------------------------
    def get_rect_center(self, rect: Union[Tuple[int, int, int, int], List[int], np.ndarray]) -> Tuple[int, int]:
        """
        计算矩形中心坐标（支持多格式输入）
        
        Args:
            rect: 输入矩形 (x, y, w, h)
        Returns:
            Tuple[int, int]: 矩形中心坐标，无效输入返回(0, 0)
        """
        rect = self._convert_numpy_to_tuple(rect)
        # 格式校验
        is_valid, err_msg = self.validate_roi_format(rect)
        if not is_valid:
            self.logger.warning(f"矩形中心计算失败：{err_msg}")
            return (0, 0)
        
        try:
            x, y, w, h = map(int, rect)
            center_x = x + w // 2
            center_y = y + h // 2
            self.logger.debug(f"矩形中心计算：输入: {rect} → 中心: ({center_x},{center_y})")
            return (center_x, center_y)
        except (ValueError, TypeError) as e:
            self.logger.warning(f"矩形中心计算失败：{str(e)} → 输入: {rect}")
            return (0, 0)

    def limit_rect_to_boundary(
        self,
        rect: Tuple[int, int, int, int],
        boundary_width: int,
        boundary_height: int
    ) -> Tuple[int, int, int, int]:
        """
        限制矩形在指定边界内
        
        Args:
            rect: 输入矩形 (x, y, w, h)
            boundary_width: 边界宽度
            boundary_height: 边界高度
        Returns:
            Tuple[int, int, int, int]: 限制后的矩形
        """
        return self._ensure_rect_in_boundary(rect, boundary_width, boundary_height)

    def get_unified_logical_rect(
        self,
        phys_rect: Union[Tuple[int, int, int, int], List[int]]
    ) -> Union[Tuple[int, int, int, int], Tuple[()]]:
        """
        统一将物理矩形转为逻辑矩形（自动适配全屏/窗口模式）
        
        Args:
            phys_rect: 输入物理矩形 (x, y, w, h)
        Returns:
            Union[Tuple[int, int, int, int], Tuple[()]]: 统一逻辑矩形，无效输入返回空元组
        """
        # 格式校验
        is_valid, err_msg = self.validate_roi_format(phys_rect)
        if not is_valid:
            self.logger.error(f"逻辑矩形转换失败：{err_msg}")
            return ()
        
        if not self.is_fullscreen:
            # 窗口：物理→逻辑
            return self.convert_client_physical_rect_to_logical(phys_rect)
        else:
            # 全屏：物理=逻辑，仅限制边界
            screen_w, screen_h = self._display_context.screen_physical_res
            limited_rect = self._ensure_rect_in_boundary(phys_rect, screen_w, screen_h)
            self.logger.debug(
                f"逻辑矩形转换：全屏模式 → 物理矩形: {phys_rect} → 限制后: {limited_rect}"
            )
            return limited_rect

    # ------------------------------ 专用工具（OCR/图像匹配）------------------------------
    def apply_roi_offset_to_subcoord(
        self,
        sub_coord: Union[Tuple[int, int], Tuple[int, int, int, int], List[int], np.ndarray],
        roi_offset_phys: Tuple[int, int]
    ) -> Union[Tuple[int, int], Tuple[int, int, int, int]]:
        """
        子图内坐标 → 原图物理坐标（应用ROI偏移量）
        
        Args:
            sub_coord: 子图内坐标（(x,y) 或 (x,y,w,h)）
            roi_offset_phys: ROI在原图的物理偏移量 (offset_x, offset_y)
        Returns:
            Union[Tuple[int, int], Tuple[int, int, int, int]]: 原图物理坐标，无效输入返回原坐标
        """
        sub_coord = self._convert_numpy_to_tuple(sub_coord)
        
        # 格式校验
        if not sub_coord or len(sub_coord) not in (2, 4):
            self.logger.error(f"子图坐标修正失败：无效输入 {sub_coord}")
            return sub_coord
        
        offset_x, offset_y = roi_offset_phys
        if len(sub_coord) == 2:
            # 单个坐标
            result = (sub_coord[0] + offset_x, sub_coord[1] + offset_y)
        else:
            # 矩形坐标
            result = (sub_coord[0] + offset_x, sub_coord[1] + offset_y, sub_coord[2], sub_coord[3])
        
        self.logger.debug(
            f"子图坐标→原图 | 子图: {sub_coord} | 偏移: {roi_offset_phys} → 原图: {result}"
        )
        return result

    def calculate_template_scale_ratio(
        self,
        target_phys_size: Tuple[int, int],
        has_roi: bool = False,
        roi_logical_size: Optional[Tuple[int, int]] = None
    ) -> float:
        """
        计算模板图像缩放比例（避免拉伸变形）
        
        Args:
            target_phys_size: 目标物理尺寸 (w, h)
            has_roi: 是否基于ROI逻辑尺寸计算
            roi_logical_size: ROI逻辑尺寸 (w, h)（has_roi=True时必需）
        Returns:
            float: 模板缩放比例（≥0.001），无效输入返回1.0
        """
        target_w, target_h = target_phys_size
        if target_w <= 0 or target_h <= 0:
            self.logger.error(f"模板缩放比计算失败：无效目标尺寸 {target_phys_size}")
            return 1.0
        
        ctx = self._display_context
        orig_base_w, orig_base_h = ctx.original_base_res
        
        # ROI参数校验
        if has_roi and roi_logical_size:
            roi_log_w, roi_log_h = roi_logical_size
            if roi_log_w <= 0 or roi_log_h <= 0:
                self.logger.warning(f"无效ROI逻辑尺寸 {roi_logical_size}，fallback到基准分辨率")
                has_roi = False
        
        # 计算缩放比
        if has_roi and roi_logical_size:
            scale_ratio_w = target_w / roi_log_w
            scale_ratio_h = target_h / roi_log_h
            self.logger.debug(
                f"模板缩放比：基于ROI | 目标: {target_phys_size} | ROI逻辑: {roi_logical_size} | "
                f"宽比: {scale_ratio_w:.4f} | 高比: {scale_ratio_h:.4f}"
            )
        else:
            scale_ratio_w = target_w / orig_base_w
            scale_ratio_h = target_h / orig_base_h
            self.logger.debug(
                f"模板缩放比：基于基准 | 目标: {target_phys_size} | 基准: {orig_base_w}x{orig_base_h} | "
                f"宽比: {scale_ratio_w:.4f} | 高比: {scale_ratio_h:.4f}"
            )
        
        # 取最小值避免拉伸，保证比例≥0.001
        scale_ratio = max(0.001, min(scale_ratio_w, scale_ratio_h))
        self.logger.debug(f"模板缩放比计算完成：{scale_ratio:.4f}")
        return scale_ratio

    def calculate_scaled_template_size(self, template_size: Tuple[int, int], min_size: Tuple[int, int], crop_size: Tuple[int, int]) -> Tuple[int, int]:
        """
        计算模板缩放后的尺寸（确保≥最小尺寸，≤裁剪尺寸）
        
        Args:
            template_size: 模板原始尺寸 (w, h)
            min_size: 最小尺寸限制 (w, h)
            crop_size: 裁剪子图尺寸 (w, h)
        Returns:
            Tuple[int, int]: 缩放后的模板尺寸
        """
        template_w, template_h = template_size
        min_w, min_h = min_size
        crop_w, crop_h = crop_size
        
        # 计算缩放比
        scale_ratio = self.calculate_template_scale_ratio(
            target_phys_size=self.display_context.effective_physical_res,
            has_roi=False
        )
        
        # 缩放+边界限制
        scaled_w = int(round(template_w * scale_ratio))
        scaled_h = int(round(template_h * scale_ratio))
        scaled_w, scaled_h = self._ensure_positive_size(scaled_w, scaled_h)
        scaled_w = max(scaled_w, min_w)
        scaled_h = max(scaled_h, min_h)
        scaled_w = min(scaled_w, crop_w - 2)
        scaled_h = min(scaled_h, crop_h - 2)
        
        return scaled_w, scaled_h