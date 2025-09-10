import ctypes
import time
from ctypes import c_int
from typing import Optional, Tuple, Union

import cv2
import numpy as np
import pydirectinput
import win32api
import win32con
import win32gui
import win32ui
from airtest.core.api import Template, connect_device, exists, paste, wait, touch
from airtest.core.api import sleep as air_sleep
from airtest.core.helper import logwrap
from PIL import Image

from auto_control.device_base import BaseDevice, DeviceState


class DCHandle:
    """DC资源上下文管理器，自动释放资源"""
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.hdc = None

    def __enter__(self):
        self.hdc = win32gui.GetWindowDC(self.hwnd)
        return self.hdc

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.hdc and self.hwnd:
            try:
                win32gui.ReleaseDC(self.hwnd, self.hdc)
            except Exception as e:
                # 使用print降级，避免日志循环依赖
                print(f"释放DC失败: {str(e)}")


class BitmapHandle:
    """位图资源上下文管理器，自动释放资源"""
    def __init__(self, bitmap):
        self.bitmap = bitmap

    def __enter__(self):
        return self.bitmap

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.bitmap:
            try:
                win32gui.DeleteObject(self.bitmap.GetHandle())
            except Exception as e:
                # 使用print降级，避免日志循环依赖
                print(f"释放位图失败: {str(e)}")


