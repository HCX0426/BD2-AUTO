from typing import Tuple
import win32gui
import win32con
import win32api


from src.auto_control.utils.display_context import RuntimeDisplayContext


class CoordinateTransformer:
    """坐标转换工具类：基于 RuntimeDisplayContext 完成各类坐标转换"""

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
        # 全屏判定误差容忍度（保持原有值，如需兼容更多场景可改为10）
        self.FULLSCREEN_ERROR_TOLERANCE = 5

    @property
    def display_context(self) -> "RuntimeDisplayContext":
        """获取当前显示上下文（便于外部查看或验证）"""
        return self._display_context

    @property
    def is_fullscreen(self) -> bool:
        """
        判断当前窗口是否为全屏状态（属性方式，兼容外部调用）
        外部调用：self.coord_transformer.is_fullscreen
        """
        return self._check_fullscreen()

    def is_fullscreen_method(self) -> bool:
        """
        判断当前窗口是否为全屏状态（方法方式，兼容外部调用）
        外部调用：self.coord_transformer.is_fullscreen_method()
        """
        return self._check_fullscreen()

    def _check_fullscreen(self) -> bool:
        """
        内部实现：检查窗口是否为全屏（优化判定逻辑，不依赖最大化状态）
        判定逻辑（精准兼容窗口/游戏全屏）：
        1. 从上下文获取窗口句柄
        2. 窗口尺寸 ≈ 屏幕硬件分辨率（误差<容忍度）
        3. 窗口位置 ≈ 屏幕原点(0,0)（误差<容忍度）
        4. 移除最大化状态强制要求（兼容游戏全屏无WS_MAXIMIZE标记的场景）
        """
        ctx = self._display_context

        # 必要条件校验：从上下文获取窗口句柄
        hwnd = ctx.hwnd
        if not hwnd:
            self.logger.warning("上下文未设置窗口句柄，无法判断全屏状态")
            return False

        try:
            # 1. 获取窗口整体矩形（屏幕坐标，含边框/无边框）
            win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(hwnd)
            win_width = win_right - win_left
            win_height = win_bottom - win_top

            # 2. 获取屏幕硬件分辨率（不受DPI影响，复用原有稳定方法）
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

            # 3. 保留最大化状态日志（不参与判定，便于调试）
            window_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            is_maximized = (window_style & win32con.WS_MAXIMIZE) != 0

            # 4. 核心全屏判定逻辑（尺寸匹配 + 位置匹配）
            # 尺寸匹配：窗口尺寸与屏幕分辨率误差在容忍范围内
            size_match = (
                abs(win_width - screen_width) < self.FULLSCREEN_ERROR_TOLERANCE and
                abs(win_height - screen_height) < self.FULLSCREEN_ERROR_TOLERANCE
            )
            # 位置匹配：窗口左上角接近屏幕原点（避免尺寸巧合导致的误判）
            position_match = (
                abs(win_left) < self.FULLSCREEN_ERROR_TOLERANCE and
                abs(win_top) < self.FULLSCREEN_ERROR_TOLERANCE
            )
            # 最终判定：两个条件同时满足即为全屏
            fullscreen = size_match and position_match

            # 日志输出（补充位置匹配状态，便于调试）
            self.logger.debug(
                f"全屏状态检查 | "
                f"窗口句柄: {hwnd} | "
                f"最大化: {is_maximized} | "
                f"窗口尺寸: {win_width}x{win_height} | "
                f"屏幕硬件分辨率: {screen_width}x{screen_height} | "
                f"窗口位置: ({win_left},{win_top}) | "
                f"尺寸匹配: {size_match} | 位置匹配: {position_match} | "
                f"误差容忍度: {self.FULLSCREEN_ERROR_TOLERANCE} | "
                f"全屏判定: {fullscreen}"
            )

            return fullscreen

        except Exception as e:
            self.logger.error(f"检查全屏状态失败: {str(e)}", exc_info=True)
            return False

    def convert_original_to_current_client(self, x: int, y: int) -> Tuple[int, int]:
        """
        将原始基准坐标（物理像素）转换为当前客户区逻辑坐标
        
        :param x: 原始基准X坐标（基于 original_base_res）
        :param y: 原始基准Y坐标（基于 original_base_res）
        :return: 当前客户区逻辑坐标 (x, y)
        """
        ctx = self._display_context

        # 校验必要参数
        orig_w, orig_h = ctx.original_base_res
        curr_logical_w, curr_logical_h = ctx.client_logical_res
        if orig_w <= 0 or orig_h <= 0 or curr_logical_w <= 0 or curr_logical_h <= 0:
            self.logger.error(f"无效分辨率，无法转换坐标 | 原始: {orig_w}x{orig_h}, 当前逻辑: {curr_logical_w}x{curr_logical_h}")
            return (x, y)

        # 计算缩放比例（原始物理 → 当前逻辑）
        scale_x = curr_logical_w / orig_w
        scale_y = curr_logical_h / orig_h

        # 转换并限制在客户区内
        final_x = int(round(x * scale_x))
        final_y = int(round(y * scale_y))
        final_x = max(0, min(final_x, curr_logical_w - 1))
        final_y = max(0, min(final_y, curr_logical_h - 1))

        self.logger.debug(
            f"原始→客户区逻辑 | 原始: ({x},{y}) → 客户区逻辑: ({final_x},{final_y}) "
            f"[缩放比 x:{scale_x:.2f}, y:{scale_y:.2f}]"
        )
        return (final_x, final_y)

    def convert_original_rect_to_current_client(self, rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """
        将原始基准矩形转换为当前客户区逻辑矩形
        
        :param rect: 原始矩形 (x, y, w, h)（基于 original_base_res）
        :return: 当前客户区逻辑矩形 (x, y, w, h)
        """
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            self.logger.error(f"无效矩形尺寸: {rect}")
            return rect

        # 转换左上角坐标
        new_x, new_y = self.convert_original_to_current_client(x, y)

        # 基于上下文的内容缩放比转换宽高（保持宽高比）
        scale = self._display_context.content_scale_ratio
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))

        # 确保尺寸有效
        new_w = max(1, new_w)
        new_h = max(1, new_h)

        self.logger.debug(
            f"原始→客户区矩形 | 原始: {rect} → 客户区逻辑: ({new_x},{new_y},{new_w},{new_h}) [缩放比: {scale:.2f}]"
        )
        return (new_x, new_y, new_w, new_h)

    def convert_client_logical_to_physical(self, x: int, y: int) -> Tuple[int, int]:
        """
        将客户区逻辑坐标转换为物理像素坐标
        
        :param x: 客户区逻辑X坐标
        :param y: 客户区逻辑Y坐标
        :return: 客户区物理坐标 (x, y)
        """
        ctx = self._display_context
        ratio = ctx.logical_to_physical_ratio

        phys_x = int(round(x * ratio))
        phys_y = int(round(y * ratio))

        # 限制在客户区物理范围内
        phys_w, phys_h = ctx.client_physical_res
        phys_x = max(0, min(phys_x, phys_w - 1))
        phys_y = max(0, min(phys_y, phys_h - 1))

        self.logger.debug(
            f"客户区逻辑→物理 | 逻辑: ({x},{y}) → 物理: ({phys_x},{phys_y}) [比例: {ratio:.2f}]"
        )
        return (phys_x, phys_y)

    def convert_client_logical_to_screen_physical(self, x: int, y: int) -> Tuple[int, int]:
        """
        将客户区逻辑坐标转换为屏幕全局物理坐标（用于鼠标点击等操作）
        
        :param x: 客户区逻辑X坐标
        :param y: 客户区逻辑Y坐标
        :return: 屏幕全局物理坐标 (x, y)
        """
        ctx = self._display_context
        hwnd = ctx.hwnd
        if not hwnd:
            self.logger.error("上下文未设置窗口句柄，无法转换为屏幕坐标")
            return (x, y)

        # 先转换为客户区物理坐标，再转换为屏幕坐标
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

    def convert_client_physical_to_original(self, x: int, y: int) -> Tuple[int, int]:
        """
        将客户区物理坐标反向转换为原始基准坐标
        
        :param x: 客户区物理X坐标
        :param y: 客户区物理Y坐标
        :return: 原始基准坐标 (x, y)
        """
        ctx = self._display_context
        orig_w, orig_h = ctx.original_base_res
        curr_phys_w, curr_phys_h = ctx.client_physical_res

        if orig_w <= 0 or orig_h <= 0 or curr_phys_w <= 0 or curr_phys_h <= 0:
            self.logger.error(f"无效分辨率，无法反向转换 | 原始: {orig_w}x{orig_h}, 当前物理: {curr_phys_w}x{curr_phys_h}")
            return (x, y)

        scale_x = orig_w / curr_phys_w
        scale_y = orig_h / curr_phys_h

        orig_x = int(round(x * scale_x))
        orig_y = int(round(y * scale_y))

        self.logger.debug(
            f"客户区物理→原始 | 物理: ({x},{y}) → 原始: ({orig_x},{orig_y}) [缩放比 x:{scale_x:.2f}, y:{scale_y:.2f}]"
        )
        return (orig_x, orig_y)

    def convert_client_physical_to_logical(self, x: int, y: int) -> Tuple[int, int]:
        """
        新增：将客户区物理坐标（截图像素坐标）转换为客户区逻辑坐标
        用于模板匹配结果的坐标转换（截图是客户区物理尺寸，需转逻辑坐标）
        """
        ctx = self._display_context
        ratio = ctx.logical_to_physical_ratio  # 逻辑→物理的比例，反向则除以该比例

        if ratio <= 0:
            self.logger.error(f"无效的逻辑-物理比例: {ratio}，无法转换坐标")
            return (x, y)

        logical_x = int(round(x / ratio))
        logical_y = int(round(y / ratio))

        # 限制在客户区逻辑范围内
        logical_w, logical_h = ctx.client_logical_res
        logical_x = max(0, min(logical_x, logical_w - 1))
        logical_y = max(0, min(logical_y, logical_h - 1))

        self.logger.debug(
            f"客户区物理→逻辑 | 物理: ({x},{y}) → 逻辑: ({logical_x},{logical_y}) [比例: {ratio:.2f}]"
        )
        return (logical_x, logical_y)

    def convert_client_physical_rect_to_logical(self, rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """
        新增：将客户区物理矩形（截图匹配结果）转换为客户区逻辑矩形
        """
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            self.logger.error(f"无效矩形尺寸: {rect}")
            return rect

        # 转换左上角坐标
        new_x, new_y = self.convert_client_physical_to_logical(x, y)

        # 转换宽高（同比例缩放）
        ctx = self._display_context
        ratio = ctx.logical_to_physical_ratio
        new_w = int(round(w / ratio)) if ratio > 0 else w
        new_h = int(round(h / ratio)) if ratio > 0 else h

        # 确保尺寸有效
        new_w = max(1, new_w)
        new_h = max(1, new_h)

        self.logger.debug(
            f"客户区物理矩形→逻辑 | 物理: {rect} → 逻辑: ({new_x},{new_y},{new_w},{new_h}) [比例: {ratio:.2f}]"
        )
        return (new_x, new_y, new_w, new_h)