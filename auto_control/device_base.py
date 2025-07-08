from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Optional, Tuple


class DeviceState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


class BaseDevice(ABC):
    def __init__(self, device_uri: str):
        self.device_uri = device_uri
        self.connected = False
        self.resolution: Tuple[int, int] = (0, 0)
        self.minimized = False
        self.state = DeviceState.DISCONNECTED
        self.last_error: Optional[str] = None

    @abstractmethod
    def connect(self, timeout: float = 10.0) -> bool:
        """
        连接设备
        :param timeout: 连接超时时间(秒)
        :return: 是否连接成功
        """
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        """
        断开连接并清理资源
        :return: 是否成功断开
        """
        self.connected = False
        self.state = DeviceState.DISCONNECTED
        pass

    @abstractmethod
    def capture_screen(self) -> Optional[bytes]:
        """
        捕获屏幕截图
        :return: 截图二进制数据或None
        """
        pass

    @abstractmethod
    def click(self, x: int, y: int, duration: float = 0.1) -> bool:
        """
        点击指定位置
        :param x: X坐标
        :param y: Y坐标
        :param duration: 点击持续时间(秒)
        :return: 是否点击成功
        """
        pass

    @abstractmethod
    def key_press(self, key: str, duration: float = 0.1) -> bool:
        """
        按键操作
        :param key: 按键名称
        :param duration: 按键持续时间(秒)
        :return: 是否按键成功
        """
        pass

    @abstractmethod
    def text_input(self, text: str, interval: float = 0.05) -> bool:
        """
        文本输入
        :param text: 要输入的文本
        :param interval: 字符输入间隔(秒)
        :return: 是否输入成功
        """
        pass

    def set_foreground(self) -> bool:
        """
        将窗口置前
        :return: 是否置前成功
        """
        return True

    def get_resolution(self) -> Tuple[int, int]:
        """获取设备分辨率"""
        return self.resolution

    def is_minimized(self) -> bool:
        """检查是否最小化"""
        return self.minimized

    def get_state(self) -> DeviceState:
        """获取设备当前状态"""
        return self.state
