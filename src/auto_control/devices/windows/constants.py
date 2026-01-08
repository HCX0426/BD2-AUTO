from enum import Enum, auto


class CoordType(Enum):
    """
    坐标类型枚举，定义Windows设备支持的坐标体系。

    枚举值说明：
    - LOGICAL: 逻辑坐标（适配DPI缩放后的客户区坐标）
    - PHYSICAL: 物理坐标（屏幕像素坐标，未缩放）
    - BASE: 基准坐标（原始设计分辨率坐标，需转换为当前窗口坐标）
    """

    LOGICAL = auto()
    PHYSICAL = auto()
    BASE = auto()