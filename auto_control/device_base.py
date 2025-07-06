from abc import ABC, abstractmethod
import time
import win32gui
import win32con

class BaseDevice(ABC):
    def __init__(self, device_uri):
        self.device_uri = device_uri
        self.connected = False
        self.resolution = (0, 0)
        self.minimized = False
        
    @abstractmethod
    def connect(self):
        """连接设备"""
        pass
        
    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass
        
    @abstractmethod
    def capture_screen(self):
        """捕获屏幕截图"""
        pass
        
    @abstractmethod
    def click(self, x, y, duration=0.1):
        """点击指定位置"""
        pass
        
    @abstractmethod
    def key_press(self, key, duration=0.1):
        """按键操作"""
        pass
        
    @abstractmethod
    def text_input(self, text, interval=0.05):
        """文本输入"""
        pass
        
    def set_foreground(self):
        """将窗口置前（默认实现）"""
        return True
        
    def get_resolution(self):
        """获取设备分辨率"""
        return self.resolution
        
    def is_minimized(self):
        """检查是否最小化"""
        return self.minimized