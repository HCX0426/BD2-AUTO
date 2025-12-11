# display_context.py

from dataclasses import dataclass
from typing import Tuple, NamedTuple


class Resolution(NamedTuple):
    width: int
    height: int

    def __str__(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass(frozen=True)
class RuntimeDisplayContext:
    """
    统一管理运行时显示上下文，集中处理：
    - 分辨率（原始 vs 当前）
    - DPI 缩放
    - 逻辑坐标 vs 物理像素
    - 全屏/窗口模式差异

    所有尺寸单位明确标注，避免混淆。
    """

    # === 录制基准（不变）===
    original_base_res: Resolution

    # === 运行时动态信息 ===
    hwnd: int
    is_fullscreen: bool
    dpi_scale: float  # e.g., 1.0 (100%), 1.25 (125%)

    # 客户区逻辑尺寸（Windows 虚拟化后的“应用看到的”尺寸）
    client_logical_width: int
    client_logical_height: int

    # 客户区物理尺寸（显示器上实际占用的像素数）
    client_physical_width: int
    client_physical_height: int

    # 全屏时使用的屏幕物理分辨率
    screen_physical_width: int
    screen_physical_height: int

    # === 衍生属性（只读）===

    @property
    def client_logical_res(self) -> Resolution:
        return Resolution(self.client_logical_width, self.client_logical_height)

    @property
    def client_physical_res(self) -> Resolution:
        return Resolution(self.client_physical_width, self.client_physical_height)

    @property
    def screen_physical_res(self) -> Resolution:
        return Resolution(self.screen_physical_width, self.screen_physical_height)

    @property
    def effective_physical_res(self) -> Resolution:
        """当前用于内容渲染的有效物理分辨率"""
        if self.is_fullscreen:
            return self.screen_physical_res
        else:
            return self.client_physical_res

    @property
    def content_scale_ratio(self) -> float:
        """
        基于原始录制分辨率的**内容缩放比例**（仅考虑分辨率，不含 DPI）。
        用于模板按比例缩放以适应不同屏幕大小。
        """
        orig_w, orig_h = self.original_base_res.width, self.original_base_res.height
        curr_w, curr_h = self.effective_physical_res.width, self.effective_physical_res.height
        # 使用 min 保持宽高比，避免拉伸
        return min(curr_w / orig_w, curr_h / orig_h)

    @property
    def template_total_scale(self) -> float:
        """
        模板匹配应使用的**总缩放因子**。
        - 全屏：仅 content_scale_ratio
        - 窗口：content_scale_ratio * dpi_scale（因 UI 元素在高 DPI 下实际变大）
        """
        scale = self.content_scale_ratio
        if not self.is_fullscreen:
            scale *= self.dpi_scale
        return scale

    @property
    def logical_to_physical_ratio(self) -> float:
        """
        逻辑坐标 → 物理坐标的转换比例。
        - 全屏：1.0（通常无 DPI 虚拟化）
        - 窗口：1.0 / dpi_scale（因逻辑尺寸 = 物理尺寸 * dpi_scale）
        """
        return 1.0 if self.is_fullscreen else (1.0 / self.dpi_scale)

    def logical_to_physical(self, x: float, y: float) -> Tuple[int, int]:
        """将客户区逻辑坐标转换为物理像素坐标（用于裁剪截图或点击）"""
        ratio = self.logical_to_physical_ratio
        return (
            int(round(x * ratio)),
            int(round(y * ratio))
        )

    def __repr__(self) -> str:
        mode = "Fullscreen" if self.is_fullscreen else "Windowed"
        return (
            f"<RuntimeDisplayContext {mode} | "
            f"Original={self.original_base_res} | "
            f"ClientLogical={self.client_logical_res} | "
            f"ClientPhysical={self.client_physical_res} | "
            f"DPI Scale={self.dpi_scale:.2f}>"
        )