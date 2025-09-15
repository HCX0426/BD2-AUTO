import ctypes
import time
from typing import Dict, Optional, Tuple, Union
from ctypes import c_int, wintypes
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
    def __init__(self, hwnd,logger):
        self.hwnd = hwnd
        self.hdc = None
        self.logger = logger

    def __enter__(self):
        # 关键修改：GetDC → 仅获取客户区DC；GetWindowDC会包含标题栏，已废弃
        self.hdc = win32gui.GetDC(self.hwnd)
        if not self.hdc:
            raise RuntimeError(f"获取客户区DC失败（窗口句柄: {self.hwnd}）")
        self.logger.debug(f"成功获取客户区DC: {self.hdc}（窗口句柄: {self.hwnd}）")
        return self.hdc

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.hdc and self.hwnd:
            try:
                # 释放客户区DC（对应GetDC）
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
    """Windows设备控制器：全屏截屏幕分辨率，窗口截当前客户区，适配DPI变化"""

    # 类常量
    WINDOW_RESTORE_DELAY = 0.5        # 窗口恢复后的等待时间
    WINDOW_ACTIVATE_DELAY = 0.1       # 窗口激活后的验证等待时间

    def __init__(
        self,
        device_uri: str,
        logger = None,
        image_processor: Optional[ImageProcessor] = None,
        coord_transformer: Optional[CoordinateTransformer] = None
    ):
        super().__init__(device_uri)

        self.logger = logger
        self.image_processor: ImageProcessor = image_processor
        self.coord_transformer: CoordinateTransformer = coord_transformer

        # 窗口信息
        self.hwnd: Optional[int] = None  # 窗口句柄
        self.window_title: str = ""      # 窗口标题
        self._client_size: Tuple[int, int] = (0, 0)  # 客户区大小（全屏=屏幕分辨率，窗口=物理尺寸）
        self.dpi_scale: float = 1.0      # 当前窗口DPI缩放因子
        self._window_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)  # 窗口矩形
        self.minimized = False  # 窗口是否最小化

        # 解析URI参数
        self.uri_params = self._parse_uri(device_uri)
        self.logger.debug(f"Windows设备URI参数: {self.uri_params}")
        # 启用DPI感知（确保获取正确的物理尺寸和DPI）
        self._enable_dpi_awareness()

    def _parse_uri(self, uri: str) -> Dict[str, str]:
        """解析设备URI参数（格式: windows://title=xxx 或 windows://title_re=xxx）"""
        params = {}
        if "://" in uri:
            _, query = uri.split("://", 1)
            for part in query.split("&"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    params[key.lower()] = value
        return params

    def _get_window_handle(self) -> Optional[int]:
        """根据URI参数查找窗口句柄（支持精确/正则/进程/类名匹配）"""
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

            # 修复正则：将*替换为.*（兼容用户输入习惯）
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

        # 3. 进程名匹配（针对BrownDust2）
        self.logger.info("尝试通过进程名查找窗口...")
        process_hwnd = self._find_window_by_process_name("BrownDust2")
        if process_hwnd:
            return process_hwnd

        # 4. 类名匹配（Unity游戏默认类名）
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
        """通过进程名查找窗口（依赖psutil）"""
        try:
            import psutil
            for proc in psutil.process_iter(['name', 'pid']):
                if proc.info['name'].lower() == process_name.lower():
                    pid = proc.info['pid']
                    self.logger.info(f"找到进程: {process_name}, PID: {pid}")

                    # 枚举该进程的所有窗口
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
        """启用DPI感知（Windows 11专用优化版）"""
        try:
            # 直接使用SetProcessDpiAwareness（Windows 8.1+推荐）
            import ctypes
            shcore = ctypes.windll.shcore
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            result = shcore.SetProcessDpiAwareness(2)
            
            if result == 0:  # S_OK
                self.logger.debug("已成功启用Per-Monitor DPI感知模式")
                
                # 可选：获取当前DPI信息用于调试
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
            
            # 备用方案（通常不需要，但保留）
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                self.logger.debug("已启用备用DPI感知模式")
            except:
                self.logger.error("所有DPI感知方法都失败")

    def _get_dpi_for_window(self) -> float:
        """获取当前窗口的DPI缩放因子（优先级：窗口DPI > 监视器DPI > 系统DPI）"""
        if not self.hwnd:
            self.logger.warning("窗口句柄不存在，默认DPI=1.0")
            return 1.0

        try:
            # 1. 优先获取窗口专属DPI（Windows 10+）
            if hasattr(ctypes.windll.user32, 'GetDpiForWindow'):
                dpi = ctypes.windll.user32.GetDpiForWindow(self.hwnd)
                if dpi > 0:
                    return dpi / 96.0  # 96为默认DPI，转换为缩放因子（如120→1.25）

            # 2. 回退：获取窗口所在监视器的DPI
            monitor = ctypes.windll.user32.MonitorFromWindow(self.hwnd, win32con.MONITOR_DEFAULTTONEAREST)
            dpi_x = wintypes.UINT()
            if hasattr(ctypes.windll.shcore, 'GetDpiForMonitor'):
                ctypes.windll.shcore.GetDpiForMonitor(monitor, win32con.MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), None)
                return dpi_x.value / 96.0

            # 3. 最终回退：系统全局DPI
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, win32con.LOGPIXELSX)
            ctypes.windll.user32.ReleaseDC(0, hdc)
            return dpi / 96.0
        except Exception as e:
            self.logger.error(f"获取DPI失败: {e}，默认DPI=1.0")
            return 1.0

    def _get_screen_hardware_res(self) -> Tuple[int, int]:
        """获取屏幕硬件分辨率（不受DPI影响，全屏游戏客户区即为此尺寸）"""
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        self.logger.debug(f"屏幕硬件分辨率: {screen_w}x{screen_h}（不受DPI影响）")
        return (screen_w, screen_h)
    
    def _get_screen_hardware_res(self) -> Tuple[int, int]:
        """
        获取物理屏幕分辨率（忽略系统DPI缩放，直接读取显示器原始分辨率）
        解决高DPI缩放（如125%）导致的分辨率被压缩问题
        """
        try:
            # 调用Windows API获取物理分辨率（绕过DPI缩放影响）
            import ctypes
            from ctypes import wintypes

            # 定义结构体
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
                    ("dmPelsWidth", wintypes.DWORD),   # 物理宽度
                    ("dmPelsHeight", wintypes.DWORD),  # 物理高度
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
            
            # 枚举主显示器设置（ENUM_CURRENT_SETTINGS = -1）
            result = ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(devmode))
            if result:
                screen_w = devmode.dmPelsWidth
                screen_h = devmode.dmPelsHeight
                self.logger.debug(f"物理屏幕分辨率（忽略DPI）: {screen_w}x{screen_h}")
                return (screen_w, screen_h)
            else:
                # 回退方案：使用系统API（可能受DPI影响）
                screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
                screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
                self.logger.warning(f"枚举显示器设置失败，使用回退方案: {screen_w}x{screen_h}")
                return (screen_w, screen_h)
        except Exception as e:
            self.logger.error(f"获取物理分辨率失败: {e}")
            # 最终回退
            return (1920, 1080)  # 强制使用你的基准分辨率

    def _update_window_info(self) -> bool:
        """
        完整窗口信息更新方法：
        - 全屏：识别DPI缩放后的视觉全屏，使用物理屏幕分辨率
        - 窗口：计算客户区逻辑尺寸（物理尺寸×DPI），排除标题栏，确保截图完整
        """
        if not self.hwnd:
            self.logger.error("无法更新窗口信息：窗口句柄不存在")
            return False

        try:
            # 1. 处理窗口最小化：确保非最小化状态，避免尺寸获取错误
            if self.is_minimized():
                self.logger.debug("检测到窗口最小化，执行恢复操作")
                self.restore_window()
                time.sleep(0.1)  # 等待窗口完全恢复渲染
                if self.is_minimized():
                    raise RuntimeError("窗口恢复失败，仍处于最小化状态")

            # 2. 获取核心基础参数
            # 2.1 窗口整体矩形（含标题栏/边框，屏幕坐标）
            self._window_rect = win32gui.GetWindowRect(self.hwnd)
            win_left, win_top, win_right, win_bottom = self._window_rect
            if win_left == 0 and win_top == 0 and win_right == 0 and win_bottom == 0:
                raise RuntimeError(f"获取窗口矩形失败，返回无效值: {self._window_rect}")

            # 2.2 当前窗口DPI缩放因子（如1.25=125%）
            self.dpi_scale = self._get_dpi_for_window()
            if self.dpi_scale <= 0:
                self.logger.warning(f"DPI缩放因子异常: {self.dpi_scale}，强制使用1.0")
                self.dpi_scale = 1.0

            # 2.3 物理屏幕分辨率（不受DPI影响，如1920×1080）
            physical_screen_w, physical_screen_h = self._get_screen_hardware_res()
            if physical_screen_w <= 0 or physical_screen_h <= 0:
                raise RuntimeError(f"获取物理屏幕分辨率失败: {physical_screen_w}x{physical_screen_h}")

            # 3. 计算辅助参数：系统缩放后的屏幕尺寸（用于视觉全屏判断）
            scaled_screen_w = int(physical_screen_w / self.dpi_scale)
            scaled_screen_h = int(physical_screen_h / self.dpi_scale)
            self.logger.debug(
                f"基础参数汇总 | "
                f"物理屏幕分辨率: {physical_screen_w}x{physical_screen_h} | "
                f"系统缩放后屏幕尺寸: {scaled_screen_w}x{scaled_screen_h}（DPI={self.dpi_scale:.2f}） | "
                f"窗口整体矩形: ({win_left},{win_top},{win_right},{win_bottom})"
            )

            # 4. 提取客户区参数：排除标题栏/边框，仅保留游戏内容区域
            # 4.1 客户区物理尺寸（系统缩放后，不含标题栏，如1168×656）
            client_rect_phys = win32gui.GetClientRect(self.hwnd)
            client_w_phys = client_rect_phys[2] - client_rect_phys[0]
            client_h_phys = client_rect_phys[3] - client_rect_phys[1]
            if client_w_phys <= 0 or client_h_phys <= 0:
                raise RuntimeError(f"获取客户区物理尺寸失败: {client_w_phys}x{client_h_phys}（可能窗口未渲染）")

            # 4.2 验证标题栏：通过窗口尺寸与客户区尺寸差值，确认标题栏已排除
            window_w_phys = win_right - win_left  # 含标题栏的窗口物理宽度
            window_h_phys = win_bottom - win_top  # 含标题栏的窗口物理高度
            title_bar_height = window_h_phys - client_h_phys  # 标题栏+边框高度（正常20-30px）
            border_width = (window_w_phys - client_w_phys) // 2  # 左右边框宽度（正常4-8px）
            self.logger.debug(
                f"客户区验证 | "
                f"窗口物理尺寸（含标题栏）: {window_w_phys}x{window_h_phys} | "
                f"客户区物理尺寸（无标题栏）: {client_w_phys}x{client_h_phys} | "
                f"标题栏高度估算: {title_bar_height}px | 边框宽度估算: {border_width}px"
            )
            # 合理性校验：排除异常值（如标题栏高度<0或>50px，可能客户区获取错误）
            if title_bar_height < 0 or title_bar_height > 50:
                self.logger.warning(
                    f"客户区尺寸异常：标题栏高度{title_bar_height}px（正常20-30px），"
                    f"可能包含标题栏，将重新尝试获取客户区"
                )
                # 重试客户区获取（避免临时渲染异常）
                time.sleep(0.05)
                client_rect_phys = win32gui.GetClientRect(self.hwnd)
                client_w_phys = client_rect_phys[2] - client_rect_phys[0]
                client_h_phys = client_rect_phys[3] - client_rect_phys[1]
                if client_w_phys <= 0 or client_h_phys <= 0:
                    raise RuntimeError("重试后仍无法获取有效客户区尺寸")

            # 5. 计算关键尺寸：窗口模式用逻辑尺寸，全屏用物理分辨率
            # 5.1 窗口模式：逻辑尺寸=客户区物理尺寸×DPI（游戏实际渲染尺寸，解决截不全）
            client_w_logic = int(round(client_w_phys * self.dpi_scale))
            client_h_logic = int(round(client_h_phys * self.dpi_scale))
            # 确保逻辑尺寸非零（避免极端DPI导致的异常）
            client_w_logic = max(800, client_w_logic)  # 最小800px宽，避免过小
            client_h_logic = max(600, client_h_logic)  # 最小600px高，避免过小

            # 5.2 全屏判断：结合物理尺寸和视觉全屏（解决DPI缩放后的全屏识别）
            # 无边界判定：窗口尺寸≈客户区尺寸（排除标题栏/边框，全屏时无边界）
            is_borderless = (abs(window_w_phys - client_w_phys) <= 2) and (abs(window_h_phys - client_h_phys) <= 2)
            # 视觉全屏判定：窗口对齐屏幕四角+无边界（即使尺寸是缩放后的值）
            is_visual_fullscreen = (
                win_left == 0 and win_top == 0  # 左上角对齐屏幕原点
                and abs(win_right - scaled_screen_w) <= 2  # 右边界对齐缩放后屏幕
                and abs(win_bottom - scaled_screen_h) <= 2  # 下边界对齐缩放后屏幕
                and is_borderless  # 无边界（排除普通窗口最大化）
            )
            # 最终全屏判定：要么尺寸=物理分辨率，要么是视觉全屏
            is_fullscreen = (
                # 物理全屏：窗口尺寸≈物理屏幕分辨率（无DPI缩放影响）
                (abs(window_w_phys - physical_screen_w) <= 2 and abs(window_h_phys - physical_screen_h) <= 2)
                or is_visual_fullscreen  # 视觉全屏：DPI缩放后的全屏
            )

            # 6. 同步客户区尺寸：区分全屏/窗口模式
            if is_fullscreen:
                self._client_size = (physical_screen_w, physical_screen_h)
                self.logger.debug(
                    f"全屏模式 | "
                    f"客户区尺寸设置为物理屏幕分辨率: {self._client_size} | "
                    f"视觉全屏: {is_visual_fullscreen} | 无边界: {is_borderless}"
                )
            else:
                self._client_size = (client_w_logic, client_h_logic)
                self.logger.debug(
                    f"窗口模式 | "
                    f"客户区尺寸设置为逻辑尺寸: {self._client_size}（物理尺寸{client_w_phys}x{client_h_phys}×DPI{self.dpi_scale}） | "
                    f"标题栏高度: {title_bar_height}px（已排除）"
                )

            # 7. 同步坐标转换器上下文：确保后续坐标转换基于当前有效尺寸
            if self.coord_transformer:
                self.coord_transformer.update_context(
                    client_size=self._client_size,
                    current_dpi=self.dpi_scale,
                    handle=self.hwnd
                )
                self.logger.debug(
                    f"坐标转换器上下文更新 | "
                    f"客户区尺寸: {self._client_size} | DPI: {self.dpi_scale:.2f} | 窗口句柄: {self.hwnd}"
                )

            # 8. 输出最终更新结果日志
            self.logger.debug(
                f"窗口信息更新完成 | "
                f"模式: {'全屏' if is_fullscreen else '窗口'} | "
                f"客户区尺寸: {self._client_size} | "
                f"DPI缩放: {self.dpi_scale:.2f} | "
                f"窗口位置: ({win_left},{win_top},{win_right},{win_bottom}) | "
                f"标题栏排除状态: {'已排除' if title_bar_height > 0 else '无需排除'}"
            )
            return True

        except Exception as e:
            self.last_error = f"窗口信息更新失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            # 异常时设置默认尺寸，避免后续崩溃
            self._client_size = (1920, 1080)
            self.logger.warning(f"异常降级：客户区尺寸设置为默认1920×1080")
            return False
    @property
    def client_size(self) -> Tuple[int, int]:
        """获取当前客户区尺寸（供外部调用）"""
        return self._client_size

    def connect(self, timeout: float = 10.0) -> bool:
        """连接到Windows窗口（超时重试）"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            self.hwnd = self._get_window_handle()
            if self.hwnd:
                # 激活窗口并更新信息
                self.restore_window()
                self.set_foreground()
                time.sleep(0.5)
                if self._update_window_info():
                    self.state = DeviceState.CONNECTED
                    self.logger.info(
                        f"已连接到Windows窗口: {self.window_title}（句柄: {self.hwnd}）"
                    )
                    return True
            time.sleep(0.5)

        self.last_error = f"超时未找到匹配窗口（{timeout}s）"
        self.state = DeviceState.DISCONNECTED
        self.logger.error(f"连接失败: {self.last_error}")
        return False

    def disconnect(self) -> bool:
        """断开连接（重置窗口信息）"""
        if self.hwnd:
            self.logger.info(f"断开与窗口的连接: {self.window_title}（句柄: {self.hwnd}）")
            self.hwnd = None
            self.window_title = ""
            self._client_size = (0, 0)
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
            self._update_window_info()
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
            win32gui.ShowWindow(self.hwnd, win32con.SW_MAXIMIZE)
            time.sleep(self.WINDOW_RESTORE_DELAY)
            self._update_window_info()
            self.logger.info(f"窗口已最大化: {self.window_title}")
            return True
        except Exception as e:
            self.last_error = f"最大化窗口失败: {str(e)}"
            self.logger.error(self.last_error)
            return False

    def set_foreground(self) -> bool:
        """激活并置前窗口（恢复旧版验证有效的逻辑）"""
        if not self.hwnd:
            self.last_error = f"未连接到窗口或状态异常: {self.hwnd}|{self.state}"
            return False

        try:
            # 强制更新窗口状态
            self._update_window_info()
            
            # 如果窗口最小化，先恢复
            if self.is_minimized():
                self.logger.info("检测到窗口最小化，正在恢复...")
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                time.sleep(self.WINDOW_RESTORE_DELAY)  # 等待窗口恢复
                self._update_window_info()  # 再次更新状态
            
            # 直接激活窗口（旧版验证有效的方式）
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
            result = win32gui.SetForegroundWindow(self.hwnd)
            
            # 检查是否真的激活了
            time.sleep(self.WINDOW_ACTIVATE_DELAY)
            foreground_window = win32gui.GetForegroundWindow()
            
            if foreground_window == self.hwnd and not self.is_minimized():
                # self.logger.info("窗口激活成功")
                return True
            else:
                # 尝试降级方案：发送ALT键事件绕过限制
                self.logger.warning("尝试降级方案激活窗口...")
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)  # 按下ALT
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)  # 释放ALT
                time.sleep(0.1)
                win32gui.SetForegroundWindow(self.hwnd)
                time.sleep(self.WINDOW_ACTIVATE_DELAY)
                
                # 再次检查
                if win32gui.GetForegroundWindow() == self.hwnd:
                    self.logger.info("降级方案激活窗口成功")
                    return True
                
                self.logger.error(
                    f"窗口激活失败: 前景窗口={foreground_window}, "
                    f"目标窗口={self.hwnd}, 最小化={self.is_minimized()}"
                )
                return False
                
        except Exception as e:
            error_msg = f"窗口置前失败: {str(e)}"
            self.logger.error(error_msg)
            self.last_error = error_msg
            return False


    def get_resolution(self) -> Tuple[int, int]:
        """获取当前客户区分辨率（与client_size一致，供外部兼容调用）"""
        return self._client_size

    def capture_screen(self, roi: Optional[Tuple[int, int, int, int]] = None) -> Optional[np.ndarray]:
        """
        修复窗口标题栏问题：仅截取客户区，排除标题栏/边框
        """
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return None

        try:
            # 1. 确保窗口激活且非最小化
            if self.is_minimized():
                self.restore_window()
            if not self.set_foreground():
                raise RuntimeError("窗口激活失败，无法截图")
            time.sleep(0.1)  # 等待游戏渲染完成

            # 2. 确定截图尺寸（全屏=物理分辨率，窗口=客户区逻辑尺寸）
            is_fullscreen = self.coord_transformer._is_current_window_fullscreen(self.hwnd)
            physical_screen_w, physical_screen_h = self._get_screen_hardware_res()

            if is_fullscreen:
                cap_w, cap_h = physical_screen_w, physical_screen_h
                self.logger.debug(f"全屏模式 | 按物理屏幕分辨率 {cap_w}x{cap_h} 截图")
            else:
                # 窗口模式：严格使用客户区逻辑尺寸（已排除标题栏）
                cap_w, cap_h = self._client_size
                self.logger.debug(f"窗口模式 | 按客户区逻辑尺寸 {cap_w}x{cap_h} 截图（仅客户区，无标题栏）")

            # 3. 关键修复：仅截取客户区（客户区DC + PW_CLIENTONLY标志）
            with DCHandle(self.hwnd,self.logger) as hwndDC:  # 此时hwndDC是客户区DC，无标题栏
                # 创建与客户区DC兼容的位图（尺寸=客户区逻辑尺寸）
                mfcDC = win32ui.CreateDCFromHandle(hwndDC)
                saveDC = mfcDC.CreateCompatibleDC()
                saveBitMap = win32ui.CreateBitmap()
                # 严格按客户区尺寸创建位图，避免多余区域
                saveBitMap.CreateCompatibleBitmap(mfcDC, cap_w, cap_h)
                saveDC.SelectObject(saveBitMap)

                # 强制使用PW_CLIENTONLY（0x2）：仅渲染客户区，过滤标题栏/边框
                print_flag = 0x00000002  # 此标志优先级最高，确保只截客户区
                result = ctypes.windll.user32.PrintWindow(self.hwnd, saveDC.GetSafeHdc(), print_flag)
                if result != 1:
                    raise RuntimeError(f"PrintWindow截取客户区失败 | 返回值: {result}，标志: {print_flag}（仅客户区）")
                self.logger.debug(f"PrintWindow成功 | 仅截取客户区（标志: {print_flag}），截图尺寸: {cap_w}x{cap_h}")

                # 4. 转换为numpy数组（无标题栏，纯客户区内容）
                bmpinfo = saveBitMap.GetInfo()
                bmpstr = saveBitMap.GetBitmapBits(True)
                # 确保图像尺寸与客户区一致，避免拉伸
                im = Image.frombuffer(
                    'RGB',
                    (cap_w, cap_h),  # 客户区尺寸，无标题栏
                    bmpstr, 'raw', 'BGRX', 0, 1
                )
                img_np = np.array(im)

                # 5. 清理资源
                saveDC.DeleteDC()
                mfcDC.DeleteDC()
                win32gui.DeleteObject(saveBitMap.GetHandle())

            # 6. 处理ROI（基于纯客户区图像）
            if roi:
                rx, ry, rw, rh = roi
                if rx < 0 or ry < 0 or rx + rw > cap_w or ry + rh > cap_h:
                    self.logger.warning(
                        f"ROI超出客户区范围 | ROI: {roi} | 客户区尺寸: {cap_w}x{cap_h} | 已忽略ROI"
                    )
                else:
                    img_np = img_np[ry:ry+rh, rx:rx+rw]
                    self.logger.debug(f"应用ROI | 截取后尺寸: {rw}x{rh}（纯客户区）")

            # 转换为OpenCV的BGR格式
            return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        except Exception as e:
            self.last_error = f"截图失败（仅客户区）: {str(e)}"
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
        """
        鼠标点击操作：修复DPI缩放导致的坐标偏移（核心修正）
        """
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return False

        try:
            # 确保窗口在前台
            self.restore_window()
            self.set_foreground()
            time.sleep(0.1)

            # 解析点击位置（模板匹配/直接坐标）
            target_pos: Optional[Tuple[int, int]] = None
            if isinstance(pos, str):
                # 模板匹配模式（逻辑与之前一致）
                if not self.image_processor:
                    self.last_error = "未设置图像处理器，无法模板匹配"
                    return False

                screen = self.capture_screen()
                if screen is None:
                    self.last_error = "截图失败，无法模板匹配"
                    return False

                match_result = self.image_processor.match_template(
                    image=screen,  # 待匹配截图（客户区，无标题栏）
                    template=pos,  # 模板名称（pos 是传入的模板名）
                    current_dpi=self.dpi_scale,  # 当前窗口的 DPI 缩放因子（已实时更新）
                    hwnd=self.hwnd,  # 窗口句柄（用于判断全屏状态）
                    physical_screen_res=self._get_screen_hardware_res(),  # 物理屏幕分辨率（全屏时必用）
                    threshold=0.6  # 保持默认阈值，与原逻辑一致（也可按需调整）
                )
                if match_result is None:
                    self.last_error = f"模板匹配失败: {pos}"
                    return False

                # 转换匹配结果为矩形并计算中心点
                if isinstance(match_result, np.ndarray):
                    match_rect = tuple(match_result.tolist())
                else:
                    match_rect = tuple(match_result)
                if len(match_rect) != 4:
                    self.last_error = f"模板结果格式错误: {match_rect}（需4元素矩形），模板: {pos}"
                    return False

                target_pos = self.image_processor.get_center(match_rect)
                if isinstance(target_pos, (list, np.ndarray)):
                    target_pos = tuple(map(int, target_pos))
                if not isinstance(target_pos, tuple) or len(target_pos) != 2:
                    self.last_error = f"中心点计算失败: {target_pos}，模板: {pos}"
                    return False
                target_pos = (int(target_pos[0]), int(target_pos[1]))
                self.logger.debug(f"模板 {pos} 中心点坐标: {target_pos}（逻辑坐标）")

                is_base_coord = False
            else:
                # 直接坐标模式（确保整数）
                target_pos = tuple(map(int, pos))

            # 校验目标坐标
            if not target_pos or len(target_pos) != 2:
                self.last_error = f"无效的点击位置: {target_pos}"
                return False

            # 坐标转换：原始基准坐标 → 当前客户区坐标
            client_pos = target_pos
            if is_base_coord and self.coord_transformer:
                client_pos = self.coord_transformer.convert_original_to_current_client(*target_pos)
                self.logger.debug(f"原始坐标 {target_pos} → 当前客户区坐标 {client_pos}（逻辑坐标）")

            # 客户区逻辑坐标转屏幕物理坐标
            screen_physical_x, screen_physical_y = self.coord_transformer.convert_current_client_to_screen(*client_pos)

            # 执行点击
            win32api.SetCursorPos((screen_physical_x, screen_physical_y))
            time.sleep(0.1)  # 延长等待，确保移动到位

            # 发送点击事件
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
        """
        鼠标滑动操作：
        - is_base_coord：起始/结束坐标是否为原始基准坐标
        """
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return False

        try:
            # 确保窗口在前台
            self.restore_window()
            self.set_foreground()
            time.sleep(0.1)

            # 坐标转换：原始基准 → 当前客户区
            start_pos = (start_x, start_y)
            end_pos = (end_x, end_y)
            if is_base_coord and self.coord_transformer:
                start_pos = self.coord_transformer.convert_original_to_current_client(*start_pos)
                end_pos = self.coord_transformer.convert_original_to_current_client(*end_pos)
                self.logger.debug(f"滑动坐标转换: {start_pos} → {end_pos}")

            # 客户区坐标 → 屏幕坐标
            screen_start = win32gui.ClientToScreen(self.hwnd, start_pos)
            screen_end = win32gui.ClientToScreen(self.hwnd, end_pos)
            self.logger.debug(f"滑动屏幕坐标: {screen_start} → {screen_end}")

            # 计算每步移动参数
            step_x = (screen_end[0] - screen_start[0]) / steps
            step_y = (screen_end[1] - screen_start[1]) / steps
            step_delay = duration / steps

            # 执行滑动
            win32api.SetCursorPos(screen_start)
            time.sleep(0.1)
            # 按下鼠标左键
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            # 分步移动
            for i in range(1, steps + 1):
                x = int(round(screen_start[0] + step_x * i))
                y = int(round(screen_start[1] + step_y * i))
                win32api.SetCursorPos((x, y))
                time.sleep(step_delay)
            # 释放鼠标左键
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
        """按键操作（使用pydirectinput，兼容游戏）"""
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return False

        try:
            self.restore_window()
            self.set_foreground()
            time.sleep(0.1)  # 等待窗口获取焦点

            # 按下并释放按键
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
        """文本输入（长文本用粘贴，短文本逐字符输入）"""
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return False

        try:
            self.restore_window()
            self.set_foreground()
            time.sleep(0.1)

            # 长文本（>5字符）用粘贴（更高效）
            if len(text) > 5:
                import pyperclip
                pyperclip.copy(text)
                # 模拟Ctrl+V
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                win32api.keybd_event(ord('V'), 0, 0, 0)
                time.sleep(0.05)
                win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(0.1)
                self.logger.debug(f"文本粘贴成功: {text[:20]}...（长度: {len(text)}）")
                return True

            # 短文本逐字符输入
            for char in text:
                if char == ' ':
                    self.key_press("space", 0.02)
                elif char == '\n':
                    self.key_press("enter", 0.02)
                elif char == '\t':
                    self.key_press("tab", 0.02)
                else:
                    # 处理大小写和特殊字符（需Shift）
                    shift_pressed = char.isupper() or char in '~!@#$%^&*()_+{}|:"<>?'
                    if shift_pressed:
                        win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
                    # 按下字符键（统一转大写，Shift已处理大小写）
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
        """
        检查模板是否存在：返回中心点坐标，不存在则返回None
        :return: 中心点坐标或None
        """
        try:
            if not self.hwnd:
                self.last_error = "未连接到窗口"
                return None

            self.set_foreground()
            if not self.image_processor:
                self.last_error = "未设置图像处理器"
                return None

            # 1. 截图并匹配模板
            screen = self.capture_screen()
            if screen is None:
                self.logger.debug(f"截图为空，无法检查模板: {template_name}")
                return None

            self.logger.debug(f"检查模板: {template_name}（阈值: {threshold}）")
            match_result = self.image_processor.match_template(
                image=screen,  # 待匹配截图（客户区，无标题栏）
                template=template_name,  # 待检查的模板名称
                current_dpi=self.dpi_scale,  # 当前窗口 DPI 缩放因子
                hwnd=self.hwnd,  # 窗口句柄（判断全屏）
                threshold=threshold,  # 传入的匹配阈值（原逻辑保留）
                physical_screen_res=self._get_screen_hardware_res()  # 物理屏幕分辨率
            )

            # 2. 模板不存在的情况
            if match_result is None:
                self.logger.debug(f"模板未找到: {template_name}")
                return None

            # 3. 模板存在：计算并返回中心点
            # 确保匹配结果为标准矩形
            if isinstance(match_result, np.ndarray):
                match_rect = tuple(match_result.tolist())
            else:
                match_rect = tuple(match_result)
            if len(match_rect) != 4:
                self.logger.warning(f"模板结果格式无效: {match_rect}，模板: {template_name}")
                return None  # 存在但格式错误，返回空坐标

            # 关键：调用get_center获取中心点
            center_pos = self.image_processor.get_center(match_rect)
            if isinstance(center_pos, (list, np.ndarray)):
                center_pos = tuple(map(int, center_pos))
            # 校验中心点有效性
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
        """
        等待模板出现：返回中心点坐标，超时则返回None
        :return: 中心点坐标或None
        """
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
        """获取设备状态（CONNECTED/DISCONNECTED/INVISIBLE/ERROR）"""
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
        """设备睡眠（等待指定时间）"""
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