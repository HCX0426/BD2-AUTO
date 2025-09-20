from .base_device import BaseDevice

class ADBDevice(BaseDevice):
    def connect(self):
        pass

    def capture_screen(self):
        """捕获屏幕截图"""
        pass

    def click(self, x, y, duration=0.1):
        """点击指定位置"""
        pass

    def key_press(self, key, duration=0.1):
        """按键操作"""
        pass

    def text_input(self, text_str, interval=0.05):
        """文本输入"""
        pass

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> bool:
        """滑动操作"""
        pass

    def wait(self, template, timeout: float = 10.0) -> bool:
        """等待元素出现"""
        pass

    def exists(self, template) -> bool:
        """检查元素是否存在"""
        pass

    def disconnect(self):
        pass
