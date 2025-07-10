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

    @abstractmethod
    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> bool:
        """
        滑动操作 (跨平台)
        :param start_x: 起始X坐标
        :param start_y: 起始Y坐标
        :param end_x: 结束X坐标
        :param end_y: 结束Y坐标
        :param duration: 滑动持续时间(秒)
        :return: 是否滑动成功
        """
        pass

    @abstractmethod
    def wait(self, template, timeout: float = 10.0) -> bool:
        """
        等待元素出现 (跨平台)
        :param template: 要等待的模板
        :param timeout: 超时时间(秒)
        :return: 是否等待成功
        """
        pass

    @abstractmethod
    def exists(self, template) -> bool:
        """
        检查元素是否存在 (跨平台)
        :param template: 要检查的模板
        :return: 元素是否存在
        """
        pass

    def paste_text(self, text: str) -> bool:
        """
        粘贴文本 (跨平台实现)
        :param text: 要粘贴的文本
        :return: 是否粘贴成功
        """
        try:
            from airtest.core.api import paste
            paste(text)
            return True
        except Exception as e:
            print(f"粘贴文本失败: {str(e)}")
            return False

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
