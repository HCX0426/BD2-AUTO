import ctypes
import time
from typing import Dict, Optional, Tuple, Union
from ctypes import wintypes
import cv2
import numpy as np
import pydirectinput
import win32api
import win32con
import win32gui
import win32ui
import win32process
from PIL import Image
from auto_control.coordinate_transformer import CoordinateTransformer
from auto_control.device_base import BaseDevice, DeviceState
from auto_control.image_processor import ImageProcessor

class DCHandle:
    """DC资源上下文管理器：仅获取客户区DC，排除标题栏/边框"""
    def __init__(self, hwnd, logger):
        self.hwnd = hwnd
        self.hdc = None
        self.logger = logger

    def __enter__(self):
        self.hdc = win32gui.GetDC(self.hwnd)
        if not self.hdc:
            raise RuntimeError(f"获取客户区DC失败（窗口句柄: {self.hwnd}）")
        self.logger.debug(f"成功获取客户区DC: {self.hdc}（窗口句柄: {self.hwnd}）")
        return self.hdc

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.hdc and self.hwnd:
            try:
                win32gui.ReleaseDC(self.hwnd, self.hdc)
                self.logger.debug(f"成功释放客户区DC: {self.hdc}")
            except Exception as e:
                print(f"释放客户区DC失败: {str(e)}")


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
                print(f"释放位图失败: {str(e)}")


