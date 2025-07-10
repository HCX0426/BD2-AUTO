import time
from typing import Optional

import airtest
import cv2
import numpy as np
import pydirectinput
import win32con
import win32gui
from airtest.core.api import connect_device, paste, swipe, touch,Template,wait,exists
from airtest.core.win.win import Windows

from .device_base import BaseDevice, DeviceState


class WindowsDevice(BaseDevice):
    def __init__(self, device_uri: str):
        super().__init__(device_uri)
        self.window_handle = None
        self._last_window_state = None

    def connect(self, timeout: float = 10.0) -> bool:
        try:
            connect_device(self.device_uri)
            self.connected = True
            self.state = DeviceState.CONNECTED
            self.window_handle = win32gui.FindWindow(
                None, self._get_window_title())
            self._update_window_info()
            return True
        except Exception as e:
            self.state = DeviceState.ERROR
            self.last_error = str(e)
            print(f"连接Windows设备失败: {str(e)}")
            return False

    def _get_window_title(self):
        """从URI中提取窗口标题"""
        parts = self.device_uri.split('title_re=')
        if len(parts) > 1:
            return parts[1]
        return ""

    def _update_window_info(self):
        """更新窗口信息"""
        if self.window_handle:
            left, top, right, bottom = win32gui.GetWindowRect(
                self.window_handle)
            self.resolution = (right - left, bottom - top)
            self.minimized = win32gui.IsIconic(self.window_handle)

    def set_foreground(self):
        """激活并置前窗口"""
        if not self.window_handle:
            return False

        if self._last_window_state != 'normal':
            if self.minimized:
                win32gui.ShowWindow(self.window_handle, win32con.SW_RESTORE)
                time.sleep(0.5)
            self._last_window_state = 'normal'

        try:
            win32gui.SetForegroundWindow(self.window_handle)
            self._update_window_info()
            return True
        except Exception as e:
            print(f"窗口置前失败: {str(e)}")
            return False

    def text_input(self, text: str, interval: float = 0.05) -> bool:
        """文本输入"""
        if not self.set_foreground() or self.minimized:
            return False

        try:
            # 优先使用Windows原生输入
            if hasattr(self, 'win_handle') and self.win_handle:
                self.win.text(text)
                return True
            # 回退到跨平台paste
            paste(text)
            return True
        except Exception as e:
            print(f"文本输入失败: {str(e)}")
            return False

    def capture_screen(self) -> Optional[np.ndarray]:
        try:
            from ctypes import windll

            import win32ui
            from PIL import Image

            hwnd = self.window_handle
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top

            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
            saveDC.SelectObject(saveBitMap)

            result = windll.user32.PrintWindow(
                hwnd, saveDC.GetSafeHdc(), 0x00000002)

            if result == 1:
                bmpinfo = saveBitMap.GetInfo()
                bmpstr = saveBitMap.GetBitmapBits(True)
                im = Image.frombuffer(
                    'RGB',
                    (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                    bmpstr, 'raw', 'BGRX', 0, 1)
                img = np.array(im)
                return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            return None

        except Exception as e:
            print(f"截图失败: {str(e)}")
            return None

    def click(self, pos_or_template, duration: float = 0.1) -> bool:
        """点击操作，兼容坐标和模板对象
        :param pos_or_template: 可以是(x,y)坐标或Template对象
        :param duration: 点击持续时间
        """
        if not self.set_foreground() or self.minimized:
            return False

        try:
            # 如果是模板对象
            if isinstance(pos_or_template, Template):
                touch(pos_or_template)
            # 如果是坐标元组
            elif isinstance(pos_or_template, (tuple, list)) and len(pos_or_template) == 2:
                touch((pos_or_template[0], pos_or_template[1]))
            else:
                raise ValueError("参数必须是坐标(x,y)或Template对象")
            return True
        except Exception as e:
            print(f"点击操作失败: {str(e)}")
            return False

    def key_press(self, key, duration=0.1):
        """按键操作"""
        if not self.set_foreground() or self.minimized:
            print("窗口未置前，无法按键")
            return False

        pydirectinput.keyDown(key)
        time.sleep(duration)
        pydirectinput.keyUp(key)
        return True

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> bool:
        """滑动操作"""
        if not self.set_foreground() or self.minimized:
            return False
        try:
            swipe((start_x, start_y), (end_x, end_y), duration=duration)
            return True
        except Exception as e:
            print(f"滑动操作失败: {str(e)}")
            return False

    def wait(self, template, timeout: float = 10.0) -> bool:
        """等待元素出现"""
        if not self.set_foreground() or self.minimized:
            return False
        try:
            wait(template, timeout=timeout)
            return True
        except Exception as e:
            print(f"等待元素失败: {str(e)}")
            return False

    def exists(self, template) -> bool:
        """检查元素是否存在"""
        if not self.connected:
            return False
        try:
            return exists(template)
        except Exception as e:
            print(f"检查元素存在失败: {str(e)}")

    def disconnect(self) -> bool:
        try:
            self.connected = False
            self.state = DeviceState.DISCONNECTED
            self.window_handle = None
            self.resolution = (0, 0)
            self.minimized = False
            self._last_window_state = None
            return True
        except Exception as e:
            self.state = DeviceState.ERROR
            self.last_error = str(e)
            print(f"断开Windows设备连接失败: {str(e)}")
