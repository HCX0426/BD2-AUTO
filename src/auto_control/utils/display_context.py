from dataclasses import dataclass, field
from typing import Tuple, Optional


@dataclass
class RuntimeDisplayContext:
    """
    可修改的显示上下文容器：存储运行时显示参数，
    支持动态更新窗口状态（尺寸、DPI等），无转换逻辑。
    """
    # ========================= 原始基准参数（固定不变，初始化后建议不修改）=========================
    original_base_width: int
    original_base_height: int

    # ========================= 运行时动态参数（可随窗口变化更新）=========================
    hwnd: Optional[int] = None
    is_fullscreen: bool = False
    dpi_scale: float = 1.0  # DPI缩放因子（如1.0=100%）

    # 客户区逻辑尺寸（应用感知的尺寸）
    client_logical_width: int = 0
    client_logical_height: int = 0

    # 客户区物理尺寸（屏幕实际像素）
    client_physical_width: int = 0
    client_physical_height: int = 0

    # 屏幕物理分辨率（硬件原生）
    screen_physical_width: int = 0
    screen_physical_height: int = 0

    # 客户区左上角在屏幕上的物理坐标（全局位置）
    client_screen_origin_x: int = 0
    client_screen_origin_y: int = 0

    # ========================= 衍生属性（只读，基于当前参数计算）=========================
    @property
    def original_base_res(self) -> Tuple[int, int]:
        """原始基准分辨率 (宽, 高)"""
        return (self.original_base_width, self.original_base_height)

    @property
    def client_logical_res(self) -> Tuple[int, int]:
        """客户区逻辑分辨率 (宽, 高)"""
        return (self.client_logical_width, self.client_logical_height)

    @property
    def client_physical_res(self) -> Tuple[int, int]:
        """客户区物理分辨率 (宽, 高)"""
        return (self.client_physical_width, self.client_physical_height)

    @property
    def screen_physical_res(self) -> Tuple[int, int]:
        """屏幕物理分辨率 (宽, 高)"""
        return (self.screen_physical_width, self.screen_physical_height)

    @property
    def client_screen_origin(self) -> Tuple[int, int]:
        """客户区左上角屏幕物理坐标 (x, y)"""
        return (self.client_screen_origin_x, self.client_screen_origin_y)

    @property
    def effective_physical_res(self) -> Tuple[int, int]:
        """当前有效物理分辨率（全屏用屏幕，窗口用客户区）"""
        return self.screen_physical_res if self.is_fullscreen else self.client_physical_res

    @property
    def content_scale_ratio(self) -> float:
        """原始基准与当前有效物理分辨率的缩放比（保持宽高比）"""
        orig_w, orig_h = self.original_base_res
        curr_w, curr_h = self.effective_physical_res
        if orig_w <= 0 or orig_h <= 0 or curr_w <= 0 or curr_h <= 0:
            return 1.0  # 避免除零
        return min(curr_w / orig_w, curr_h / orig_h)

    @property
    def logical_to_physical_ratio(self) -> float:
        """逻辑坐标 → 物理坐标的转换比例（逻辑1单位对应多少物理像素）"""
        if self.is_fullscreen:
            return 1.0
        if self.client_logical_width <= 0:
            return 1.0
        return self.client_physical_width / self.client_logical_width

    # ========================= 便捷更新方法 =========================
    def update_from_window(self, 
                          hwnd: Optional[int] = None,
                          is_fullscreen: Optional[bool] = None,
                          dpi_scale: Optional[float] = None,
                          client_logical: Optional[Tuple[int, int]] = None,
                          client_physical: Optional[Tuple[int, int]] = None,
                          screen_physical: Optional[Tuple[int, int]] = None,
                          client_origin: Optional[Tuple[int, int]] = None) -> None:
        """
        批量更新窗口相关参数（仅更新传入的非None值）
        适合窗口尺寸、位置变化时调用
        """
        if hwnd is not None:
            self.hwnd = hwnd
        if is_fullscreen is not None:
            self.is_fullscreen = is_fullscreen
        if dpi_scale is not None:
            self.dpi_scale = dpi_scale
        if client_logical:
            self.client_logical_width, self.client_logical_height = client_logical
        if client_physical:
            self.client_physical_width, self.client_physical_height = client_physical
        if screen_physical:
            self.screen_physical_width, self.screen_physical_height = screen_physical
        if client_origin:
            self.client_screen_origin_x, self.client_screen_origin_y = client_origin

    # ========================= 格式化输出 =========================
    def __str__(self) -> str:
        mode = "全屏" if self.is_fullscreen else "窗口"
        return (
            f"RuntimeDisplayContext[{mode}] "
            f"原始基准: {self.original_base_res} | "
            f"客户区逻辑: {self.client_logical_res} | "
            f"客户区物理: {self.client_physical_res} | "
            f"DPI: {self.dpi_scale:.2f} | "
            f"屏幕: {self.screen_physical_res}"
        )