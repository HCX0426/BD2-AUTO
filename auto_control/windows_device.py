import time
from typing import Optional

import airtest
import cv2
import numpy as np
import pydirectinput
import win32con
import win32gui
from airtest.core.api import connect_device
from airtest.core.api import device as airtest_device
from airtest.core.api import snapshot, touch

from .device_base import BaseDevice, DeviceState


class WindowsDevice(BaseDevice):
    def __init__(self, device_uri: str):
        super().__init__(device_uri)
        self.window_handle = None
        self._last_window_state = None

    def connect(self, timeout: float = 10.0) -> bool:
        try:
            device = connect_device(self.device_uri)
            if device:
                self.connected = True
                self.device = device
            else:
                self.connected = False
                raise Exception("连接Windows设备失败")
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
            return False

    def _get_window_title(self):
        """从URI中提取窗口标题"""
        # 假设URI格式: Windows:///?title_re=窗口标题
        parts = self.device_uri.split('title_re=')
        if len(parts) > 1:
            return parts[1]
        return ""  # 若未找到，返回空字符串

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

        # 使用缓存状态避免不必要的API调用
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

    def text_input(self, text, interval=0.05):
        """文本输入"""
        if not self.set_foreground() or self.minimized:
            return False

        # 使用pydirectinput直接输入完整文本
        try:
            pydirectinput.write(text, interval=interval)
            return True
        except Exception as e:
            print(f"文本输入失败: {str(e)}")
            return False

    def capture_screen(self) -> Optional[np.ndarray]:
        if not self.connected or not self.window_handle:
            return None

        try:
            from ctypes import windll

            import pywintypes
            import win32ui
            from PIL import Image

            # 获取窗口位置和大小
            left, top, right, bottom = win32gui.GetWindowRect(
                self.window_handle)
            width = right - left
            height = bottom - top

            # 创建设备上下文
            hwndDC = win32gui.GetWindowDC(self.window_handle)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()

            # 创建位图对象
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
            saveDC.SelectObject(saveBitMap)

            # 使用PrintWindow API截图(即使窗口被遮挡也能截图)
            PW_CLIENTONLY = 0x00000001  # 只截图客户区
            windll.user32.PrintWindow(
                self.window_handle, saveDC.GetSafeHdc(), PW_CLIENTONLY)

            # 转换为PIL图像
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            im = Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1)

            # 转换为numpy数组
            img = np.array(im)

            # 释放资源
            win32gui.DeleteObject(saveBitMap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(self.window_handle, hwndDC)

            return img

        except Exception as e:
            print(f"截图失败: {str(e)}")
            return None

    def click(self, x: int, y: int, duration: float = 0.1) -> bool:
        if not self.set_foreground() or self.minimized:
            return False
        touch((x, y))
        return True

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
            from airtest.core.api import swipe
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
            from airtest.core.api import wait
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
            from airtest.core.api import exists
            return exists(template) is not None
        except Exception as e:
            print(f"检查元素存在失败: {str(e)}")
