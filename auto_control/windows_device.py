from typing import Optional, Tuple, Union
import time
import win32con
import win32gui
import numpy as np
from airtest.core.api import Template, connect_device, paste, swipe, touch, wait, exists
import pydirectinput
import cv2
from ctypes import windll
import win32ui
from PIL import Image

from auto_control.device_base import BaseDevice, DeviceState


class WindowsDevice(BaseDevice):
    def __init__(self, device_uri: str):
        super().__init__(device_uri)
        self.window_handle: Optional[int] = None
        self._last_window_state: Optional[str] = None
        self._window_original_rect: Optional[Tuple[int, int, int, int]] = None

    def _update_device_state(self, new_state: DeviceState) -> None:
        """更新设备状态（内部方法）"""
        self.state = new_state
        print(f"设备状态更新: {new_state.name}")

    def _get_window_title(self) -> str:
        """从URI中提取窗口标题"""
        title_re_index = self.device_uri.find('title_re=')
        if title_re_index == -1:
            return ""

        remaining_part = self.device_uri[title_re_index + len('title_re='):]
        next_param_index = remaining_part.find('&')
        return remaining_part[:next_param_index] if next_param_index != -1 else remaining_part

    def _update_window_info(self) -> None:
        """更新窗口信息（复用方法）"""
        if not self.window_handle:
            return

        try:
            left, top, right, bottom = win32gui.GetWindowRect(self.window_handle)
            self.resolution = (right - left, bottom - top)
            self.minimized = win32gui.IsIconic(self.window_handle)
            
            if self._window_original_rect is None:
                self._window_original_rect = (left, top, right, bottom)
        except Exception as e:
            print(f"更新窗口信息失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)

    def connect(self, timeout: float = 15.0) -> bool:
        self._update_device_state(DeviceState.CONNECTING)
        start_time = time.time()
        try:
            connect_device(self.device_uri)
            self.connected = True
            window_title = self._get_window_title()
            
            while time.time() - start_time < timeout:
                self.window_handle = win32gui.FindWindow(None, window_title)
                if self.window_handle:
                    self._update_window_info()
                    self._update_device_state(DeviceState.CONNECTED)
                    return True
                time.sleep(0.1)
            
            raise TimeoutError("查找窗口超时")
        except Exception as e:
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            print(f"连接Windows设备失败: {str(e)}")
            return False

    def disconnect(self) -> bool:
        """断开连接并清理所有资源"""
        try:
            self._update_device_state(DeviceState.DISCONNECTED)
            self.connected = False
            self.window_handle = None
            self.resolution = (0, 0)
            self.minimized = False
            self._last_window_state = None
            self._window_original_rect = None
            return True
        except Exception as e:
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            print(f"断开Windows设备连接失败: {str(e)}")
            return False

    def capture_screen(self) -> Optional[np.ndarray]:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.window_handle:
                return None

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

            result = windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0x00000002)

            if result == 1:
                bmpinfo = saveBitMap.GetInfo()
                bmpstr = saveBitMap.GetBitmapBits(True)
                im = Image.frombuffer(
                    'RGB',
                    (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                    bmpstr, 'raw', 'BGRX', 0, 1)
                img = np.array(im)
                self._update_device_state(DeviceState.IDLE)
                return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            return None
        except Exception as e:
            print(f"截图失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return None
        finally:
            self._update_device_state(DeviceState.IDLE)

    def set_foreground(self) -> bool:
        """激活并置前窗口（优化后的复用方法）"""
        if not self.window_handle:
            return False

        try:
            if self.minimized:
                self.restore_window()
                time.sleep(0.3)

            win32gui.SetForegroundWindow(self.window_handle)
            self._update_window_info()
            return True
        except Exception as e:
            print(f"窗口置前失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def click(self, pos_or_template: Union[Tuple[int, int], Template], duration: float = 0.1) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.set_foreground() or self.minimized:
                return False

            # 增强参数检查和处理
            if isinstance(pos_or_template, Template):
                touch(pos_or_template, duration=duration)
            elif isinstance(pos_or_template, (tuple, list)) and len(pos_or_template) == 2:
                # 确保坐标是整数
                x, y = int(pos_or_template[0]), int(pos_or_template[1])
                touch((x, y), duration=duration)
            else:
                error_msg = (
                    f"无效参数类型: {type(pos_or_template)}. "
                    "参数必须是坐标(x,y)或Template对象。"
                    f"接收到的值: {pos_or_template}"
                )
                print(error_msg)
                raise ValueError(error_msg)
            
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            print(f"点击操作失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def key_press(self, key: str, duration: float = 0.1) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.set_foreground() or self.minimized:
                print("窗口未置前，无法按键")
                return False

            pydirectinput.keyDown(key)
            time.sleep(duration)
            pydirectinput.keyUp(key)
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            print(f"按键操作失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def text_input(self, text: str, interval: float = 0.05) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.set_foreground() or self.minimized:
                return False

            paste(text)
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            print(f"文本输入失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.set_foreground() or self.minimized:
                return False

            swipe((start_x, start_y), (end_x, end_y), duration=duration)
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            print(f"滑动操作失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def wait(self, template, timeout: float = 10.0) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.set_foreground() or self.minimized:
                return False

            wait(template, timeout=timeout)
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            print(f"等待元素失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def exists(self, template) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.connected:
                return False

            result = exists(template)
            self._update_device_state(DeviceState.IDLE)
            return result
        except Exception as e:
            print(f"检查元素存在失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    # 新增窗口管理功能
    def minimize_window(self) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.window_handle:
                return False

            win32gui.ShowWindow(self.window_handle, win32con.SW_MINIMIZE)
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            print(f"最小化窗口失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def maximize_window(self) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.window_handle:
                return False

            win32gui.ShowWindow(self.window_handle, win32con.SW_MAXIMIZE)
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            print(f"最大化窗口失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def restore_window(self) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.window_handle:
                return False

            win32gui.ShowWindow(self.window_handle, win32con.SW_RESTORE)
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            print(f"恢复窗口失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def resize_window(self, width: int, height: int) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.window_handle:
                return False

            left, top, _, _ = win32gui.GetWindowRect(self.window_handle)
            win32gui.SetWindowPos(
                self.window_handle, 
                win32con.HWND_TOP, 
                left, top, width, height,
                win32con.SWP_NOZORDER
            )
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            print(f"调整窗口大小失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def move_window(self, x: int, y: int) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.window_handle:
                return False

            _, _, width, height = self.resolution
            win32gui.SetWindowPos(
                self.window_handle, 
                win32con.HWND_TOP, 
                x, y, width, height,
                win32con.SWP_NOZORDER | win32con.SWP_NOSIZE
            )
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            print(f"移动窗口失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def reset_window(self) -> bool:
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.window_handle or not self._window_original_rect:
                return False

            left, top, right, bottom = self._window_original_rect
            width = right - left
            height = bottom - top
            
            win32gui.SetWindowPos(
                self.window_handle, 
                win32con.HWND_TOP, 
                left, top, width, height,
                win32con.SWP_NOZORDER
            )
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            print(f"重置窗口失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False