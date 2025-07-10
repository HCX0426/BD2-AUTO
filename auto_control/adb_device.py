from airtest.core.api import connect_device
from airtest.core.api import device as airtest_device
from airtest.core.api import (exists, keyevent, snapshot, swipe, text, touch,
                              wait)

from .device_base import BaseDevice


class ADBDevice(BaseDevice):
    def connect(self):
        try:
            connect_device(self.device_uri)
            self.connected = True
            self.resolution = airtest_device().get_current_resolution()
            return True
        except Exception as e:
            print(f"连接ADB设备失败: {str(e)}")
            return False

    def capture_screen(self):
        """捕获屏幕截图"""
        if not self.connected:
            return None
        return snapshot()

    def click(self, x, y, duration=0.1):
        """点击指定位置"""
        if not self.connected:
            return False

        touch((x, y), duration=duration)
        return True

    def key_press(self, key, duration=0.1):
        """按键操作"""
        if not self.connected:
            return False

        keyevent(key)
        return True

    def text_input(self, text_str, interval=0.05):
        """文本输入"""
        if not self.connected:
            return False

        text(text_str)
        return True

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> bool:
        """滑动操作"""
        if not self.connected:
            return False
        swipe((start_x, start_y), (end_x, end_y), duration=duration)
        return True

    def wait(self, template, timeout: float = 10.0) -> bool:
        """等待元素出现"""
        if not self.connected:
            return False
        try:
            wait(template, timeout=timeout)
            return True
        except:
            return False

    def exists(self, template) -> bool:
        """检查元素是否存在"""
        if not self.connected:
            return False
        return exists(template) is not None

    def paste_text(self, text: str) -> bool:
        """粘贴文本"""
        if not self.connected:
            return False
        from airtest.core.api import paste
        paste(text)
        return True

    def disconnect(self):
        return super().disconnect()