class WindowsDevice(BaseDevice):
    # 类常量
    FULLSCREEN_THRESHOLD = 5          # 全屏判断的尺寸差异阈值
    ORIGINAL_DPI_SCALE = 1.25         # 原始DPI缩放比例（125%）
    MOUSE_MOVE_DELAY = 0.05           # 鼠标移动后的稳定等待时间
    WINDOW_RESTORE_DELAY = 0.5        # 窗口恢复后的等待时间
    WINDOW_ACTIVATE_DELAY = 0.1       # 窗口激活后的验证等待时间
    BASE_RESOLUTION = (1920, 1080)    # 基准分辨率

    def __init__(self, device_uri: str, logger=None):
        super().__init__(device_uri)
        # 接收上层传递的日志实例（若无则使用默认logger）
        self.logger = logger if logger else self._create_default_logger()
        
        self.window_handle: Optional[int] = None
        self._window_original_rect: Optional[Tuple[int, int, int, int]] = None
        
        # 屏幕DPI信息
        self._screen_dpi: Tuple[int, int] = (96, 96)  # 默认DPI值
        self._scaling_percentage: str = "100%"  # DPI缩放百分比
        self._dpi_scale_factor: float = 1.0  # DPI缩放因子
        
        # 客户区尺寸（游戏实际渲染区域）
        self._client_size: Tuple[int, int] = (0, 0)
        # 窗口位置和尺寸缓存
        self._window_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (left, top, width, height)
        # 启用DPI感知（解决高DPI缩放问题）
        self._enable_dpi_awareness()

    def _create_default_logger(self):
        """降级方案：当无日志实例传入时，使用基础日志实现"""
        class DefaultLogger:
            @staticmethod
            def debug(msg):
                print(f"[DEBUG] WindowsDevice: {msg}")
            
            @staticmethod
            def info(msg):
                print(f"[INFO] WindowsDevice: {msg}")
            
            @staticmethod
            def error(msg, exc_info=False):
                print(f"[ERROR] WindowsDevice: {msg}")
        
        return DefaultLogger()

    # ------------------------------
    # 辅助检查方法：提取重复检查逻辑
    # ------------------------------
    def _check_window_handle(self, raise_error: bool = False) -> bool:
        """检查窗口句柄是否有效"""
        if not self.window_handle or not win32gui.IsWindow(self.window_handle):
            msg = "窗口句柄无效或已关闭"
            if raise_error:
                raise ValueError(msg)
            self.logger.error(msg)
            return False
        return True

    def _check_connected(self, raise_error: bool = False) -> bool:
        """检查设备是否已连接"""
        if not self.is_connected:
            msg = "设备未连接"
            if raise_error:
                raise RuntimeError(msg)
            self.logger.error(msg)
            return False
        return True

    def _ensure_window_active(self) -> bool:
        """确保窗口已激活且未最小化"""
        if not self.set_foreground() or self.minimized:
            self.logger.error("窗口未激活或已最小化")
            return False
        return True

    def _handle_operation_error(self, operation: str, e: Exception) -> bool:
        """统一处理操作异常"""
        error_msg = f"{operation}失败: {str(e)}"
        self.logger.error(error_msg, exc_info=True)  # 记录异常堆栈
        self.last_error = error_msg
        
        if self._should_change_to_error_state(error_msg):
            self._update_device_state(DeviceState.ERROR)
        else:
            self._update_device_state(DeviceState.IDLE)
            
        return False

    # ------------------------------
    # 初始化与系统相关方法
    # ------------------------------
    def _enable_dpi_awareness(self) -> None:
        """启用DPI感知，确保获取物理屏幕坐标"""
        try:
            # Windows 10+ 推荐模式（Per-Monitor DPI感知V2）
            ctypes.windll.user32.SetProcessDpiAwarenessContext(c_int(-4))
            self.logger.debug("已启用Per-Monitor DPI感知V2模式")
        except Exception as e:
            # 兼容旧系统（系统级DPI感知）
            ctypes.windll.user32.SetProcessDPIAware()
            self.logger.debug(f"启用DPI感知兼容模式: {e}")

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
            
            self.logger.debug(
                f"获取DPI信息: DPI=({dpi_x},{dpi_y}), "
                f"缩放={self._scaling_percentage}, "
                f"因子={self._dpi_scale_factor:.2f}"
            )
            
        except Exception as e:
            self.logger.error(f"获取屏幕DPI信息时出错: {e}")

    def get_screen_info(self) -> dict:
        """获取屏幕信息（分辨率和DPI）"""
        # 获取屏幕分辨率
        width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        
        # 获取DPI信息（如果尚未获取）
        if self._screen_dpi == (96, 96):
            self._get_screen_dpi_info()
        
        screen_info = {
            "resolution": (width, height),
            "dpi": self._screen_dpi,
            "scaling_percentage": self._scaling_percentage,
            "scale_factor": self._dpi_scale_factor
        }
        self.logger.debug(f"屏幕信息: {screen_info}")
        return screen_info

    # ------------------------------
    # 窗口信息管理
    # ------------------------------
    def _get_window_title(self) -> str:
        """从URI中提取窗口标题"""
        title_re_index = self.device_uri.find('title_re=')
        if title_re_index == -1:
            self.logger.warning("设备URI中未找到title_re参数")
            return ""
        remaining_part = self.device_uri[title_re_index + len('title_re='):]
        next_param_index = remaining_part.find('&')
        title = remaining_part[:next_param_index] if next_param_index != -1 else remaining_part
        self.logger.debug(f"从URI提取窗口标题: {title}")
        return title

    def _get_client_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """获取窗口客户区（游戏渲染区域）的坐标和尺寸"""
        if not self._check_window_handle():
            return None
            
        try:
            # 客户区坐标是相对于窗口左上角的（left=0, top=0）
            rect = win32gui.GetClientRect(self.window_handle)
            self.logger.debug(f"获取客户区坐标: {rect}")
            return rect
        except Exception as e:
            self.logger.error(f"获取客户区失败: {str(e)}")
            return None

    def _update_window_info(self) -> None:
        """统一更新所有窗口信息（位置、尺寸、客户区等）"""
        if not self._check_window_handle():
            return

        try:
            # 窗口整体区域（含边框/标题栏）
            win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(
                self.window_handle)
            win_width = win_right - win_left
            win_height = win_bottom - win_top
            
            # 更新缓存的窗口信息
            self._window_rect = (win_left, win_top, win_width, win_height)
            self.resolution = (win_width, win_height)
            self.minimized = win32gui.IsIconic(self.window_handle)

            # 客户区区域（游戏实际内容区域）
            client_rect = self._get_client_rect()
            if client_rect:
                _, _, client_right, client_bottom = client_rect
                self._client_size = (client_right, client_bottom)  # 客户区宽高

            # 记录原始窗口位置（仅第一次获取）
            if self._window_original_rect is None:
                self._window_original_rect = (win_left, win_top, win_right, win_bottom)
                self.logger.debug(f"记录原始窗口位置: {self._window_original_rect}")
                
            self.logger.debug(
                f"更新窗口信息: 位置=({win_left},{win_top}), "
                f"尺寸=({win_width}x{win_height}), "
                f"客户区=({self._client_size[0]}x{self._client_size[1]}), "
                f"最小化={self.minimized}"
            )
                
        except Exception as e:
            error_msg = f"更新窗口信息失败: {str(e)}"
            self.logger.error(error_msg)
            self.last_error = error_msg

    # ------------------------------
    # 连接与断开
    # ------------------------------
    def connect(self, timeout: float = 15.0) -> bool:
        """连接设备：严格遵循 CONNECTING → CONNECTED → IDLE 状态流程"""
        # 先尝试转为CONNECTING状态（非法转换会直接返回False）
        if not self._update_device_state(DeviceState.CONNECTING):
            self.logger.warning(f"无法发起连接：当前状态{self.state}不允许")
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
                    self._update_window_info()  # 统一更新窗口信息
                    # 检查客户区是否有效（避免窗口未加载完成）
                    if all(self._client_size):  # 简化判断：只要宽高都不为0
                        # 连接成功：先转为CONNECTED，再转为IDLE
                        self._update_device_state(DeviceState.CONNECTED)
                        self._update_device_state(DeviceState.IDLE)
                        self.logger.info(
                            f"Windows设备连接成功：{window_title}（客户区尺寸：{self._client_size}）"
                        )
                        # 打印屏幕信息
                        screen_info = self.get_screen_info()
                        self.logger.info(
                            f"屏幕信息: 分辨率={screen_info['resolution']}, "
                            f"DPI={screen_info['dpi']}, "
                            f"缩放={screen_info['scaling_percentage']}"
                        )
                        return True
                self.sleep(0.1)

            raise TimeoutError("查找窗口超时或客户区无效")
        except Exception as e:
            error_msg = f"连接Windows设备失败: {str(e)}"
            self.logger.error(error_msg)
            # 连接失败：转为DISCONNECTED（而非ERROR，便于重试）
            self._update_device_state(DeviceState.DISCONNECTED)
            self.last_error = error_msg
            return False

    def disconnect(self) -> bool:
        """断开连接：清理资源并转为DISCONNECTED状态"""
        # 只有已连接状态才能断开
        if not self.is_connected:
            self.logger.info("无需断开：设备未连接")
            return True

        try:
            # 先转为DISCONNECTED状态
            if not self._update_device_state(DeviceState.DISCONNECTED):
                self.logger.warning("断开失败：当前状态不允许")
                return False

            # 清理所有资源
            self.window_handle = None
            self.resolution = (0, 0)
            self._client_size = (0, 0)
            self._window_rect = (0, 0, 0, 0)
            self.minimized = False
            self._window_original_rect = None
            self.last_error = None
            self.logger.info("Windows设备断开连接成功")
            return True
        except Exception as e:
            return self._handle_operation_error("断开Windows设备连接", e)

    # ------------------------------
    # 坐标转换
    # ------------------------------
    def convert_to_client_coords(self, x: int, y: int) -> Tuple[int, int]:
        """将基准坐标转换为窗口客户区坐标，考虑DPI缩放"""
        self._check_connected(raise_error=True)
        self._update_window_info()  # 确保窗口信息最新
        
        base_width, base_height = self.BASE_RESOLUTION
        client_width, client_height = self._client_size

        # 防止客户区未初始化导致除零
        if not all((client_width, client_height)):
            self._update_window_info()
            client_width, client_height = self._client_size
            if not all((client_width, client_height)):
                raise ValueError("客户区尺寸无效，无法转换坐标")

        # 按客户区尺寸缩放基准坐标，并考虑原始DPI缩放因子
        client_x = int(x * (client_width / base_width) / 
                      (self._dpi_scale_factor / self.ORIGINAL_DPI_SCALE))
        client_y = int(y * (client_height / base_height) / 
                      (self._dpi_scale_factor / self.ORIGINAL_DPI_SCALE))
        
        self.logger.debug(
            f"坐标转换: 基准坐标({x},{y}) → 客户区坐标({client_x},{client_y}) "
            f"(基准分辨率={self.BASE_RESOLUTION}, 客户区={self._client_size})"
        )
        return client_x, client_y

    def client_to_screen(self, client_x: int, client_y: int) -> Tuple[int, int]:
        self._check_window_handle(raise_error=True)
        self._update_window_info()  # 确保窗口信息最新
        
        try:
            # 检查是否已经是全屏状态
            if self._is_fullscreen():
                self.logger.debug(f"全屏模式，直接使用客户区坐标: ({client_x},{client_y})")
                return (client_x, client_y)
                
            # 应用DPI缩放因子
            scaled_client_x = int(client_x * self._dpi_scale_factor)
            scaled_client_y = int(client_y * self._dpi_scale_factor)
            
            # 使用ClientToScreen API获取客户区原点
            client_origin = win32gui.ClientToScreen(self.window_handle, (0, 0))
            
            # 计算屏幕坐标
            screen_x = client_origin[0] + scaled_client_x
            screen_y = client_origin[1] + scaled_client_y
            
            self.logger.debug(
                f"坐标转换: 客户区({client_x},{client_y}) → 屏幕({screen_x},{screen_y}) "
                f"(DPI缩放={self._dpi_scale_factor:.2f}, 客户区原点={client_origin})"
            )
            return (screen_x, screen_y)
            
        except Exception as e:
            raise RuntimeError(f"坐标转换失败: {str(e)}")
            
    def _is_fullscreen(self) -> bool:
        """判断窗口是否处于全屏状态"""
        if not self._check_window_handle():
            return False
            
        # 获取窗口矩形和客户区矩形
        _, _, win_width, win_height = self._window_rect
        client_rect = self._get_client_rect()
        
        if not client_rect:
            return False
            
        # 比较窗口和客户区大小
        _, _, client_width, client_height = client_rect
        
        # 如果客户区大小与窗口大小几乎相同，则认为处于全屏状态
        is_full = (abs(win_width - client_width) < self.FULLSCREEN_THRESHOLD and 
                  abs(win_height - client_height) < self.FULLSCREEN_THRESHOLD)
                  
        self.logger.debug(
            f"全屏判断: 窗口({win_width}x{win_height}) vs 客户区({client_width}x{client_height}) → {is_full}"
        )
        return is_full

    # ------------------------------
    # 核心操作方法
    # ------------------------------
    @BaseDevice.require_operable
    def capture_screen(self) -> Optional[np.ndarray]:
        """捕获屏幕截图：状态流程 IDLE → BUSY → IDLE/ERROR"""
        try:
            self._check_window_handle(raise_error=True)
            self._update_window_info()  # 确保窗口信息最新
            
            # 获取客户区（游戏渲染区域）
            client_rect = self._get_client_rect()
            if not client_rect:
                raise RuntimeError("客户区无效")
            _, _, client_width, client_height = client_rect
            self.logger.debug(f"开始截图: 客户区尺寸({client_width}x{client_height})")

            # 使用上下文管理器管理DC资源
            with DCHandle(self.window_handle) as hwndDC:
                if not hwndDC:
                    raise RuntimeError("获取窗口DC失败")

                # 创建兼容DC（父DC：mfcDC）
                mfcDC = win32ui.CreateDCFromHandle(hwndDC)
                if not mfcDC:
                    raise RuntimeError("创建MFC DC失败")

                # 创建子DC（用于保存截图，依赖mfcDC）
                saveDC = mfcDC.CreateCompatibleDC()
                if not saveDC:
                    raise RuntimeError("创建保存DC失败")

                # 使用上下文管理器管理位图资源
                with BitmapHandle(win32ui.CreateBitmap()) as saveBitMap:
                    saveBitMap.CreateCompatibleBitmap(mfcDC, client_width, client_height)
                    saveDC.SelectObject(saveBitMap)

                    # 执行截图（PrintWindow）
                    result = ctypes.windll.user32.PrintWindow(
                        self.window_handle, saveDC.GetSafeHdc(), 0x00000002)
                    if result != 1:
                        raise RuntimeError(f"PrintWindow截图失败，返回值: {result}")

                    # 转换位图为numpy数组（BGR格式，适配OpenCV）
                    bmpinfo = saveBitMap.GetInfo()
                    bmpstr = saveBitMap.GetBitmapBits(True)
                    im = Image.frombuffer(
                        'RGB',
                        (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                        bmpstr, 'raw', 'BGRX', 0, 1
                    )
                    img = np.array(im)
                    self._update_device_state(DeviceState.IDLE)
                    self.logger.debug("截图完成，转换为BGR格式返回")
                    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        except Exception as e:
            return self._handle_operation_error("截图", e)

        finally:
            # 释放DC资源（按创建逆序）
            try:
                saveDC.DeleteDC()
            except:
                pass
            try:
                mfcDC.DeleteDC()
            except:
                pass

    def set_foreground(self) -> bool:
        """激活并置前窗口"""
        if not self._check_connected() or not self._check_window_handle():
            return False

        try:
            # 强制更新窗口状态
            self._update_window_info()
            
            # 如果窗口最小化，先恢复
            if self.minimized:
                self.logger.info("检测到窗口最小化，正在恢复...")
                win32gui.ShowWindow(self.window_handle, win32con.SW_RESTORE)
                time.sleep(self.WINDOW_RESTORE_DELAY)  # 等待窗口恢复
                self._update_window_info()  # 再次更新状态
            
            # 激活窗口
            win32gui.ShowWindow(self.window_handle, win32con.SW_SHOW)
            win32gui.SetForegroundWindow(self.window_handle)
            
            # 检查是否真的激活了
            time.sleep(self.WINDOW_ACTIVATE_DELAY)
            foreground_window = win32gui.GetForegroundWindow()
            
            if foreground_window == self.window_handle and not self.is_minimized():
                self.logger.info("窗口激活成功")
                return True
            else:
                self.logger.error(
                    f"窗口激活失败: 前景窗口={foreground_window}, "
                    f"目标窗口={self.window_handle}, 最小化={self.minimized}"
                )
                return False
                
        except Exception as e:
            error_msg = f"窗口置前失败: {str(e)}"
            self.logger.error(error_msg)
            self.last_error = error_msg
            return False

    def _should_change_to_error_state(self, error_msg: str) -> bool:
        """判断错误是否严重到需要改变设备状态"""
        serious_errors = [
            "设备未连接", "窗口句柄无效", "设备不可用",
            "截图失败", "PrintWindow截图失败", "获取窗口DC失败",
            "连接失败", "断开连接失败"
        ]
        
        # 检查错误消息中是否包含严重错误关键词
        result = any(error in error_msg for error in serious_errors)
        self.logger.debug(f"严重错误判断: {error_msg} → {result}")
        return result

    @logwrap
    @BaseDevice.require_operable
    def click(self,
              pos: Union[Tuple[int, int], Template],
              duration: float = 0.1,
              click_time: int = 1,
              right_click: bool = False,
              is_base_coord: bool = False) -> bool:
        """点击操作：支持坐标输入（基准坐标/客户区坐标），支持多点击"""
        # 前置校验：点击次数合法性
        if click_time < 1:
            self.logger.warning(f"无法点击：点击次数必须≥1（当前：{click_time}）")
            self._update_device_state(DeviceState.IDLE)
            return False

        try:
            if not self._ensure_window_active():
                raise RuntimeError("窗口未激活或已最小化")
            
            if isinstance(pos, Template):
                # 模板点击
                try:
                    target_screen_x, target_screen_y = touch(
                        pos, time=click_time, duration=duration, right_click=right_click
                    )
                    self.logger.debug(f"模板点击成功: {pos.filename}")
                except Exception as template_error:
                    error_msg = f"模板点击失败: {str(template_error)}"
                    self.logger.error(error_msg)
                    self.last_error = error_msg
                    self._update_device_state(DeviceState.IDLE)
                    return False
            else:
                # 坐标转换：基准坐标 → 客户区坐标 → 屏幕坐标
                x, y = pos
                if is_base_coord:
                    # 基准坐标 → 客户区坐标
                    client_x, client_y = self.convert_to_client_coords(x, y)
                    self.logger.debug(f"基准坐标({x},{y}) → 客户区坐标({client_x},{client_y})")
                else:
                    # 直接使用客户区坐标
                    client_x, client_y = x, y
                    self.logger.debug(f"使用客户区坐标: ({client_x},{client_y})")

                # 客户区坐标 → 屏幕坐标
                target_screen_x, target_screen_y = self.client_to_screen(client_x, client_y)
                self.logger.debug(f"客户区坐标 → 屏幕坐标: ({target_screen_x},{target_screen_y})")

                # 执行点击（支持多次点击）
                # 先移动鼠标到目标位置
                win32api.SetCursorPos((target_screen_x, target_screen_y))
                time.sleep(self.MOUSE_MOVE_DELAY)  # 等待鼠标移动稳定

                # 定义点击事件（左键/右键）
                down_event = win32con.MOUSEEVENTF_RIGHTDOWN if right_click else win32con.MOUSEEVENTF_LEFTDOWN
                up_event = win32con.MOUSEEVENTF_RIGHTUP if right_click else win32con.MOUSEEVENTF_LEFTUP

                # 循环执行点击
                for i in range(click_time):
                    win32api.mouse_event(down_event, 0, 0, 0, 0)
                    time.sleep(duration)
                    win32api.mouse_event(up_event, 0, 0, 0, 0)
                    if i < click_time - 1:
                        time.sleep(0.1)

            # 点击成功：恢复IDLE状态
            self._update_device_state(DeviceState.IDLE)
            click_type = "右键" if right_click else "左键"
            coord_type = "基准坐标" if is_base_coord else "客户区坐标"
            self.logger.info(
                f"点击成功：{click_type} {click_time}次 | "
                f"屏幕坐标{target_screen_x, target_screen_y} | 源类型：{coord_type}"
            )
            return True

        except Exception as e:
            return self._handle_operation_error("点击操作", e)

    @logwrap
    @BaseDevice.require_operable
    def key_press(self, key: str, duration: float = 0.1) -> bool:
        """按键操作"""
        try:
            if not self._ensure_window_active():
                raise RuntimeError("窗口未激活或已最小化")

            # 执行按键按下+抬起
            self.logger.debug(f"执行按键: {key}（按住{duration}秒）")
            pydirectinput.keyDown(key)
            time.sleep(duration)
            pydirectinput.keyUp(key)

            self._update_device_state(DeviceState.IDLE)
            self.logger.info(f"按键成功：{key}（按住{duration}秒）")
            return True
        except Exception as e:
            return self._handle_operation_error("按键操作", e)

    @BaseDevice.require_operable
    def text_input(self, text: str, interval: float = 0.05) -> bool:
        """文本输入：优先使用粘贴，确保效率和兼容性"""
        try:
            if not self._ensure_window_active():
                raise RuntimeError("窗口未激活或已最小化")

            self.logger.debug(f"准备输入文本: {text}（间隔{interval}秒）")
            # 使用Airtest的paste方法（兼容大多数场景）
            paste(text)
            time.sleep(interval * len(text))  # 等待输入完成

            self._update_device_state(DeviceState.IDLE)
            self.logger.info(f"文本输入成功：{text}")
            return True
        except Exception as e:
            return self._handle_operation_error("文本输入", e)

    @logwrap
    @BaseDevice.require_operable
    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 2,
            steps: int = 50, is_base_coord: bool = False) -> bool:
        """平滑滑动操作：支持基准坐标和客户区坐标"""
        try:
            if not self._ensure_window_active():
                raise RuntimeError("窗口未激活或已最小化")

            # 坐标转换：基准坐标 → 客户区坐标
            if is_base_coord:
                start_client_x, start_client_y = self.convert_to_client_coords(start_x, start_y)
                end_client_x, end_client_y = self.convert_to_client_coords(end_x, end_y)
                self.logger.debug(
                    f"基准坐标滑动: 从({start_x},{start_y})→({end_x},{end_y}) "
                    f"→ 客户区({start_client_x},{start_client_y})→({end_client_x},{end_client_y})"
                )
            else:
                start_client_x, start_client_y = start_x, start_y
                end_client_x, end_client_y = end_x, end_y
                self.logger.debug(
                    f"客户区坐标滑动: 从({start_client_x},{start_client_y})→({end_client_x},{end_client_y})"
                )

            # 客户区坐标 → 屏幕坐标
            start_screen_x, start_screen_y = self.client_to_screen(start_client_x, start_client_y)
            end_screen_x, end_screen_y = self.client_to_screen(end_client_x, end_client_y)

            # 计算总移动距离
            dx = end_screen_x - start_screen_x
            dy = end_screen_y - start_screen_y

            self.logger.debug(
                f"滑动参数: 屏幕起点({start_screen_x},{start_screen_y}), "
                f"终点({end_screen_x},{end_screen_y}), "
                f"距离({dx},{dy}), 步数{steps}, 总时长{duration}秒"
            )

            # 移动到起始位置
            win32api.SetCursorPos((start_screen_x, start_screen_y))
            time.sleep(0.05)  # 短暂等待确保鼠标就位

            # 按下鼠标左键
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)  # 短暂等待确保按下生效

            # 使用鼠标事件进行平滑滑动
            start_time = time.time()
            elapsed = 0
            
            while elapsed < duration:
                # 计算当前进度 (0.0 到 1.0)
                progress = min(1.0, elapsed / duration)
                
                # 使用缓动函数使滑动更平滑 (这里使用二次缓出)
                # 不同的缓动函数: progress (线性), progress**2 (加速), 1 - (1-progress)**2 (减速)
                eased_progress = 1 - (1 - progress) ** 2
                
                # 计算当前位置
                current_x = int(start_screen_x + dx * eased_progress)
                current_y = int(start_screen_y + dy * eased_progress)
                
                # 移动到当前位置
                win32api.SetCursorPos((current_x, current_y))
                
                # 计算下一帧的时间
                time.sleep(0.01)  # 10ms的更新间隔提供平滑效果
                elapsed = time.time() - start_time

            # 确保到达终点
            win32api.SetCursorPos((end_screen_x, end_screen_y))
            time.sleep(0.05)  # 短暂等待确保到达终点

            # 释放鼠标左键
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            
            self._update_device_state(DeviceState.IDLE)
            coord_type = "基准坐标" if is_base_coord else "客户区坐标"
            self.logger.info(
                f"滑动成功：从{start_screen_x, start_screen_y}到{end_screen_x, end_screen_y} "
                f"| 类型:{coord_type} | 时长{duration}s"
            )
            return True
        except Exception as e:
            return self._handle_operation_error("滑动操作", e)

    @BaseDevice.require_operable
    def wait(self, template, timeout: float = 10.0) -> bool:
        """等待元素出现"""
        # 只在需要时转为BUSY状态
        was_busy = self.state == DeviceState.BUSY

        try:
            if not self._ensure_window_active():
                raise RuntimeError("窗口未激活或已最小化")

            self.logger.debug(f"等待元素: {template.filename}（超时{timeout}秒）")
            # 等待模板匹配
            pos = wait(template, timeout=timeout)
            
            # 恢复状态
            if not was_busy:
                self._update_device_state(DeviceState.IDLE)
                
            if pos:
                self.logger.info(f"等待元素成功：{template.filename}（坐标：{pos}）")
                return True
            else:
                self.logger.warning(f"等待元素超时：{template.filename}（{timeout}秒）")
                return False
                
        except Exception as e:
            error_msg = f"等待元素失败: {str(e)}"
            self.logger.error(error_msg)
            self.last_error = error_msg
            
            if not was_busy:
                self._update_device_state(DeviceState.IDLE)
                
            return False

    @BaseDevice.require_operable
    def exists(self, template) -> bool:
        """检查元素是否存在"""
        if not self._check_connected():
            return False

        # 只在需要时转为BUSY状态
        was_busy = self.state == DeviceState.BUSY

        try:
            if not isinstance(template, Template):
                self.logger.error(f"模板参数必须是Template对象,当前类型为:{type(template)}")
                return False

            self.logger.debug(f"检查元素是否存在: {template.filename}")
            # 检查元素存在性
            result = exists(template)
            
            # 恢复状态
            if not was_busy:
                self._update_device_state(DeviceState.IDLE)
                
            self.logger.info(f"元素检查结果：{template.filename} → {'存在' if result else '不存在'}")
            return result
            
        except Exception as e:
            error_msg = f"检查元素存在失败: {str(e)}"
            self.logger.error(error_msg)
            self.last_error = error_msg
            
            if not was_busy:
                self._update_device_state(DeviceState.IDLE)
                
            return False

    # ------------------------------
    # 窗口管理功能
    # ------------------------------
    @BaseDevice.require_operable
    def minimize_window(self) -> bool:
        if not self._check_connected() or not self._check_window_handle():
            return False

        try:
            self.logger.debug(f"最小化窗口: {self.window_handle}")
            win32gui.ShowWindow(self.window_handle, win32con.SW_MINIMIZE)
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            self.logger.info("窗口最小化成功")
            return True
        except Exception as e:
            return self._handle_operation_error("最小化窗口", e)

    @BaseDevice.require_operable
    def maximize_window(self) -> bool:
        if not self._check_connected() or not self._check_window_handle():
            return False

        try:
            self.logger.debug(f"最大化窗口: {self.window_handle}")
            win32gui.ShowWindow(self.window_handle, win32con.SW_MAXIMIZE)
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            self.logger.info("窗口最大化成功")
            return True
        except Exception as e:
            return self._handle_operation_error("最大化窗口", e)

    @BaseDevice.require_operable
    def restore_window(self) -> bool:
        if not self._check_connected() or not self._check_window_handle():
            return False

        try:
            self.logger.debug(f"恢复窗口: {self.window_handle}")
            win32gui.ShowWindow(self.window_handle, win32con.SW_RESTORE)
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            self.logger.info("窗口恢复成功")
            return True
        except Exception as e:
            return self._handle_operation_error("恢复窗口", e)

    @BaseDevice.require_operable
    def resize_window(self, width: int, height: int) -> bool:
        if not self._check_connected() or not self._check_window_handle():
            return False

        try:
            # 从缓存的窗口信息中获取位置
            win_left, win_top, _, _ = self._window_rect
            self.logger.debug(f"调整窗口大小: {width}x{height}，位置({win_left},{win_top})")
            # 调整窗口大小
            win32gui.SetWindowPos(
                self.window_handle,
                win32con.HWND_TOP,
                win_left, win_top, width, height,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
            )
            self._update_window_info()  # 强制更新客户区尺寸
            self._update_device_state(DeviceState.IDLE)
            self.logger.info(f"窗口调整为 {width}x{height} 成功")
            return True
        except Exception as e:
            return self._handle_operation_error("调整窗口大小", e)

    @BaseDevice.require_operable
    def move_window(self, x: int, y: int) -> bool:
        if not self._check_connected() or not self._check_window_handle():
            return False

        try:
            # 从缓存的窗口信息中获取尺寸
            _, _, win_width, win_height = self._window_rect
            self.logger.debug(f"移动窗口到: ({x},{y})，尺寸保持({win_width}x{win_height})")
            win32gui.SetWindowPos(
                self.window_handle,
                win32con.HWND_TOP,
                x, y, win_width, win_height,
                win32con.SWP_NOZORDER | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
            )
            self._update_window_info()  # 更新位置信息
            self._update_device_state(DeviceState.IDLE)
            self.logger.info(f"窗口移动到 ({x},{y}) 成功")
            return True
        except Exception as e:
            return self._handle_operation_error("移动窗口", e)

    @BaseDevice.require_operable
    def reset_window(self) -> bool:
        if not self._check_connected() or not self._check_window_handle() or not self._window_original_rect:
            return False

        try:
            win_left, win_top, win_right, win_bottom = self._window_original_rect
            win_width = win_right - win_left
            win_height = win_bottom - win_top
            self.logger.debug(f"重置窗口到原始状态: 位置({win_left},{win_top}), 尺寸({win_width}x{win_height})")

            win32gui.SetWindowPos(
                self.window_handle,
                win32con.HWND_TOP,
                win_left, win_top, win_width, win_height,
                win32con.SWP_NOZORDER
            )
            self._update_window_info()
            self._update_device_state(DeviceState.IDLE)
            self.logger.info("窗口重置成功")
            return True
        except Exception as e:
            return self._handle_operation_error("重置窗口", e)

    # ------------------------------
    # 基础方法实现
    # ------------------------------
    def sleep(self, secs: float) -> bool:
        """设备睡眠：不改变状态"""
        try:
            self.logger.debug(f"设备睡眠: {secs}秒")
            air_sleep(secs)
            return True
        except Exception as e:
            self.logger.error(f"设备睡眠失败: {str(e)}")
            return False
    