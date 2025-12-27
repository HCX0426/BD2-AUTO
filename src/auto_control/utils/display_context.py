from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class RuntimeDisplayContext:
    """
    全局共享的显示状态容器，统一管理运行时窗口/屏幕参数，为坐标转换提供基础数据。
    核心能力：支撑「基准坐标→逻辑坐标→物理坐标」的完整转换流程，适配不同分辨率、DPI、显示模式（全屏/窗口）。
    """

    # ========== 固定基准参数（初始化后不修改） ==========
    original_base_width: int
    """原始基准宽度（坐标转换的基准参照，默认对应1920x1080采集分辨率）"""
    original_base_height: int
    """原始基准高度（与original_base_width构成基准分辨率）"""

    # ========== 运行时动态参数（窗口状态变化时更新） ==========
    hwnd: Optional[int] = None
    """目标窗口句柄（Windows窗口唯一标识，用于验证窗口有效性）"""
    is_fullscreen: bool = False
    """显示模式标识：True=全屏，False=窗口（决定坐标转换规则）"""
    dpi_scale: float = 1.0
    """DPI缩放因子（物理像素/逻辑像素，如1.25=125%缩放，解决高DPI坐标偏移）"""

    # 客户区逻辑尺寸（应用感知的视觉尺寸，与DPI无关）
    client_logical_width: int = 0
    """客户区逻辑宽度（窗口内可交互区域的视觉宽度）"""
    client_logical_height: int = 0
    """客户区逻辑高度（窗口内可交互区域的视觉高度）"""

    # 客户区物理尺寸（屏幕实际渲染像素，逻辑尺寸 × DPI缩放）
    client_physical_width: int = 0
    """客户区物理宽度（窗口内可交互区域的实际像素宽度）"""
    client_physical_height: int = 0
    """客户区物理高度（窗口内可交互区域的实际像素高度）"""

    # 屏幕物理分辨率（硬件原生分辨率，无缩放）
    screen_physical_width: int = 0
    """屏幕物理宽度（显示器原生像素宽度）"""
    screen_physical_height: int = 0
    """屏幕物理高度（显示器原生像素高度）"""

    # 客户区屏幕原点（客户区左上角在全局屏幕的物理坐标）
    client_screen_origin_x: int = 0
    """客户区左上角X轴全局物理坐标"""
    client_screen_origin_y: int = 0
    """客户区左上角Y轴全局物理坐标"""

    # ========== 基础衍生属性（只读，封装字段组合） ==========
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
        """客户区左上角全局屏幕坐标 (x, y)"""
        return (self.client_screen_origin_x, self.client_screen_origin_y)

    # ========== 核心计算属性（坐标转换关键参数） ==========
    @property
    def effective_physical_res(self) -> Tuple[int, int]:
        """当前有效物理分辨率：全屏用屏幕分辨率，窗口用客户区物理分辨率"""
        return self.screen_physical_res if self.is_fullscreen else self.client_physical_res

    @property
    def content_scale_ratio(self) -> float:
        """
        内容缩放比例（保持宽高比）：基准分辨率与当前有效分辨率的适配比例。
        计算规则：取宽/高缩放比的最小值，确保内容完全显示，避免拉伸。
        """
        orig_w, orig_h = self.original_base_res
        curr_w, curr_h = self.effective_physical_res

        # 避免除零异常，返回默认缩放比
        if orig_w <= 0 or orig_h <= 0 or curr_w <= 0 or curr_h <= 0:
            return 1.0

        return min(curr_w / orig_w, curr_h / orig_h)

    @property
    def logical_to_physical_ratio(self) -> float:
        """
        逻辑→物理坐标转换比例：1个逻辑单位对应的物理像素数。
        规则：全屏模式=1.0（逻辑=物理），窗口模式=物理宽度/逻辑宽度。
        """
        if self.is_fullscreen:
            return 1.0
        if self.client_logical_width <= 0:
            return 1.0  # 避免除零异常
        return self.client_physical_width / self.client_logical_width

    # ========== 坐标转换工具方法 ==========
    def logical_to_physical(self, x: int, y: int) -> Tuple[int, int]:
        """
        将客户区逻辑坐标转换为物理坐标（自动适配全屏/窗口模式）。

        Args:
            x: 客户区逻辑X坐标
            y: 客户区逻辑Y坐标

        Returns:
            对应的客户区物理坐标 (x, y)
        """
        ratio = self.logical_to_physical_ratio
        return (int(round(x * ratio)), int(round(y * ratio)))

    # ========== 状态更新方法 ==========
    def update_from_window(
        self,
        hwnd: Optional[int] = None,
        is_fullscreen: Optional[bool] = None,
        dpi_scale: Optional[float] = None,
        client_logical: Optional[Tuple[int, int]] = None,
        client_physical: Optional[Tuple[int, int]] = None,
        screen_physical: Optional[Tuple[int, int]] = None,
        client_origin: Optional[Tuple[int, int]] = None,
    ) -> None:
        """
        批量更新窗口相关动态参数（仅更新传入的非None值）。
        调用时机：窗口尺寸/位置/显示模式/DPI变化时。

        Args:
            hwnd: 窗口句柄
            is_fullscreen: 显示模式标识
            dpi_scale: DPI缩放因子
            client_logical: 客户区逻辑分辨率 (宽, 高)
            client_physical: 客户区物理分辨率 (宽, 高)
            screen_physical: 屏幕物理分辨率 (宽, 高)
            client_origin: 客户区左上角全局坐标 (x, y)
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

    # ========== 格式化输出（调试/日志用） ==========
    def __str__(self) -> str:
        """简洁格式化输出，便于日志打印"""
        mode = "全屏" if self.is_fullscreen else "窗口"
        return (
            f"RuntimeDisplayContext[{mode}] | "
            f"基准分辨率: {self.original_base_res} | "
            f"逻辑尺寸: {self.client_logical_res} | "
            f"物理尺寸: {self.client_physical_res} | "
            f"DPI缩放: {self.dpi_scale:.2f} | "
            f"屏幕分辨率: {self.screen_physical_res} | "
            f"坐标转换比: {self.logical_to_physical_ratio:.2f}"
        )

    def __repr__(self) -> str:
        """详细结构化输出，便于调试"""
        return (
            f"RuntimeDisplayContext(\n"
            f"  original_base_width={self.original_base_width}, original_base_height={self.original_base_height},\n"
            f"  hwnd={self.hwnd}, is_fullscreen={self.is_fullscreen}, dpi_scale={self.dpi_scale:.2f},\n"
            f"  client_logical_width={self.client_logical_width}, client_logical_height={self.client_logical_height},\n"
            f"  client_physical_width={self.client_physical_width}, client_physical_height={self.client_physical_height},\n"
            f"  screen_physical_width={self.screen_physical_width}, screen_physical_height={self.screen_physical_height},\n"
            f"  client_screen_origin_x={self.client_screen_origin_x}, client_screen_origin_y={self.client_screen_origin_y}\n"
            f")"
        )
