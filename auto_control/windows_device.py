import time
from ctypes import windll, c_int
from typing import Optional, Tuple, Union

import cv2
import numpy as np
import pydirectinput
import win32con
import win32api
import win32gui
import win32ui
from airtest.core.api import Template, connect_device, exists, paste
from airtest.core.api import sleep as air_sleep
from airtest.core.api import touch, wait
from airtest.core.helper import log, logwrap
from PIL import Image

from auto_control.device_base import BaseDevice, DeviceState


class WindowsDevice(BaseDevice):
    def __init__(self, device_uri: str):
        super().__init__(device_uri)
        self.window_handle: Optional[int] = None
        self._last_window_state: Optional[str] = None
        self._window_original_rect: Optional[Tuple[int, int, int, int]] = None
        # 新增：客户区尺寸（游戏实际渲染区域）
        self._client_size: Tuple[int, int] = (0, 0)
        # 新增：启用DPI感知（解决高DPI缩放问题）
        self._enable_dpi_awareness()

    def _enable_dpi_awareness(self) -> None:
        """启用DPI感知，确保获取物理屏幕坐标"""
        try:
            # Windows 10+ 推荐模式（Per-Monitor DPI感知V2）
            windll.user32.SetProcessDpiAwarenessContext(c_int(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        except Exception as e:
            # 兼容旧系统（系统级DPI感知）
            windll.user32.SetProcessDPIAware()
            print(f"启用DPI感知兼容模式: {e}")

    def _update_device_state(self, new_state: DeviceState) -> None:
        """更新设备状态"""
        self.state = new_state

    def _get_window_title(self) -> str:
        """从URI中提取窗口标题"""
        title_re_index = self.device_uri.find('title_re=')
        if title_re_index == -1:
            return ""
        remaining_part = self.device_uri[title_re_index + len('title_re='):]
        next_param_index = remaining_part.find('&')
        return remaining_part[:next_param_index] if next_param_index != -1 else remaining_part

    def _get_client_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """获取窗口客户区（游戏渲染区域）的坐标和尺寸"""
        if not self.window_handle:
            return None
        try:
            # 客户区坐标是相对于窗口左上角的（left=0, top=0）
            client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(self.window_handle)
            return (client_left, client_top, client_right, client_bottom)
        except Exception as e:
            print(f"获取客户区失败: {str(e)}")
            return None

    def _update_window_info(self) -> None:
        """更新窗口信息（新增客户区尺寸更新）"""
        if not self.window_handle:
            return

        try:
            # 窗口整体区域（含边框/标题栏）
            win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(self.window_handle)
            self.resolution = (win_right - win_left, win_bottom - win_top)
            self.minimized = win32gui.IsIconic(self.window_handle)

            # 客户区区域（游戏实际内容区域）
            client_rect = self._get_client_rect()
            if client_rect:
                _, _, client_right, client_bottom = client_rect
                self._client_size = (client_right, client_bottom)  # 客户区宽高

            if self._window_original_rect is None:
                self._window_original_rect = (win_left, win_top, win_right, win_bottom)
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
                    # 检查客户区是否有效（避免窗口未加载完成）
                    if self._client_size != (0, 0):
                        self._update_device_state(DeviceState.CONNECTED)
                        return True
                self.sleep(0.1)

            raise TimeoutError("查找窗口超时或客户区无效")
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
            self._client_size = (0, 0)  # 清理客户区尺寸
            self.minimized = False
            self._last_window_state = None
            self._window_original_rect = None
            return True
        except Exception as e:
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            print(f"断开Windows设备连接失败: {str(e)}")
            return False

    def convert_to_client_coords(self, x: int, y: int) -> Tuple[int, int]:
        """
        将1920*1080基准坐标转换为窗口客户区坐标
        （客户区是游戏实际渲染区域，避免边框/标题栏影响）
        """
        base_width, base_height = 1920, 1080
        client_width, client_height = self._client_size

        # 防止客户区未初始化导致除零
        if client_width == 0 or client_height == 0:
            self._update_window_info()
            client_width, client_height = self._client_size
            if client_width == 0 or client_height == 0:
                raise ValueError("客户区尺寸无效，无法转换坐标")

        # 按客户区尺寸缩放基准坐标
        client_x = int(x * (client_width / base_width))
        client_y = int(y * (client_height / base_height))
        return client_x, client_y

    def client_to_screen(self, client_x: int, client_y: int, y_offset: int = -38) -> Tuple[int, int]:
        """
        支持全屏检测和Y轴偏移校准的坐标转换
        
        :param client_x: 客户区X坐标
        :param client_y: 客户区Y坐标
        :param y_offset: Y轴手动校准偏移量（px），默认-38（根据你的偏差设置）
        """
        if not self.window_handle:
            raise ValueError("窗口句柄无效")

        try:
            # 1. 获取窗口坐标和客户区尺寸
            win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(self.window_handle)
            client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(self.window_handle)
            client_width = client_right - client_left
            client_height = client_bottom - client_top

            # 2. 检测是否全屏（窗口尺寸 ≈ 屏幕分辨率）
            screen_width = win32api.GetSystemMetrics(0)  # 屏幕宽度
            screen_height = win32api.GetSystemMetrics(1)  # 屏幕高度
            is_fullscreen = (
                abs(win_right - win_left - screen_width) < 5 and
                abs(win_bottom - win_top - screen_height) < 5
            )

            # 3. 计算基准点（区分全屏/窗口模式）
            if is_fullscreen:
                # 全屏模式：无标题栏/边框，客户区即屏幕
                base_x = win_left
                base_y = win_top
                print("检测到全屏模式，使用窗口左上角作为基准点")
            else:
                # 窗口模式：计算边框和标题栏
                border_width = (win_right - win_left - client_width) // 2
                title_bar_height = (win_bottom - win_top - client_height) - border_width  # 原算法
                base_x = win_left + border_width
                base_y = win_top + title_bar_height
                print(f"窗口模式：边框={border_width}px，标题栏={title_bar_height}px")

            # 4. 应用Y轴手动校准偏移（核心修正）
            final_y = base_y + client_y + y_offset

            # 5. 计算最终屏幕坐标
            screen_x = base_x + client_x
            screen_y = final_y

            # 调试日志
            print(f"窗口坐标: ({win_left}, {win_top}, {win_right}, {win_bottom})")
            print(f"客户区尺寸: {client_width}x{client_height}，屏幕尺寸: {screen_width}x{screen_height}")
            print(f"基准点: ({base_x}, {base_y})，应用偏移{y_offset}px后 → 实际Y={final_y}")
            print(f"转换后屏幕坐标: ({screen_x}, {screen_y})")
            return (screen_x, screen_y)

        except Exception as e:
            raise RuntimeError(f"坐标转换失败: {str(e)}")



    def capture_screen(self) -> Optional[np.ndarray]:
        self._update_device_state(DeviceState.BUSY)
        # 初始化DC对象为None，便于后续判断是否创建成功
        hwndDC = None
        mfcDC = None
        saveDC = None
        saveBitMap = None
        try:
            if not self.window_handle:
                log("截图失败：窗口句柄无效")
                return None

            # 获取客户区（游戏渲染区域）
            client_rect = self._get_client_rect()
            if not client_rect:
                log("截图失败：客户区无效")
                return None
            _, _, client_width, client_height = client_rect

            # 1. 创建父DC（绑定窗口设备）
            hwndDC = win32gui.GetWindowDC(self.window_handle)
            if not hwndDC:
                raise RuntimeError("获取窗口DC失败")

            # 2. 创建兼容DC（父DC：mfcDC）
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            if not mfcDC:
                raise RuntimeError("创建MFC DC失败")

            # 3. 创建子DC（用于保存截图，依赖mfcDC）
            saveDC = mfcDC.CreateCompatibleDC()
            if not saveDC:
                raise RuntimeError("创建保存DC失败")

            # 4. 创建位图对象
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, client_width, client_height)
            saveDC.SelectObject(saveBitMap)

            # 5. 执行截图（PrintWindow）
            result = windll.user32.PrintWindow(self.window_handle, saveDC.GetSafeHdc(), 0x00000002)
            if result != 1:
                raise RuntimeError(f"PrintWindow截图失败，返回值: {result}")

            # 6. 转换位图为numpy数组
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            im = Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1
            )
            img = np.array(im)
            self._update_device_state(DeviceState.IDLE)
            return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        except Exception as e:
            error_msg = f"截图失败: {str(e)}"
            print(error_msg)
            log(error_msg, level="ERROR")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = error_msg
            return None

        finally:
            # 关键：按「先子后父、先创建后释放」的顺序释放资源
            # 1. 释放位图对象
            if saveBitMap:
                try:
                    win32gui.DeleteObject(saveBitMap.GetHandle())  # 释放位图句柄
                except Exception as e:
                    log(f"释放位图失败: {str(e)}", level="WARNING")
            
            # 2. 释放子DC（saveDC）
            if saveDC:
                try:
                    saveDC.DeleteDC()
                except Exception as e:
                    log(f"释放saveDC失败: {str(e)}", level="ERROR")
            
            # 3. 释放父DC（mfcDC）
            if mfcDC:
                try:
                    mfcDC.DeleteDC()
                except Exception as e:
                    log(f"释放mfcDC失败: {str(e)}", level="ERROR")
            
            # 4. 释放窗口DC（hwndDC）
            if hwndDC and self.window_handle:
                try:
                    win32gui.ReleaseDC(self.window_handle, hwndDC)
                except Exception as e:
                    log(f"释放hwndDC失败: {str(e)}", level="ERROR")
            
            self._update_device_state(DeviceState.IDLE)

    def set_foreground(self) -> bool:
        """激活并置前窗口"""
        if not self.window_handle:
            return False

        try:
            if self.minimized:
                self.restore_window()
                self.sleep(0.3)

            # 兼容Windows 10+的窗口置前（避免权限问题）
            win32gui.ShowWindow(self.window_handle, win32con.SW_SHOWNA)
            win32gui.SetForegroundWindow(self.window_handle)
            self._update_window_info()
            return True
        except Exception as e:
            print(f"窗口置前失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    def click(self, pos_or_template: Union[Tuple[int, int], Template], duration: float = 0.1, 
              time: int = 1, right_click: bool = False, is_base_coord: bool = False) -> bool:
        """
        点击操作，支持基准坐标和客户区坐标
        
        :param pos_or_template: 坐标元组 (x, y) 或 Airtest Template对象
        :param is_base_coord: 是否为1920x1080基准坐标，默认False（客户区坐标）
        """
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.set_foreground() or self.minimized:
                return False

            # 处理Airtest模板（默认视为客户区坐标，无需转换）
            if isinstance(pos_or_template, Template):
                pos = touch(pos_or_template, duration=duration, time=time, right_click=right_click)
            else:
                # 处理坐标元组：根据is_base_coord判断是否转换
                x, y = pos_or_template
                if is_base_coord:
                    # 基准坐标 → 客户区坐标
                    client_x, client_y = self.convert_to_client_coords(x, y)
                else:
                    # 默认为客户区坐标，直接使用
                    client_x, client_y = x, y

                # 客户区坐标 → 屏幕坐标
                print(f"[DEBUG] 点击位置（客户区坐标）: ({client_x}, {client_y})")
                target_screen_x,target_screen_y = self.client_to_screen(client_x, client_y)
                # print(f"[DEBUG] 点击位置（屏幕坐标）: ({screen_x}, {screen_y})")
                # 执行点击
                # pos = touch((screen_x, screen_y), duration=duration, time=time, right_click=right_click)
                if target_screen_x is not None and target_screen_y is not None:
                    # 移动鼠标到目标位置
                    win32api.SetCursorPos((target_screen_x, target_screen_y))
                    # time.sleep(0.05)  # 等待鼠标移动稳定
                    # 执行点击（左键/右键）
                    mouse_event = win32con.MOUSEEVENTF_RIGHTDOWN if right_click else win32con.MOUSEEVENTF_LEFTDOWN
                    win32api.mouse_event(mouse_event, 0, 0, 0, 0)
                    # time.sleep(duration)  # 按住时长
                    mouse_event_up = win32con.MOUSEEVENTF_RIGHTUP if right_click else win32con.MOUSEEVENTF_LEFTUP
                    win32api.mouse_event(mouse_event_up, 0, 0, 0, 0)

                    log(f"Win32点击成功：屏幕坐标({target_screen_x}, {target_screen_y})", snapshot=True)
                    self._update_device_state(DeviceState.IDLE)
                    return True

            if pos is None:
                log("点击失败：未获取到有效坐标")
                return False
            self._update_device_state(DeviceState.IDLE)
            coord_type = "基准坐标" if (is_base_coord and isinstance(pos_or_template, Tuple)) else "客户区坐标"
            log(f"点击坐标 {pos}（屏幕坐标），源类型：{coord_type}", snapshot=True)
            return True
        except Exception as e:
            print(f"点击操作失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            log(f"点击异常: {e}", desc="点击操作失败")
            return False

    @logwrap
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

    @logwrap
    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 2, 
              steps: int = 10, is_base_coord: bool = False) -> bool:
        """
        滑动操作，支持基准坐标和客户区坐标
        
        :param start_x/start_y: 起始坐标
        :param end_x/end_y: 结束坐标
        :param is_base_coord: 是否为1920x1080基准坐标，默认False（客户区坐标）
        """
        self._update_device_state(DeviceState.BUSY)
        try:
            if not self.set_foreground() or self.minimized:
                return False

            # 根据is_base_coord判断是否转换坐标
            if is_base_coord:
                # 基准坐标 → 客户区坐标
                start_client_x, start_client_y = self.convert_to_client_coords(start_x, start_y)
                end_client_x, end_client_y = self.convert_to_client_coords(end_x, end_y)
            else:
                # 默认为客户区坐标，直接使用
                start_client_x, start_client_y = start_x, start_y
                end_client_x, end_client_y = end_x, end_y

            # 客户区坐标 → 屏幕坐标
            start_screen_x, start_screen_y = self.client_to_screen(start_client_x, start_client_y)
            end_screen_x, end_screen_y = self.client_to_screen(end_client_x, end_client_y)

            # 计算每步移动距离（增加steps数量，使滑动更平滑）
            step_x = (end_screen_x - start_screen_x) / steps
            step_y = (end_screen_y - start_screen_y) / steps
            interval = duration / steps

            # 执行滑动
            pydirectinput.moveTo(start_screen_x, start_screen_y)
            pydirectinput.mouseDown(button='left')
            time.sleep(0.05)

            for i in range(1, steps + 1):
                current_x = int(start_screen_x + step_x * i)
                current_y = int(start_screen_y + step_y * i)
                pydirectinput.moveTo(current_x, current_y)
                time.sleep(interval)

            pydirectinput.mouseUp(button='left')
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

            # 等待模板时，基于客户区截图匹配
            pos = wait(template, timeout=timeout)
            self._update_device_state(DeviceState.IDLE)
            return pos is not None
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

            if not isinstance(template, Template):
                raise ValueError(f"模板参数必须是Template对象,当前类型为:{type(template)}")

            # 元素检查时，使用客户区截图提高匹配精度
            result = exists(template)
            self._update_device_state(DeviceState.IDLE)
            return result
        except Exception as e:
            print(f"检查元素存在失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return False

    # 窗口管理功能
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

            win_left, win_top, _, _ = win32gui.GetWindowRect(self.window_handle)
            # 调整窗口大小时，确保客户区尺寸同步更新
            win32gui.SetWindowPos(
                self.window_handle,
                win32con.HWND_TOP,
                win_left, win_top, width, height,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
            )
            self._update_window_info()  # 强制更新客户区尺寸
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

            win_width, win_height = self.resolution
            win32gui.SetWindowPos(
                self.window_handle,
                win32con.HWND_TOP,
                x, y, win_width, win_height,
                win32con.SWP_NOZORDER | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
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

            win_left, win_top, win_right, win_bottom = self._window_original_rect
            win_width = win_right - win_left
            win_height = win_bottom - win_top

            win32gui.SetWindowPos(
                self.window_handle,
                win32con.HWND_TOP,
                win_left, win_top, win_width, win_height,
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

    def sleep(self, secs: float) -> bool:
        """设备睡眠"""
        try:
            air_sleep(secs)
            return True
        except Exception as e:
            print(f"设备睡眠失败: {str(e)}")
            return False

    def get_window_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """获取窗口位置和大小（含边框）"""
        try:
            if not self.window_handle:
                return None
            win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(self.window_handle)
            return (win_left, win_top, win_right - win_left, win_bottom - win_top)
        except Exception as e:
            print(f"获取窗口矩形失败: {str(e)}")
            self._update_device_state(DeviceState.ERROR)
            self.last_error = str(e)
            return None

    def get_client_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """新增：获取客户区位置和大小（游戏渲染区域）"""
        return self._get_client_rect()