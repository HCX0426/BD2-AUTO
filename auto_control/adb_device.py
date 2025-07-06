from airtest.core.api import connect_device, device as airtest_device, touch, snapshot, text, keyevent
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