class WindowsDevice(BaseDevice):
    """Windows设备控制器：使用CoordinateTransformer判断全屏状态"""

    # 类常量
    WINDOW_RESTORE_DELAY = 0.5        # 窗口恢复后的等待时间
    WINDOW_ACTIVATE_DELAY = 0.1       # 窗口激活后的验证等待时间
    ACTIVATE_COOLDOWN = 5.0           # 激活冷却时间（5秒内不重复激活）

    def __init__(
        self,
        device_uri: str,
        logger = None,
        image_processor: Optional[ImageProcessor] = None,
        coord_transformer: Optional[CoordinateTransformer] = None
    ):
        super().__init__(device_uri)

        self.logger = logger
        self.device_uri = device_uri
        self.image_processor: ImageProcessor = image_processor
        self.coord_transformer: CoordinateTransformer = coord_transformer

        # 窗口基础信息（连接时初始化，稳定属性）
        self.hwnd: Optional[int] = None  # 窗口句柄
        self.window_title: str = ""      # 窗口标题
        self.window_class: str = ""      # 窗口类名（如UnityWndClass）
        self.process_id: int = 0         # 窗口所属进程ID
        self.physical_screen_res: Tuple[int, int] = (0, 0)  # 物理屏幕分辨率（稳定值）

        # 窗口动态信息（状态变化时更新）
        self._client_size: Tuple[int, int] = (0, 0)  # 客户区大小
        self.dpi_scale: float = 1.0      # 当前窗口DPI缩放因子
        self._window_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)  # 窗口矩形
        self.is_fullscreen: bool = False  # 是否全屏（动态变化）

        # 激活状态缓存
        self._last_activate_time = 0.0   # 上次激活时间（秒级时间戳）

        # 解析URI参数
        self.uri_params = self._parse_uri(device_uri)
        self.logger.debug(f"Windows设备URI参数: {self.uri_params}")
        # 启用DPI感知
        self._enable_dpi_awareness()

    def _parse_uri(self, uri: str) -> Dict[str, str]:
        """解析设备URI参数"""
        params = {}
        if "://" in uri:
            _, query = uri.split("://", 1)
            for part in query.split("&"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    params[key.lower()] = value
        return params

    def _get_window_handle(self) -> Optional[int]:
        """根据URI参数查找窗口句柄"""
        self.logger.info("开始查找窗口...")

        # 1. 精确标题匹配
        if "title" in self.uri_params:
            title = self.uri_params["title"]
            self.logger.info(f"尝试精确匹配标题: '{title}'")
            hwnd = win32gui.FindWindow(None, title)
            if hwnd:
                self.window_title = title
                self.logger.info(f"通过精确标题找到窗口: {title}, 句柄: {hwnd}")
                return hwnd
            self.logger.info(f"精确标题未找到窗口: {title}")

        # 2. 正则标题匹配
        if "title_re" in self.uri_params:
            import re
            pattern_str = self.uri_params["title_re"]
            self.logger.info(f"尝试正则匹配: '{pattern_str}'")

            if '*' in pattern_str and not (pattern_str.startswith('.*') or pattern_str.endswith('.*')):
                pattern_str = pattern_str.replace('*', '.*')
                self.logger.info(f"修正后的正则表达式: '{pattern_str}'")

            try:
                pattern = re.compile(pattern_str, re.IGNORECASE)
            except re.error as e:
                self.logger.error(f"正则表达式编译错误: {e}")
                return None

            matches = []
            def callback(hwnd, ctx):
                if win32gui.IsWindow(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title and pattern.search(title):
                        matches.append((hwnd, title))
                        self.logger.info(f"正则匹配找到窗口: 句柄={hwnd}, 标题='{title}'")
                return True
            win32gui.EnumWindows(callback, None)

            if matches:
                self.logger.info(f"找到 {len(matches)} 个匹配窗口")
                hwnd, title = matches[0]
                self.window_title = title
                return hwnd
            else:
                self.logger.info("正则匹配未找到窗口，枚举所有带标题窗口...")
                all_windows = []
                def debug_callback(hwnd, ctx):
                    if win32gui.IsWindow(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        if title:
                            all_windows.append((hwnd, title))
                            self.logger.info(f"窗口句柄: {hwnd}, 标题: '{title}'")
                win32gui.EnumWindows(debug_callback, None)
                self.logger.info(f"系统中共有 {len(all_windows)} 个带标题的窗口")

        # 3. 进程名匹配
        self.logger.info("尝试通过进程名查找窗口...")
        process_hwnd = self._find_window_by_process_name("BrownDust2")
        if process_hwnd:
            return process_hwnd

        # 4. 类名匹配
        self.logger.info("尝试通过类名查找窗口...")
        class_hwnd = win32gui.FindWindow("UnityWndClass", None)
        if class_hwnd:
            title = win32gui.GetWindowText(class_hwnd)
            self.logger.info(f"通过类名找到窗口: 句柄={class_hwnd}, 标题='{title}'")
            self.window_title = title
            return class_hwnd

        self.logger.error("未找到匹配的窗口")
        return None

    def _find_window_by_process_name(self, process_name: str) -> Optional[int]:
        """通过进程名查找窗口"""
        try:
            import psutil
            for proc in psutil.process_iter(['name', 'pid']):
                if proc.info['name'].lower() == process_name.lower():
                    pid = proc.info['pid']
                    self.logger.info(f"找到进程: {process_name}, PID: {pid}")

                    target_hwnd = None
                    def callback(hwnd, pid):
                        nonlocal target_hwnd
                        if win32gui.IsWindow(hwnd):
                            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                            if found_pid == pid:
                                title = win32gui.GetWindowText(hwnd)
                                if title:
                                    target_hwnd = hwnd
                                    self.logger.info(f"找到进程窗口: 句柄={hwnd}, 标题='{title}'")
                        return True
                    win32gui.EnumWindows(callback, pid)
                    if target_hwnd:
                        return target_hwnd
        except ImportError:
            self.logger.warning("psutil未安装，无法通过进程名查找窗口")
        except Exception as e:
            self.logger.error(f"通过进程名查找窗口出错: {e}")
        return None

    def _enable_dpi_awareness(self) -> None:
        """启用DPI感知"""
        try:
            import ctypes
            shcore = ctypes.windll.shcore
            result = shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            
            if result == 0:
                self.logger.debug("已成功启用Per-Monitor DPI感知模式")
                try:
                    from ctypes import wintypes
                    dpi = ctypes.windll.user32.GetDpiForSystem()
                    self.logger.debug(f"系统DPI: {dpi}")
                except:
                    pass
            else:
                self.logger.warning(f"SetProcessDpiAwareness失败，错误码: {result}")
                
        except Exception as e:
            self.logger.error(f"启用DPI感知失败: {e}")
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                self.logger.debug("已启用备用DPI感知模式")
            except:
                self.logger.error("所有DPI感知方法都失败")

    def _get_dpi_for_window(self) -> float:
        """获取当前窗口的DPI缩放因子"""
        if not self.hwnd:
            self.logger.warning("窗口句柄不存在，默认DPI=1.0")
            return 1.0

        try:
            if hasattr(ctypes.windll.user32, 'GetDpiForWindow'):
                dpi = ctypes.windll.user32.GetDpiForWindow(self.hwnd)
                if dpi > 0:
                    return dpi / 96.0

            monitor = ctypes.windll.user32.MonitorFromWindow(self.hwnd, win32con.MONITOR_DEFAULTTONEAREST)
            dpi_x = wintypes.UINT()
            if hasattr(ctypes.windll.shcore, 'GetDpiForMonitor'):
                ctypes.windll.shcore.GetDpiForMonitor(monitor, win32con.MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), None)
                return dpi_x.value / 96.0

            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, win32con.LOGPIXELSX)
            ctypes.windll.user32.ReleaseDC(0, hdc)
            return dpi / 96.0
        except Exception as e:
            self.logger.error(f"获取DPI失败: {e}，默认DPI=1.0")
            return 1.0

    def _get_screen_hardware_res(self) -> Tuple[int, int]:
        """获取物理屏幕分辨率（仅在connect时调用一次，后续复用缓存）"""
        try:
            class DEVMODE(ctypes.Structure):
                _fields_ = [
                    ("dmDeviceName", ctypes.c_wchar * 32),
                    ("dmSpecVersion", wintypes.WORD),
                    ("dmDriverVersion", wintypes.WORD),
                    ("dmSize", wintypes.WORD),
                    ("dmDriverExtra", wintypes.WORD),
                    ("dmFields", wintypes.DWORD),
                    ("dmPositionX", ctypes.c_long),
                    ("dmPositionY", ctypes.c_long),
                    ("dmDisplayOrientation", wintypes.DWORD),
                    ("dmDisplayFixedOutput", wintypes.DWORD),
                    ("dmColor", wintypes.SHORT),
                    ("dmDuplex", wintypes.SHORT),
                    ("dmYResolution", wintypes.SHORT),
                    ("dmTTOption", wintypes.SHORT),
                    ("dmCollate", wintypes.SHORT),
                    ("dmFormName", ctypes.c_wchar * 32),
                    ("dmLogPixels", wintypes.WORD),
                    ("dmBitsPerPel", wintypes.DWORD),
                    ("dmPelsWidth", wintypes.DWORD),
                    ("dmPelsHeight", wintypes.DWORD),
                    ("dmDisplayFlags", wintypes.DWORD),
                    ("dmDisplayFrequency", wintypes.DWORD),
                    ("dmICMMethod", wintypes.DWORD),
                    ("dmICMIntent", wintypes.DWORD),
                    ("dmMediaType", wintypes.DWORD),
                    ("dmDitherType", wintypes.DWORD),
                    ("dmReserved1", wintypes.DWORD),
                    ("dmReserved2", wintypes.DWORD),
                    ("dmPanningWidth", wintypes.DWORD),
                    ("dmPanningHeight", wintypes.DWORD),
                ]

            devmode = DEVMODE()
            devmode.dmSize = ctypes.sizeof(DEVMODE)
            
            result = ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(devmode))
            if result:
                return (devmode.dmPelsWidth, devmode.dmPelsHeight)
            else:
                screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
                screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
                self.logger.warning(f"枚举显示器设置失败，使用回退方案: {screen_w}x{screen_h}")
                return (screen_w, screen_h)
        except Exception as e:
            self.logger.error(f"获取物理分辨率失败: {e}")
            return (1920, 1080)

    def _update_dynamic_window_info(self) -> bool:
        """更新动态窗口信息（客户区大小、DPI、窗口位置等）"""
        if not self.hwnd:
            self.logger.error("无法更新窗口信息：窗口句柄不存在")
            return False

        try:
            if self.is_minimized():
                self.logger.debug("检测到窗口最小化，执行恢复操作")
                self.restore_window()
                time.sleep(0.1)
                if self.is_minimized():
                    raise RuntimeError("窗口恢复失败，仍处于最小化状态")

            # 获取窗口矩形
            self._window_rect = win32gui.GetWindowRect(self.hwnd)
            win_left, win_top, win_right, win_bottom = self._window_rect
            if win_left == 0 and win_top == 0 and win_right == 0 and win_bottom == 0:
                raise RuntimeError(f"获取窗口矩形失败，返回无效值: {self._window_rect}")

            # 更新DPI缩放因子（可能随显示器变化）
            self.dpi_scale = self._get_dpi_for_window()
            if self.dpi_scale <= 0:
                self.logger.warning(f"DPI缩放因子异常: {self.dpi_scale}，强制使用1.0")
                self.dpi_scale = 1.0

            # 计算缩放后的屏幕尺寸（用于辅助判断）
            scaled_screen_w = int(self.physical_screen_res[0] / self.dpi_scale)
            scaled_screen_h = int(self.physical_screen_res[1] / self.dpi_scale)

            # 获取客户区物理尺寸
            client_rect_phys = win32gui.GetClientRect(self.hwnd)
            client_w_phys = client_rect_phys[2] - client_rect_phys[0]
            client_h_phys = client_rect_phys[3] - client_rect_phys[1]
            if client_w_phys <= 0 or client_h_phys <= 0:
                raise RuntimeError(f"获取客户区物理尺寸失败: {client_w_phys}x{client_h_phys}")

            # 验证标题栏排除
            window_w_phys = win_right - win_left
            window_h_phys = win_bottom - win_top
            title_bar_height = window_h_phys - client_h_phys
            border_width = (window_w_phys - client_w_phys) // 2
            self.logger.debug(
                f"客户区验证 | 窗口尺寸: {window_w_phys}x{window_h_phys} | "
                f"客户区尺寸: {client_w_phys}x{client_h_phys} | "
                f"标题栏高度: {title_bar_height}px | 边框宽度: {border_width}px"
            )

            # 计算逻辑尺寸
            client_w_logic = int(round(client_w_phys * self.dpi_scale))
            client_h_logic = int(round(client_h_phys * self.dpi_scale))
            client_w_logic = max(800, client_w_logic)
            client_h_logic = max(600, client_h_logic)

            # 使用坐标转换器判断是否全屏
            if self.coord_transformer:
                self.is_fullscreen = self.coord_transformer._is_current_window_fullscreen(self.hwnd)
            else:
                # 备用方案：如果没有坐标转换器，使用简单判断
                is_borderless = (abs(window_w_phys - client_w_phys) <= 2) and (abs(window_h_phys - client_h_phys) <= 2)
                is_visual_fullscreen = (
                    win_left == 0 and win_top == 0 
                    and abs(win_right - scaled_screen_w) <= 2 
                    and abs(win_bottom - scaled_screen_h) <= 2 
                    and is_borderless
                )
                self.is_fullscreen = is_visual_fullscreen
                self.logger.warning("未使用坐标转换器判断全屏状态，可能存在误差")

            # 更新客户区尺寸
            self._client_size = (self.physical_screen_res if self.is_fullscreen 
                               else (client_w_logic, client_h_logic))

            # 更新坐标转换器
            if self.coord_transformer:
                self.coord_transformer.update_context(
                    client_size=self._client_size,
                    current_dpi=self.dpi_scale,
                    handle=self.hwnd
                )

            self.logger.debug(
                f"动态信息更新完成 | 模式: {'全屏' if self.is_fullscreen else '窗口'} | "
                f"客户区尺寸: {self._client_size} | DPI: {self.dpi_scale:.2f}"
            )
            return True

        except Exception as e:
            self.last_error = f"动态窗口信息更新失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            self._client_size = (1920, 1080)
            return False

    @property
    def client_size(self) -> Tuple[int, int]:
        """获取当前客户区尺寸"""
        return self._client_size

    def connect(self, timeout: float = 10.0) -> bool:
        """连接到Windows窗口，初始化并缓存稳定属性"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            self.hwnd = self._get_window_handle()
            if self.hwnd:
                # 缓存稳定属性（仅连接时计算一次）
                self.physical_screen_res = self._get_screen_hardware_res()  # 物理屏幕分辨率（稳定）
                self.window_class = win32gui.GetClassName(self.hwnd)       # 窗口类名（稳定）
                _, self.process_id = win32process.GetWindowThreadProcessId(self.hwnd)  # 进程ID（稳定）
                
                # 激活窗口并更新动态属性
                self.restore_window()
                self.set_foreground()
                time.sleep(0.5)
                if self._update_dynamic_window_info():  # 只更新动态属性
                    self.state = DeviceState.CONNECTED
                    self.logger.info(
                        f"已连接到Windows窗口 | 标题: {self.window_title} | 句柄: {self.hwnd} | "
                        f"类名: {self.window_class} | 进程ID: {self.process_id} | "
                        f"物理屏幕分辨率: {self.physical_screen_res}"
                    )
                    return True
            time.sleep(0.5)

        self.last_error = f"超时未找到匹配窗口（{timeout}s）"
        self.state = DeviceState.DISCONNECTED
        self.logger.error(f"连接失败: {self.last_error}")
        return False

    def disconnect(self) -> bool:
        """断开连接，重置所有属性"""
        if self.hwnd:
            self.logger.info(f"断开与窗口的连接: {self.window_title}（句柄: {self.hwnd}）")
            # 重置所有属性
            self.hwnd = None
            self.window_title = ""
            self.window_class = ""
            self.process_id = 0
            self.physical_screen_res = (0, 0)
            self._client_size = (0, 0)
            self.dpi_scale = 1.0
            self._window_rect = (0, 0, 0, 0)
            self.is_fullscreen = False
            self._last_activate_time = 0.0  # 重置激活缓存
            self.state = DeviceState.DISCONNECTED
            return True
        return False

    def is_minimized(self) -> bool:
        """检查窗口是否最小化"""
        if not self.hwnd:
            return True
        return win32gui.IsIconic(self.hwnd)

    def restore_window(self) -> bool:
        """恢复窗口（从最小化状态）"""
        if not self.hwnd:
            self.last_error = "未连接到窗口"
            return False

        try:
            if self.is_minimized():
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                time.sleep(self.WINDOW_RESTORE_DELAY)
            self._update_dynamic_window_info()  # 状态变化，更新动态属性
            self.logger.debug(f"窗口已恢复: {self.window_title}")
            return True
        except Exception as e:
            self.last_error = f"恢复窗口失败: {str(e)}"
            self.logger.error(self.last_error)
            return False

    def minimize_window(self) -> bool:
        """最小化窗口"""
        if not self.hwnd:
            self.last_error = "未连接到窗口"
            return False

        try:
            win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
            self.logger.info(f"窗口已最小化: {self.window_title}")
            return True
        except Exception as e:
            self.last_error = f"最小化窗口失败: {str(e)}"
            self.logger.error(self.last_error)
            return False

    def maximize_window(self) -> bool:
        """最大化窗口"""
        if not self.hwnd:
            self.last_error = "未连接到窗口"
            return False

        try:
            is_max = win32gui.IsZoomed(self.hwnd)
            if is_max:
                self.logger.debug("窗口已处于最大化状态，无需重复操作")
                return True
            
            win32gui.ShowWindow(self.hwnd, win32con.SW_MAXIMIZE)
            time.sleep(self.WINDOW_RESTORE_DELAY)
            self._update_dynamic_window_info()  # 状态变化，更新动态属性
            self.logger.info(f"窗口已最大化: {self.window_title}")
            return True
        except Exception as e:
            self.last_error = f"最大化窗口失败: {str(e)}"
            self.logger.error(self.last_error)
            return False

    def set_foreground(self) -> bool:
        """窗口激活逻辑（冷却+前台验证，避免频繁激活）"""
        if not self.hwnd:
            self.last_error = f"未连接到窗口或状态异常: {self.hwnd}|{self.state}"
            return False

        current_time = time.time()
        # 1. 冷却时间判断：1秒内已激活过，直接返回成功（跳过重复操作）
        if current_time - self._last_activate_time < self.ACTIVATE_COOLDOWN:
            self.logger.debug(
                f"窗口激活跳过（冷却期内）| 句柄: {self.hwnd} | "
                f"上次激活: {current_time - self._last_activate_time:.2f}s前"
            )
            return True

        # 2. 前台验证：当前前台窗口就是目标窗口，无需激活
        foreground_hwnd = win32gui.GetForegroundWindow()
        if foreground_hwnd == self.hwnd:
            self._last_activate_time = current_time  # 更新激活时间（刷新冷却）
            self.logger.debug(f"窗口已在前台 | 句柄: {self.hwnd} | 无需激活")
            return True

        # 3. 执行激活操作（仅当冷却过期且不在前台时）
        try:
            # 先恢复窗口（防止最小化导致激活无效）
            if self.is_minimized():
                self.logger.info("检测到窗口最小化，先恢复...")
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                time.sleep(self.WINDOW_RESTORE_DELAY)

            # 激活窗口并等待生效
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
            win32gui.SetForegroundWindow(self.hwnd)
            time.sleep(self.WINDOW_ACTIVATE_DELAY)

            # 4. 二次验证：确保激活成功
            final_foreground = win32gui.GetForegroundWindow()
            if final_foreground == self.hwnd and not self.is_minimized():
                self._last_activate_time = current_time  # 更新激活时间
                self.logger.info(f"窗口激活成功 | 句柄: {self.hwnd} | 标题: {self.window_title}")
                return True
            else:
                error_msg = (
                    f"窗口激活失败 | 目标句柄: {self.hwnd} | "
                    f"实际前台句柄: {final_foreground} | 最小化: {self.is_minimized()}"
                )
                self.last_error = error_msg
                self.logger.error(error_msg)
                return False
                
        except Exception as e:
            error_msg = f"窗口激活异常: {str(e)} | 句柄: {self.hwnd}"
            self.last_error = error_msg
            self.logger.error(error_msg, exc_info=True)
            return False

    def get_resolution(self) -> Tuple[int, int]:
        """获取当前客户区分辨率"""
        return self._client_size

    def capture_screen(self, roi: Optional[Tuple[int, int, int, int]] = None) -> Optional[np.ndarray]:
        """截取客户区屏幕"""
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return None

        try:
            if self.is_minimized():
                self.restore_window()
            if not self.set_foreground():
                raise RuntimeError("窗口激活失败，无法截图")
            time.sleep(0.1)

            cap_w, cap_h = self.physical_screen_res if self.is_fullscreen else self._client_size
            self.logger.debug(f"{'全屏' if self.is_fullscreen else '窗口'}模式 | 截图尺寸: {cap_w}x{cap_h}")

            with DCHandle(self.hwnd, self.logger) as hwndDC:
                mfcDC = win32ui.CreateDCFromHandle(hwndDC)
                saveDC = mfcDC.CreateCompatibleDC()
                saveBitMap = win32ui.CreateBitmap()
                saveBitMap.CreateCompatibleBitmap(mfcDC, cap_w, cap_h)
                saveDC.SelectObject(saveBitMap)

                print_flag = 0x00000002  # 仅截取客户区
                result = ctypes.windll.user32.PrintWindow(self.hwnd, saveDC.GetSafeHdc(), print_flag)
                if result != 1:
                    raise RuntimeError(f"PrintWindow截取客户区失败 | 返回值: {result}")

                bmpinfo = saveBitMap.GetInfo()
                bmpstr = saveBitMap.GetBitmapBits(True)
                im = Image.frombuffer(
                    'RGB',
                    (cap_w, cap_h),
                    bmpstr, 'raw', 'BGRX', 0, 1
                )
                img_np = np.array(im)

                saveDC.DeleteDC()
                mfcDC.DeleteDC()
                win32gui.DeleteObject(saveBitMap.GetHandle())

            if roi:
                rx, ry, rw, rh = roi
                if rx < 0 or ry < 0 or rx + rw > cap_w or ry + rh > cap_h:
                    self.logger.warning(f"ROI超出客户区范围 | ROI: {roi} | 忽略ROI")
                else:
                    img_np = img_np[ry:ry+rh, rx:rx+rw]

            return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        except Exception as e:
            self.last_error = f"截图失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return None

    def click(
            self,
            pos: Union[Tuple[int, int], str],
            click_time: int = 1,
            duration: float = 0.1,
            right_click: bool = False,
            is_base_coord: bool = False
        ) -> bool:
        """鼠标点击操作"""
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return False

        try:
            self.restore_window()
            self.set_foreground()
            time.sleep(0.1)

            target_pos: Optional[Tuple[int, int]] = None
            if isinstance(pos, str):
                if not self.image_processor:
                    self.last_error = "未设置图像处理器，无法模板匹配"
                    return False

                screen = self.capture_screen()
                if screen is None:
                    self.last_error = "截图失败，无法模板匹配"
                    return False

                match_result = self.image_processor.match_template(
                    image=screen,
                    template=pos,
                    current_dpi=self.dpi_scale,
                    hwnd=self.hwnd,
                    physical_screen_res=self.physical_screen_res,
                    threshold=0.6
                )
                if match_result is None:
                    self.last_error = f"模板匹配失败: {pos}"
                    return False

                if isinstance(match_result, np.ndarray):
                    match_rect = tuple(match_result.tolist())
                else:
                    match_rect = tuple(match_result)
                if len(match_rect) != 4:
                    self.last_error = f"模板结果格式错误: {match_rect}"
                    return False

                target_pos = self.image_processor.get_center(match_rect)
                if isinstance(target_pos, (list, np.ndarray)):
                    target_pos = tuple(map(int, target_pos))
                if not isinstance(target_pos, tuple) or len(target_pos) != 2:
                    self.last_error = f"中心点计算失败: {target_pos}"
                    return False
                target_pos = (int(target_pos[0]), int(target_pos[1]))
                self.logger.debug(f"模板 {pos} 中心点坐标: {target_pos}")

                is_base_coord = False
            else:
                target_pos = tuple(map(int, pos))

            if not target_pos or len(target_pos) != 2:
                self.last_error = f"无效的点击位置: {target_pos}"
                return False

            client_pos = target_pos
            if is_base_coord and self.coord_transformer:
                client_pos = self.coord_transformer.convert_original_to_current_client(*target_pos)
                self.logger.debug(f"原始坐标 {target_pos} → 当前客户区坐标 {client_pos}")

            screen_physical_x, screen_physical_y = self.coord_transformer.convert_current_client_to_screen(*client_pos)

            win32api.SetCursorPos((screen_physical_x, screen_physical_y))
            time.sleep(0.1)

            down_event = win32con.MOUSEEVENTF_RIGHTDOWN if right_click else win32con.MOUSEEVENTF_LEFTDOWN
            up_event = win32con.MOUSEEVENTF_RIGHTUP if right_click else win32con.MOUSEEVENTF_LEFTUP

            for _ in range(click_time):
                win32api.mouse_event(down_event, 0, 0, 0, 0)
                time.sleep(duration)
                win32api.mouse_event(up_event, 0, 0, 0, 0)
                if click_time > 1:
                    time.sleep(0.1)

            self.logger.info(
                f"点击成功 | 物理坐标: ({screen_physical_x},{screen_physical_y}) | "
                f"模板: {pos if isinstance(pos, str) else '直接坐标'}"
            )
            return True
        except Exception as e:
            self.last_error = f"点击失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False


    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.3,
        steps: int = 10,
        is_base_coord: bool = False
    ) -> bool:
        """鼠标滑动操作"""
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return False

        try:
            self.restore_window()
            self.set_foreground()
            time.sleep(0.1)

            start_pos = (start_x, start_y)
            end_pos = (end_x, end_y)
            if is_base_coord and self.coord_transformer:
                start_pos = self.coord_transformer.convert_original_to_current_client(*start_pos)
                end_pos = self.coord_transformer.convert_original_to_current_client(*end_pos)
                self.logger.debug(f"滑动坐标转换: {start_pos} → {end_pos}")

            screen_start = win32gui.ClientToScreen(self.hwnd, start_pos)
            screen_end = win32gui.ClientToScreen(self.hwnd, end_pos)
            self.logger.debug(f"滑动屏幕坐标: {screen_start} → {screen_end}")

            step_x = (screen_end[0] - screen_start[0]) / steps
            step_y = (screen_end[1] - screen_start[1]) / steps
            step_delay = duration / steps

            win32api.SetCursorPos(screen_start)
            time.sleep(0.1)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            for i in range(1, steps + 1):
                x = int(round(screen_start[0] + step_x * i))
                y = int(round(screen_start[1] + step_y * i))
                win32api.SetCursorPos((x, y))
                time.sleep(step_delay)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

            self.logger.debug(
                f"滑动成功 | 客户区: {start_pos} → {end_pos} | 时长: {duration}s | 步数: {steps}"
            )
            return True
        except Exception as e:
            self.last_error = f"滑动失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    def key_press(self, key: str, duration: float = 0.1) -> bool:
        """按键操作"""
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return False

        try:
            self.restore_window()
            self.set_foreground()
            time.sleep(0.1)

            pydirectinput.keyDown(key)
            time.sleep(duration)
            pydirectinput.keyUp(key)

            self.logger.debug(f"按键成功: {key}（时长: {duration}s）")
            return True
        except Exception as e:
            self.last_error = f"按键失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    def text_input(self, text: str, interval: float = 0.05) -> bool:
        """文本输入"""
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return False

        try:
            self.restore_window()
            self.set_foreground()
            time.sleep(0.1)

            if len(text) > 5:
                import pyperclip
                pyperclip.copy(text)
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                win32api.keybd_event(ord('V'), 0, 0, 0)
                time.sleep(0.05)
                win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(0.1)
                self.logger.debug(f"文本粘贴成功: {text[:20]}...（长度: {len(text)}）")
                return True

            for char in text:
                if char == ' ':
                    self.key_press("space", 0.02)
                elif char == '\n':
                    self.key_press("enter", 0.02)
                elif char == '\t':
                    self.key_press("tab", 0.02)
                else:
                    shift_pressed = char.isupper() or char in '~!@#$%^&*()_+{}|:"<>?'
                    if shift_pressed:
                        win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
                    win32api.keybd_event(ord(char.upper()), 0, 0, 0)
                    time.sleep(0.02)
                    win32api.keybd_event(ord(char.upper()), 0, win32con.KEYEVENTF_KEYUP, 0)
                    if shift_pressed:
                        win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(interval)

            self.logger.debug(f"文本输入成功: {text}")
            return True
        except Exception as e:
            self.last_error = f"文本输入失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    def exists(self, template_name: str, threshold: float = 0.6) -> Optional[Tuple[int, int]]:
        """检查模板是否存在"""
        try:
            if not self.hwnd:
                self.last_error = "未连接到窗口"
                return None

            self.set_foreground()
            if not self.image_processor:
                self.last_error = "未设置图像处理器"
                return None

            screen = self.capture_screen()
            if screen is None:
                self.logger.debug(f"截图为空，无法检查模板: {template_name}")
                return None

            self.logger.debug(f"检查模板: {template_name}（阈值: {threshold}）")
            match_result = self.image_processor.match_template(
                image=screen,
                template=template_name,
                current_dpi=self.dpi_scale,
                hwnd=self.hwnd,
                threshold=threshold,
                physical_screen_res=self.physical_screen_res
            )

            if match_result is None:
                self.logger.debug(f"模板未找到: {template_name}")
                return None

            if isinstance(match_result, np.ndarray):
                match_rect = tuple(match_result.tolist())
            else:
                match_rect = tuple(match_result)
            if len(match_rect) != 4:
                self.logger.warning(f"模板结果格式无效: {match_rect}，模板: {template_name}")
                return None

            center_pos = self.image_processor.get_center(match_rect)
            if isinstance(center_pos, (list, np.ndarray)):
                center_pos = tuple(map(int, center_pos))
            if not isinstance(center_pos, tuple) or len(center_pos) != 2:
                self.logger.warning(f"模板中心点无效: {center_pos}，模板: {template_name}")
                return None

            self.logger.debug(
                f"模板找到: {template_name} | 矩形区域: {match_rect} | "
                f"中心点: {center_pos}"
            )
            return center_pos
        except Exception as e:
            self.logger.error(f"模板检查异常: {str(e)}", exc_info=True)
            return None

    def wait(self, template_name: str, timeout: float = 10.0, interval: float = 0.5) -> Optional[Tuple[int, int]]:
        """等待模板出现"""
        start_time = time.time()
        self.logger.debug(f"开始等待模板: {template_name}（超时: {timeout}s，间隔: {interval}s）")

        while time.time() - start_time < timeout:
            center_pos = self.exists(template_name)
            if center_pos is not None:
                self.logger.info(f"模板 {template_name} 已找到（等待耗时: {time.time()-start_time:.1f}s），中心点: {center_pos}")
                return center_pos
            time.sleep(interval)

        self.last_error = f"等待模板超时: {template_name}（{timeout}s）"
        self.logger.error(self.last_error)
        return None

    def get_state(self) -> DeviceState:
        """获取设备状态"""
        if not self.hwnd:
            return DeviceState.DISCONNECTED

        try:
            if not win32gui.IsWindow(self.hwnd):
                self.hwnd = None
                return DeviceState.DISCONNECTED
            if not win32gui.IsWindowVisible(self.hwnd):
                return DeviceState.INVISIBLE
            return DeviceState.CONNECTED
        except Exception as e:
            self.logger.error(f"获取设备状态失败: {e}")
            return DeviceState.ERROR

    def sleep(self, secs: float) -> bool:
        """设备睡眠"""
        if secs <= 0:
            self.logger.warning(f"无效睡眠时间: {secs}秒")
            return False

        try:
            time.sleep(secs)
            self.logger.debug(f"设备睡眠完成: {secs}秒")
            return True
        except Exception as e:
            self.last_error = f"睡眠操作失败: {str(e)}"
            self.logger.error(self.last_error)
            return False