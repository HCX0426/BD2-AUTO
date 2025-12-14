from typing import Tuple, Optional
import win32gui

from src.auto_control.utils.display_context import RuntimeDisplayContext


class CoordinateTransformer:
    """坐标转换工具类：基于 RuntimeDisplayContext 完成各类坐标转换"""

    def __init__(self, display_context: "RuntimeDisplayContext", logger):
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

    @property
    def display_context(self) -> "RuntimeDisplayContext":
        """获取当前显示上下文（便于外部查看或验证）"""
        return self._display_context

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
        if not ctx.hwnd:
            self.logger.error("窗口句柄未设置，无法转换为屏幕坐标")
            return (x, y)

        # 先转换为客户区物理坐标，再转换为屏幕坐标
        phys_x, phys_y = self.convert_client_logical_to_physical(x, y)
        try:
            screen_x, screen_y = win32gui.ClientToScreen(ctx.hwnd, (phys_x, phys_y))
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