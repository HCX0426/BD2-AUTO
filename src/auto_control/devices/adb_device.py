from src.auto_control.devices.base_device import BaseDevice


class ADBDevice(BaseDevice):
    def __init__(self, device_uri: str, logger=None):
        super().__init__(device_uri, logger)

    def connect(self):
        pass

    def capture_screen(self, roi=None):
        """捕获屏幕截图"""
        pass

    def click(self, pos, click_time=1, duration=0.1, right_click=False, coord_type=None, roi=None):
        """点击指定位置"""
        pass

    def key_press(self, key, duration=0.1):
        """按键操作"""
        pass

    def text_input(self, text, interval=0.05):
        """文本输入"""
        pass

    def swipe(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.3, steps=10, coord_type=None
    ) -> bool:
        """滑动操作"""
        pass

    def wait(self, template_name, timeout: float = 10.0, interval: float = 0.5, roi=None):
        """等待元素出现"""
        pass

    def exists(self, template_name, threshold: float = 0.8, roi=None):
        """检查元素是否存在"""
        pass

    def disconnect(self):
        pass
