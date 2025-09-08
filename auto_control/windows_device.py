import ctypes
import time
from ctypes import c_int, windll
from typing import Optional, Tuple, Union

import cv2
import numpy as np
import pydirectinput
import win32api
import win32con
import win32gui
import win32ui
from airtest.core.api import Template, connect_device, exists, paste
from airtest.core.api import sleep as air_sleep
from airtest.core.api import wait, touch
from airtest.core.helper import log, logwrap
from PIL import Image

from auto_control.device_base import BaseDevice, DeviceState


class WindowsDevice(BaseDevice):
    def __init__(self, device_uri: str):
        super().__init__(device_uri)
        self.window_handle: Optional[int] = None
        self._last_window_state: Optional[str] = None
        self._window_original_rect: Optional[Tuple[int, int, int, int]] = None
        
        # 屏幕DPI信息
        self._screen_dpi: Tuple[int, int] = (96, 96)  # 默认DPI值
        self._scaling_percentage: str = "100%"  # DPI缩放百分比
        self._dpi_scale_factor: float = 1.0  # DPI缩放因子
        
        # 客户区尺寸（游戏实际渲染区域）
        self._client_size: Tuple[int, int] = (0, 0)
        # 启用DPI感知（解决高DPI缩放问题）
        self._enable_dpi_awareness()

    def _enable_dpi_awareness(self) -> None:
        """启用DPI感知，确保获取物理屏幕坐标"""
        try:
            # Windows 10+ 推荐模式（Per-Monitor DPI感知V2）
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            windll.user32.SetProcessDpiAwarenessContext(c_int(-4))
        except Exception as e:
            # 兼容旧系统（系统级DPI感知）
            windll.user32.SetProcessDPIAware()
            print(f"启用DPI感知兼容模式: {e}")

    def _get_screen_dpi_info(self) -> None:
        """获取屏幕DPI信息"""
        try:
            # 使用ctypes直接调用Windows API获取DPI
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            
            # 获取桌面窗口的DC
            hdc = user32.GetDC(0)
            LOGPIXELSX = 88  # 水平DPI常量
            LOGPIXELSY = 90  # 垂直DPI常量
            
            # 获取DPI值
            dpi_x = gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
            dpi_y = gdi32.GetDeviceCaps(hdc, LOGPIXELSY)
            self._screen_dpi = (dpi_x, dpi_y)
            
            # 计算DPI缩放百分比（相对于标准96 DPI）
            scaling_x = round((dpi_x / 96.0) * 100)
            scaling_y = round((dpi_y / 96.0) * 100)
            
            # 通常情况下水平和垂直DPI相同
            if scaling_x == scaling_y:
                self._scaling_percentage = f"{scaling_x}%"
                self._dpi_scale_factor = dpi_x / 96.0
            else:
                self._scaling_percentage = f"{scaling_x}% (水平), {scaling_y}% (垂直)"
                # 使用水平DPI作为主要缩放因子
                self._dpi_scale_factor = dpi_x / 96.0
            
            # 释放DC
            user32.ReleaseDC(0, hdc)
            
        except Exception as e:
            print(f"获取屏幕DPI信息时出错: {e}")
            # 出错时使用默认值
            self._screen_dpi = (96, 96)
            self._scaling_percentage = "100%"
            self._dpi_scale_factor = 1.0

    def get_screen_info(self) -> dict:
        """获取屏幕信息（分辨率和DPI）"""
        # 获取屏幕分辨率
        width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        
        # 获取DPI信息（如果尚未获取）
        if self._screen_dpi == (96, 96):
            self._get_screen_dpi_info()
        
        return {
            "resolution": (width, height),
            "dpi": self._screen_dpi,
            "scaling_percentage": self._scaling_percentage,
            "scale_factor": self._dpi_scale_factor
        }

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
            client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(
                self.window_handle)
            return (client_left, client_top, client_right, client_bottom)
        except Exception as e:
            print(f"获取客户区失败: {str(e)}")
            return None

    def _update_window_info(self) -> None:
        """更新窗口信息"""
        if not self.window_handle:
            return

        try:
            # 窗口整体区域（含边框/标题栏）
            win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(
                self.window_handle)
            self.resolution = (win_right - win_left, win_bottom - win_top)
            self.minimized = win32gui.IsIconic(self.window_handle)

            # 客户区区域（游戏实际内容区域）
            client_rect = self._get_client_rect()
            if client_rect:
                _, _, client_right, client_bottom = client_rect
                self._client_size = (client_right, client_bottom)  # 客户区宽高

            if self._window_original_rect is None:
                self._window_original_rect = (
                    win_left, win_top, win_right, win_bottom)
        except Exception as e:
            error_msg = f"更新窗口信息失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg

    def connect(self, timeout: float = 15.0) -> bool:
        """连接设备：严格遵循 CONNECTING → CONNECTED → IDLE 状态流程"""
        # 先尝试转为CONNECTING状态（非法转换会直接返回False）
        if not self._update_device_state(DeviceState.CONNECTING):
            print(f"无法发起连接：当前状态{self.state}不允许")
            return False

        start_time = time.time()
        try:
            connect_device(self.device_uri)
            window_title = self._get_window_title()

            # 获取屏幕DPI信息（在连接时获取一次）
            self._get_screen_dpi_info()

            # 超时等待窗口句柄和有效客户区
            while time.time() - start_time < timeout:
                self.window_handle = win32gui.FindWindow(None, window_title)
                if self.window_handle:
                    self._update_window_info()
                    # 检查客户区是否有效（避免窗口未加载完成）
                    if self._client_size != (0, 0):
                        # 连接成功：先转为CONNECTED，再转为IDLE
                        self._update_device_state(DeviceState.CONNECTED)
                        self._update_device_state(DeviceState.IDLE)
                        print(
                            f"Windows设备连接成功：{window_title}（客户区尺寸：{self._client_size}）")
                        # 打印屏幕信息
                        screen_info = self.get_screen_info()
                        print(f"屏幕分辨率: {screen_info['resolution']}")
                        print(f"屏幕DPI (水平, 垂直): {screen_info['dpi']}")
                        print(f"DPI缩放百分比: {screen_info['scaling_percentage']}")
                        print(f"DPI缩放因子: {screen_info['scale_factor']}")
                        return True
                self.sleep(0.1)

            raise TimeoutError("查找窗口超时或客户区无效")
        except Exception as e:
            error_msg = f"连接Windows设备失败: {str(e)}"
            print(error_msg)
            # 连接失败：转为DISCONNECTED（而非ERROR，便于重试）
            self._update_device_state(DeviceState.DISCONNECTED)
            self.last_error = error_msg
            return False

    def disconnect(self) -> bool:
        """断开连接：清理资源并转为DISCONNECTED状态"""
        # 只有已连接状态才能断开
        if not self.is_connected:
            print("无需断开：设备未连接")
            return True

        try:
            # 先转为DISCONNECTED状态
            if not self._update_device_state(DeviceState.DISCONNECTED):
                print("断开失败：当前状态不允许")
                return False

            # 清理所有资源
            self.window_handle = None
            self.resolution = (0, 0)
            self._client_size = (0, 0)
            self.minimized = False
            self._last_window_state = None
            self._window_original_rect = None
            self.last_error = None
            print("Windows设备断开连接成功")
            return True
        except Exception as e:
            error_msg = f"断开Windows设备连接失败: {str(e)}"
            print(error_msg)
            self._update_device_state(DeviceState.ERROR)
            self.last_error = error_msg
            return False

    def convert_to_client_coords(self, x: int, y: int) -> Tuple[int, int]:
        """将1920*1080基准坐标转换为窗口客户区坐标，考虑DPI缩放"""
        if not self.is_connected:
            raise RuntimeError("无法转换坐标：设备未连接")

        # 保持基准分辨率为1920×1080
        base_width, base_height = 1920, 1080
        client_width, client_height = self._client_size

        # 防止客户区未初始化导致除零
        if client_width == 0 or client_height == 0:
            self._update_window_info()
            client_width, client_height = self._client_size
            if client_width == 0 or client_height == 0:
                raise ValueError("客户区尺寸无效，无法转换坐标")

        # 按客户区尺寸缩放基准坐标，并考虑125%缩放因子
        # 原来的坐标是在125%缩放下取的，所以需要除以1.25来还原
        original_dpi_scale = 1.25  # 125%缩放
        client_x = int(x * (client_width / base_width) / (self._dpi_scale_factor / original_dpi_scale))
        client_y = int(y * (client_height / base_height) / (self._dpi_scale_factor / original_dpi_scale))
        return client_x, client_y

    def client_to_screen(self, client_x: int, client_y: int) -> Tuple[int, int]:
        if not self.window_handle:
            raise ValueError("窗口句柄无效")
        
        try:
            # 检查是否已经是全屏状态
            if self._is_fullscreen():
                return (client_x, client_y)
                
            # 应用DPI缩放因子
            scaled_client_x = int(client_x * self._dpi_scale_factor)
            scaled_client_y = int(client_y * self._dpi_scale_factor)
            
            # 使用ClientToScreen API获取客户区原点
            client_origin = win32gui.ClientToScreen(self.window_handle, (0, 0))
            
            # 计算屏幕坐标
            screen_x = client_origin[0] + scaled_client_x
            screen_y = client_origin[1] + scaled_client_y
            
            return (screen_x, screen_y)
            
        except Exception as e:
            raise RuntimeError(f"坐标转换失败: {str(e)}")
            
    def _is_fullscreen(self) -> bool:
        """判断窗口是否处于全屏状态"""
        if not self.window_handle:
            return False
            
        # 获取窗口矩形和客户区矩形
        window_rect = win32gui.GetWindowRect(self.window_handle)
        client_rect = win32gui.GetClientRect(self.window_handle)
        
        # 比较窗口和客户区大小
        window_width = window_rect[2] - window_rect[0]
        window_height = window_rect[3] - window_rect[1]
        client_width = client_rect[2] - client_rect[0]
        client_height = client_rect[3] - client_rect[1]
        
        # 如果客户区大小与窗口大小几乎相同，则认为处于全屏状态
        return abs(window_width - client_width) < 5 and abs(window_height - client_height) < 5

    def capture_screen(self) -> Optional[np.ndarray]:
        """捕获屏幕截图：状态流程 IDLE → BUSY → IDLE/ERROR"""
        if not self.is_operable:
            print(f"无法截图：设备状态为 {self.state.name}")
            return None

        # 转为BUSY状态
        if not self._update_device_state(DeviceState.BUSY):
            print("无法截图：当前状态不允许")
            return None

        # 初始化DC对象为None，便于后续释放
        hwndDC = None
        mfcDC = None
        saveDC = None
        saveBitMap = None
        try:
            if not self.window_handle:
                raise RuntimeError("窗口句柄无效")

            # 获取客户区（游戏渲染区域）
            client_rect = self._get_client_rect()
            if not client_rect:
                raise RuntimeError("客户区无效")
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
            saveBitMap.CreateCompatibleBitmap(
                mfcDC, client_width, client_height)
            saveDC.SelectObject(saveBitMap)

            # 5. 执行截图（PrintWindow）
            result = windll.user32.PrintWindow(
                self.window_handle, saveDC.GetSafeHdc(), 0x00000002)
            if result != 1:
                raise RuntimeError(f"PrintWindow截图失败，返回值: {result}")

            # 6. 转换位图为numpy数组（BGR格式，适配OpenCV）
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
            self.last_error = error_msg
            
            # 根据错误严重程度决定是否转为ERROR
            if self._should_change_to_error_state(error_msg):
                self._update_device_state(DeviceState.ERROR)
            else:
                self._update_device_state(DeviceState.IDLE)
                
            return None

        finally:
            # 关键：按「先子后父、先创建后释放」的顺序释放资源
            # 1. 释放位图对象
            if saveBitMap:
                try:
                    win32gui.DeleteObject(saveBitMap.GetHandle())  # 释放位图句柄
                except Exception as e:
                    print(f"释放位图失败: {str(e)}")

            # 2. 释放子DC（saveDC）
            if saveDC:
                try:
                    saveDC.DeleteDC()
                except Exception as e:
                    print(f"释放saveDC失败: {str(e)}")

            # 3. 释放父DC（mfcDC）
            if mfcDC:
                try:
                    mfcDC.DeleteDC()
                except Exception as e:
                    print(f"释放mfcDC失败: {str(e)}")

            # 4. 释放窗口DC（hwndDC）
            if hwndDC and self.window_handle:
                try:
                    win32gui.ReleaseDC(self.window_handle, hwndDC)
                except Exception as e:
                    print(f"释放hwndDC失败: {str(e)}")

    def set_foreground(self) -> bool:
        """激活并置前窗口 - 修复版本"""
        if not self.is_connected or not self.window_handle:
            print("无法置前窗口：设备未连接或句柄无效")
            return False

        try:
            # 强制更新窗口状态
            self._update_window_info()
            
            # 如果窗口最小化，先恢复
            if self.minimized:
                print("检测到窗口最小化，正在恢复...")
                win32gui.ShowWindow(self.window_handle, win32con.SW_RESTORE)
                time.sleep(0.5)  # 等待窗口恢复
                # 再次更新状态
                self._update_window_info()
            
            # 激活窗口
            win32gui.ShowWindow(self.window_handle, win32con.SW_SHOW)
            win32gui.SetForegroundWindow(self.window_handle)
            
            # 检查是否真的激活了
            time.sleep(0.1)
            foreground_window = win32gui.GetForegroundWindow()
            
            if foreground_window == self.window_handle and not self.is_minimized():
                print("窗口激活成功")
                return True
            else:
                print(f"窗口激活失败: 前景窗口={foreground_window}, 最小化={self.minimized}")
                return False
                
        except Exception as e:
            error_msg = f"窗口置前失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            return False

    def _should_change_to_error_state(self, error_msg: str) -> bool:
        """
        判断错误是否严重到需要改变设备状态
        
        Returns:
            bool: True表示需要转为ERROR状态，False表示只记录错误
        """
        serious_errors = [
            "设备未连接",
            "窗口句柄无效",
            "设备不可用",
            "截图失败",
            "PrintWindow截图失败",
            "获取窗口DC失败",
            "连接失败",
            "断开连接失败"
        ]
        
        # 检查错误消息中是否包含严重错误关键词
        for serious_error in serious_errors:
            if serious_error in error_msg:
                return True
                
        return False

    @logwrap
    def click(self,
              pos: Union[Tuple[int, int], Template],
              duration: float = 0.1,
              click_time: int = 1,
              right_click: bool = False,
              is_base_coord: bool = False) -> bool:
        """
        点击操作：仅支持坐标输入（基准坐标/客户区坐标），支持多点击
        状态流程：IDLE → BUSY → IDLE/ERROR
        """
        # 1. 前置校验：设备状态 + 点击次数合法性
        if not self.is_operable:
            print(f"无法点击：设备状态为 {self.state.name}")
            return False

        if click_time < 1:
            print(f"无法点击：点击次数必须≥1（当前：{click_time}）")
            return False

        # 2. 转为BUSY状态
        if not self._update_device_state(DeviceState.BUSY):
            print("无法点击：当前状态不允许")
            return False

        try:
            # 3. 激活窗口（确保窗口在前台）
            if not self.set_foreground() or self.minimized:
                raise RuntimeError("窗口未激活或已最小化")
            
            if isinstance(pos, Template):
                # 模板点击 - 使用更安全的方式
                try:
                    target_screen_x, target_screen_y = touch(
                        pos, time=click_time, duration=duration, right_click=right_click
                    )
                    print(f"模板点击成功: {pos.filename}")
                except Exception as template_error:
                    # 模板点击失败，但不影响设备状态
                    error_msg = f"模板点击失败: {str(template_error)}"
                    print(error_msg)
                    self.last_error = error_msg
                    # 不转为ERROR状态，只是返回失败
                    self._update_device_state(DeviceState.IDLE)
                    return False
            else:
                # 4. 坐标转换：基准坐标 → 客户区坐标 → 屏幕坐标
                x, y = pos
                if is_base_coord:
                    # 基准坐标（1920*1080）→ 客户区坐标
                    client_x, client_y = self.convert_to_client_coords(x, y)
                    print(f"[DEBUG] 基准坐标({x},{y}) → 客户区坐标({client_x},{client_y})")
                else:
                    # 直接使用客户区坐标
                    client_x, client_y = x, y
                    print(f"[DEBUG] 使用客户区坐标: ({client_x},{client_y})")

                # 客户区坐标 → 屏幕坐标
                target_screen_x, target_screen_y = self.client_to_screen(client_x, client_y)
                print(f"[DEBUG] 客户区坐标 → 屏幕坐标: ({target_screen_x},{target_screen_y})")

                # 5. 执行点击（支持多次点击）
                # 先移动鼠标到目标位置
                win32api.SetCursorPos((target_screen_x, target_screen_y))
                time.sleep(0.05)  # 等待鼠标移动稳定

                # 定义点击事件（左键/右键）
                down_event = win32con.MOUSEEVENTF_RIGHTDOWN if right_click else win32con.MOUSEEVENTF_LEFTDOWN
                up_event = win32con.MOUSEEVENTF_RIGHTUP if right_click else win32con.MOUSEEVENTF_LEFTUP

                # 循环执行点击（按click_time次数）
                for i in range(click_time):
                    # 按下鼠标
                    win32api.mouse_event(down_event, 0, 0, 0, 0)
                    # 按住指定时长
                    time.sleep(duration)
                    # 抬起鼠标
                    win32api.mouse_event(up_event, 0, 0, 0, 0)
                    # 多次点击时，相邻两次点击间隔0.1秒
                    if i < click_time - 1:
                        time.sleep(0.1)

            # 6. 点击成功：恢复IDLE状态
            self._update_device_state(DeviceState.IDLE)
            click_type = "右键" if right_click else "左键"
            coord_type = "基准坐标" if is_base_coord else "客户区坐标"
            print(f"点击成功：{click_type} {click_time}次 | 屏幕坐标{target_screen_x, target_screen_y} | 源类型：{coord_type}")
            return True

        except Exception as e:
            error_msg = f"点击操作失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            
            # 根据错误类型决定是否转为ERROR状态
            if self._should_change_to_error_state(error_msg):
                self._update_device_state(DeviceState.ERROR)
            else:
                self._update_device_state(DeviceState.IDLE)
                
            return False

    @logwrap
    def key_press(self, key: str, duration: float = 0.1) -> bool:
        """按键操作：状态流程 IDLE → BUSY → IDLE/ERROR"""
        if not self.is_operable:
            print(f"无法按键：设备状态为 {self.state.name}")
            return False

        if not self._update_device_state(DeviceState.BUSY):
            print("无法按键：当前状态不允许")
            return False

        try:
            if not self.set_foreground() or self.minimized:
                raise RuntimeError("窗口未激活或已最小化")

            # 执行按键按下+抬起
            pydirectinput.keyDown(key)
            time.sleep(duration)
            pydirectinput.keyUp(key)

            self._update_device_state(DeviceState.IDLE)
            print(f"按键成功：{key}（按住{duration}秒）")
            return True
        except Exception as e:
            error_msg = f"按键操作失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            
            if self._should_change_to_error_state(error_msg):
                self._update_device_state(DeviceState.ERROR)
            else:
                self._update_device_state(DeviceState.IDLE)
                
            return False

    def text_input(self, text: str, interval: float = 0.05) -> bool:
        """文本输入：优先使用粘贴，确保效率和兼容性"""
        if not self.is_operable:
            print(f"无法输入文本：设备状态为 {self.state.name}")
            return False

        if not self._update_device_state(DeviceState.BUSY):
            print("无法输入文本：当前状态不允许")
            return False

        try:
            if not self.set_foreground() or self.minimized:
                raise RuntimeError("窗口未激活或已最小化")

            # 使用Airtest的paste方法（兼容大多数场景）
            paste(text)
            time.sleep(interval * len(text))  # 等待输入完成

            self._update_device_state(DeviceState.IDLE)
            print(f"文本输入成功：{text}")
            return True
        except Exception as e:
            error_msg = f"文本输入失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            
            if self._should_change_to_error_state(error_msg):
                self._update_device_state(DeviceState.ERROR)
            else:
                self._update_device_state(DeviceState.IDLE)
                
            return False

    @logwrap
    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 2,
              steps: int = 10, is_base_coord: bool = False) -> bool:
        """滑动操作：支持基准坐标和客户区坐标"""
        if not self.is_operable:
            print(f"无法滑动：设备状态为 {self.state.name}")
            return False

        if not self._update_device_state(DeviceState.BUSY):
            print("无法滑动：当前状态不允许")
            return False

        try:
            if not self.set_foreground() or self.minimized:
                raise RuntimeError("窗口未激活或已最小化")

            # 坐标转换：基准坐标 → 客户区坐标
            if is_base_coord:
                start_client_x, start_client_y = self.convert_to_client_coords(start_x, start_y)
                end_client_x, end_client_y = self.convert_to_client_coords(end_x, end_y)
            else:
                start_client_x, start_client_y = start_x, start_y
                end_client_x, end_client_y = end_x, end_y

            # 客户区坐标 → 屏幕坐标
            start_screen_x, start_screen_y = self.client_to_screen(start_client_x, start_client_y)
            end_screen_x, end_screen_y = self.client_to_screen(end_client_x, end_client_y)

            # 计算每步移动距离（steps越多越平滑）
            step_x = (end_screen_x - start_screen_x) / steps
            step_y = (end_screen_y - start_screen_y) / steps
            step_interval = duration / steps

            # 执行滑动操作
            pydirectinput.moveTo(start_screen_x, start_screen_y)
            pydirectinput.mouseDown(button='left')
            time.sleep(0.05)  # 按下后等待稳定

            for i in range(1, steps + 1):
                current_x = int(start_screen_x + step_x * i)
                current_y = int(start_screen_y + step_y * i)
                pydirectinput.moveTo(current_x, current_y)
                time.sleep(step_interval)

            pydirectinput.mouseUp(button='left')
            self._update_device_state(DeviceState.IDLE)
            print(f"滑动成功：从{start_screen_x, start_screen_y}到{end_screen_x, end_screen_y}（{duration}秒）")
            return True
        except Exception as e:
            error_msg = f"滑动操作失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            
            if self._should_change_to_error_state(error_msg):
                self._update_device_state(DeviceState.ERROR)
            else:
                self._update_device_state(DeviceState.IDLE)
                
            return False

    def wait(self, template, timeout: float = 10.0) -> bool:
        """等待元素出现：状态流程 IDLE → BUSY → IDLE/ERROR"""
        if not self.is_operable:
            print(f"无法等待元素：设备状态为 {self.state.name}")
            return False

        # 只在需要时转为BUSY状态
        was_busy = self.state == DeviceState.BUSY
        if not was_busy and not self._update_device_state(DeviceState.BUSY):
            print("无法等待元素：当前状态不允许")
            return False

        try:
            if not self.set_foreground() or self.minimized:
                raise RuntimeError("窗口未激活或已最小化")

            # 等待模板匹配
            pos = wait(template, timeout=timeout)
            
            # 恢复状态
            if not was_busy:
                self._update_device_state(DeviceState.IDLE)
                
            if pos:
                print(f"等待元素成功：{template.filename}（坐标：{pos}）")
                return True
            else:
                print(f"等待元素超时：{template.filename}（{timeout}秒）")
                return False
                
        except Exception as e:
            error_msg = f"等待元素失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            
            # 不改变设备状态
            if not was_busy:
                self._update_device_state(DeviceState.IDLE)
                
            return False

    def exists(self, template) -> bool:
        """检查元素是否存在：状态流程 IDLE → BUSY → IDLE/ERROR"""
        if not self.is_connected:
            print("无法检查元素：设备未连接")
            return False

        # 只在需要时转为BUSY状态
        was_busy = self.state == DeviceState.BUSY
        if not was_busy and not self._update_device_state(DeviceState.BUSY):
            print("无法检查元素：当前状态不允许")
            return False

        try:
            if not isinstance(template, Template):
                print(f"模板参数必须是Template对象,当前类型为:{type(template)}")
                return False

            # 检查元素存在性
            result = exists(template)
            
            # 只有成功转为BUSY状态才需要转回IDLE
            if not was_busy:
                self._update_device_state(DeviceState.IDLE)
                
            print(f"元素检查结果：{template.filename} → {'存在' if result else '不存在'}")
            return result
            
        except Exception as e:
            error_msg = f"检查元素存在失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            
            # 重要：不改变设备状态，只是记录错误
            if not was_busy:
                self._update_device_state(DeviceState.IDLE)
                
            return False

    # ------------------------------
    # 窗口管理功能（状态流程优化）
    # ------------------------------
    def minimize_window(self) -> bool:
        if not self.is_connected or not self.window_handle:
            return False
        if not self._update_device_state(DeviceState.BUSY):
            return False

        try:
            win32gui.ShowWindow(self.window_handle, win32con.SW_MINIMIZE)
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            error_msg = f"最小化窗口失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            self._update_device_state(DeviceState.IDLE)
            return False

    def maximize_window(self) -> bool:
        if not self.is_connected or not self.window_handle:
            return False
        if not self._update_device_state(DeviceState.BUSY):
            return False

        try:
            win32gui.ShowWindow(self.window_handle, win32con.SW_MAXIMIZE)
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            error_msg = f"最大化窗口失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            self._update_device_state(DeviceState.IDLE)
            return False

    def restore_window(self) -> bool:
        if not self.is_connected or not self.window_handle:
            return False
        if not self._update_device_state(DeviceState.BUSY):
            return False

        try:
            win32gui.ShowWindow(self.window_handle, win32con.SW_RESTORE)
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            return True
        except Exception as e:
            error_msg = f"恢复窗口失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            self._update_device_state(DeviceState.IDLE)
            return False

    def resize_window(self, width: int, height: int) -> bool:
        if not self.is_connected or not self.window_handle:
            return False
        if not self._update_device_state(DeviceState.BUSY):
            return False

        try:
            win_left, win_top, _, _ = win32gui.GetWindowRect(self.window_handle)
            # 调整窗口大小
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
            error_msg = f"调整窗口大小失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            self._update_device_state(DeviceState.IDLE)
            return False

    def move_window(self, x: int, y: int) -> bool:
        if not self.is_connected or not self.window_handle:
            return False
        if not self._update_device_state(DeviceState.BUSY):
            return False

        try:
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
            error_msg = f"移动窗口失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            self._update_device_state(DeviceState.IDLE)
            return False

    def reset_window(self) -> bool:
        if not self.is_connected or not self.window_handle or not self._window_original_rect:
            return False
        if not self._update_device_state(DeviceState.BUSY):
            return False

        try:
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
            error_msg = f"重置窗口失败: {str(e)}"
            print(error_msg)
            self.last_error = error_msg
            self._update_device_state(DeviceState.IDLE)
            return False

    # ------------------------------
    # 基础方法实现
    # ------------------------------
    def sleep(self, secs: float) -> bool:
        """设备睡眠：不改变状态（避免影响其他操作）"""
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
            win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(
                self.window_handle)
            return (win_left, win_top, win_right - win_left, win_bottom - win_top)
        except Exception as e:
            error_msg = f"获取窗口矩形失败: {str(e)}"
            print(error_msg)
            self._update_device_state(DeviceState.ERROR)
            self.last_error = error_msg
            return None