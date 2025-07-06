from airtest.core.api import connect_device, device as airtest_device, touch, snapshot
from .device_base import BaseDevice
import pydirectinput
import win32gui
import win32con
import time

class WindowsDevice(BaseDevice):
    def connect(self):
        try:
            connect_device(self.device_uri)
            self.connected = True
            self.window_handle = win32gui.FindWindow(None, self._get_window_title())
            self._update_window_info()
            return True
        except Exception as e:
            print(f"连接Windows设备失败: {str(e)}")
            return False
            
    def _get_window_title(self):
        """从URI中提取窗口标题"""
        # 假设URI格式: Windows:///?title_re=窗口标题
        parts = self.device_uri.split('title_re=')
        return parts[1] if len(parts) > 1 else ""
        
    def _update_window_info(self):
        """更新窗口信息"""
        if self.window_handle:
            left, top, right, bottom = win32gui.GetWindowRect(self.window_handle)
            self.resolution = (right - left, bottom - top)
            self.minimized = win32gui.IsIconic(self.window_handle)
            
    def set_foreground(self):
        """激活并置前窗口"""
        if not self.window_handle:
            return False
            
        # 如果窗口最小化则恢复
        if self.minimized:
            win32gui.ShowWindow(self.window_handle, win32con.SW_RESTORE)
            time.sleep(0.5)
            
        try:
            win32gui.SetForegroundWindow(self.window_handle)
            self._update_window_info()
            return True
        except:
            return False
            
    def capture_screen(self):
        """捕获屏幕截图"""
        if not self.connected:
            return None
        return snapshot()
        
    def click(self, x, y, duration=0.1):
        """点击指定位置"""
        if not self.set_foreground() or self.minimized:
            return False
            
        touch((x, y))
        return True
        
    def key_press(self, key, duration=0.1):
        """按键操作"""
        if not self.set_foreground() or self.minimized:
            return False
            
        pydirectinput.keyDown(key)
        time.sleep(duration)
        pydirectinput.keyUp(key)
        return True
        
    def text_input(self, text, interval=0.05):
        """文本输入"""
        if not self.set_foreground() or self.minimized:
            return False
            
        for char in text:
            self.key_press(char, duration=interval)
        return True