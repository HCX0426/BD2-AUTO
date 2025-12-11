import ctypes
import time
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import pydirectinput
import win32api
import win32con
import win32gui
import win32process
import win32ui
from PIL import Image

from src.auto_control.devices.base_device import BaseDevice, DeviceState
from src.auto_control.until.coordinate_transformer import CoordinateTransformer
from src.auto_control.image.image_processor import ImageProcessor


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
    WINDOW_RESTORE_DELAY = 0.5  # 窗口恢复后的等待时间
    WINDOW_ACTIVATE_DELAY = 0.1  # 窗口激活后的验证等待时间
    ACTIVATE_COOLDOWN = 5.0  # 激活冷却时间（5秒内不重复激活）
    FOREGROUND_CHECK_INTERVAL = 5.0 # 新增：前台检查间隔

    def __init__(
            self,
            device_uri: str,
            logger=None,
            image_processor: Optional[ImageProcessor] = None,
            coord_transformer: Optional[CoordinateTransformer] = None,
    ):
        super().__init__(device_uri)
        self.logger = logger
        self.device_uri = device_uri
        self.image_processor: ImageProcessor = image_processor
        self.coord_transformer: CoordinateTransformer = coord_transformer

        # 窗口基础信息（连接时初始化，稳定属性）
        self.hwnd: Optional[int] = None  # 窗口句柄
        self.window_title: str = ""  # 窗口标题
        self.window_class: str = ""  # 窗口类名（如UnityWndClass）
        self.process_id: int = 0  # 窗口所属进程ID
        self.physical_screen_res: Tuple[int, int] = (0, 0)  # 物理屏幕分辨率（稳定值）

        # 窗口动态信息（状态变化时更新）
        self._client_size: Tuple[int, int] = (0, 0)  # 客户区大小
        self.dpi_scale: float = 1.0  # 当前窗口DPI缩放因子
        self._window_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)  # 窗口矩形
        self.is_fullscreen: bool = False  # 是否全屏（动态变化）

        # 激活状态缓存
        self._last_activate_time = 0.0  # 上次激活时间（秒级时间戳）
        
        # 控制前台激活行为的标志
        self._foreground_activation_allowed = True # 是否允许尝试将窗口激活到前台

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
        
        # 按优先级尝试不同查找方式
        strategies = [
            ("精确标题", lambda: self.uri_params.get("title") and win32gui.FindWindow(None, self.uri_params["title"])),
            ("正则标题", self._find_by_title_regex),
            ("进程名", lambda: self._find_window_by_process_name("BrownDust2")),
            ("类名", lambda: win32gui.FindWindow("UnityWndClass", None)),
        ]
        
        for name, strategy in strategies:
            self.logger.info(f"尝试通过{name}查找窗口...")
            hwnd = strategy()
            if hwnd:
                # 获取窗口标题
                title = win32gui.GetWindowText(hwnd)
                self.window_title = title
                self.logger.info(f"通过{name}找到窗口: {title}, 句柄: {hwnd}")
                return hwnd
        
        self.logger.error("未找到匹配的窗口")
        return None

    def _find_by_title_regex(self) -> Optional[int]:
        """通过正则表达式查找窗口标题"""
        if "title_re" not in self.uri_params:
            return None
        
        import re
        pattern_str = self.uri_params["title_re"]
        # 处理通配符
        if '*' in pattern_str and not (pattern_str.startswith('.*') or pattern_str.endswith('.*')):
            pattern_str = pattern_str.replace('*', '.*')
        
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
        except re.error as e:
            self.logger.error(f"正则表达式编译错误: {e}")
            return None
        
        def callback(hwnd, ctx):
            title = win32gui.GetWindowText(hwnd)
            if title and pattern.search(title):
                ctx.append(hwnd)  # 找到就添加到列表
                return False  # 停止枚举，只找第一个
            return True
        
        results = []
        win32gui.EnumWindows(callback, results)
        return results[0] if results else None
    def _find_window_by_process_name(self, process_name: str) -> Optional[int]:
        """通过进程名查找窗口"""
        try:
            import psutil
            for proc in psutil.process_iter(['name', 'pid']):
                if proc.info['name'].lower() == process_name.lower():
                    pid = proc.info['pid']
                    self.logger.info(f"找到进程: {process_name}, PID: {pid}")
                    
                    def find_window_by_pid(hwnd, pid_list):
                        _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                        if found_pid == pid_list[0] and win32gui.GetWindowText(hwnd):
                            pid_list.append(hwnd)  # 找到就添加
                            return False  # 停止枚举
                        return True
                    
                    results = [pid]  # 用列表传递PID
                    win32gui.EnumWindows(find_window_by_pid, results)
                    if len(results) > 1:  # 找到了窗口句柄
                        self.logger.info(f"找到进程窗口: 句柄={results[1]}")
                        return results[1]
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
            # 最现代的方法（Windows 10+）
            if hasattr(ctypes.windll.user32, 'GetDpiForWindow'):
                dpi = ctypes.windll.user32.GetDpiForWindow(self.hwnd)
                if dpi > 0:
                    return dpi / 96.0
            
            # 回退：获取系统DPI
            dpi = ctypes.windll.user32.GetDpiForSystem()
            return dpi / 96.0
            
        except Exception as e:
            self.logger.error(f"获取DPI失败: {e}，默认DPI=1.0")
            return 1.0

    def _get_screen_hardware_res(self) -> Tuple[int, int]:
        """获取物理屏幕分辨率（仅在connect时调用一次，后续复用缓存）"""
        try:
            # 直接获取系统指标
            screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            self.logger.debug(f"获取屏幕分辨率: {screen_w}x{screen_h}")
            return (screen_w, screen_h)
        except Exception as e:
            self.logger.error(f"获取屏幕分辨率失败: {e}")
            return (1920, 1080)  # 默认值

    def _update_dynamic_window_info(self) -> bool:
        """更新动态窗口信息（客户区大小、DPI、窗口位置等）"""
        if not self.hwnd:
            self.logger.error("无法更新窗口信息：窗口句柄不存在")
            return False

        try:
            if self.is_minimized():
                self.logger.debug("窗口处于最小化状态，跳过动态信息更新")
                return False

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

            # --- 正确的计算：将物理尺寸转换为逻辑尺寸 ---
            client_w_logic = int(round(client_w_phys / self.dpi_scale)) # 正确：物理 / DPI = 逻辑
            client_h_logic = int(round(client_h_phys / self.dpi_scale)) # 正确：物理 / DPI = 逻辑
            client_w_logic = max(800, client_w_logic)
            client_h_logic = max(600, client_h_logic)
            # --- 结束修正 ---

            # 使用坐标转换器判断是否全屏
            if self.coord_transformer:
                self.is_fullscreen = self.coord_transformer._is_current_window_fullscreen(self.hwnd)
            else:
                # 备用方案：如果没有坐标转换器，使用简单判断
                is_borderless = (abs(window_w_phys - client_w_phys) <= 2) and (
                    abs(window_h_phys - client_h_phys) <= 2)
                is_visual_fullscreen = (
                    win_left == 0 and win_top == 0 and abs(win_right - scaled_screen_w) <= 2 and abs(
                        win_bottom - scaled_screen_h) <= 2 and is_borderless)
                self.is_fullscreen = is_visual_fullscreen
                self.logger.warning("未使用坐标转换器判断全屏状态，可能存在误差")

            # 更新客户区尺寸 (存储逻辑尺寸)
            self._client_size = (self.physical_screen_res if self.is_fullscreen else (client_w_logic, client_h_logic))

            # 更新坐标转换器 (传递逻辑尺寸)
            if self.coord_transformer:
                self.coord_transformer.update_context(
                    client_size=self._client_size, # 传递逻辑尺寸
                    current_dpi=self.dpi_scale,
                    handle=self.hwnd
                )
            self.logger.debug(
                f"动态信息更新完成 | 模式: {'全屏' if self.is_fullscreen else '窗口'} | "
                f"客户区尺寸 (逻辑): {self._client_size} | DPI: {self.dpi_scale:.2f}"
            )
            return True
        except Exception as e:
            self.last_error = f"动态窗口信息更新失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            # 即使出错，也应该提供一个合理的默认值，或者让调用者知道状态无效
            # self._client_size = (1920, 1080) # 或许可以保留，或许应该设为 (0, 0)?
            return False # 返回 False 更能反映更新失败的状态


    def connect(self, timeout: float = 10.0) -> bool:
        """连接到Windows窗口，初始化并缓存稳定属性"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            self.hwnd = self._get_window_handle()
            if self.hwnd:
                # 缓存稳定属性（仅连接时计算一次）
                self.physical_screen_res = self._get_screen_hardware_res()  # 物理屏幕分辨率（稳定）
                self.window_class = win32gui.GetClassName(self.hwnd)  # 窗口类名（稳定）
                _, self.process_id = win32process.GetWindowThreadProcessId(self.hwnd)  # 进程ID（稳定）

                self.set_foreground()
                time.sleep(0.5)

                # 检查窗口是否有效连接
                if self.hwnd and win32gui.IsWindow(self.hwnd) and win32gui.IsWindowVisible(self.hwnd):
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
            self._foreground_activation_allowed = True # 重置前台激活标志
            self.state = DeviceState.DISCONNECTED
            return True
        return False

    def is_minimized(self) -> bool:
        """检查窗口是否最小化"""
        if not self.hwnd:
            return True
        return win32gui.IsIconic(self.hwnd)

    def set_foreground(self) -> bool:
        """
        窗口激活逻辑：首次调用时可以尝试激活，之后如果不在前台则循环等待。
        """
        if not self.hwnd:
            self.last_error = f"未连接到窗口或状态异常: {self.hwnd}|{self.state}"
            return False

        current_time = time.time()
        
        # 1. 前台验证：当前前台窗口就是目标窗口，无需激活
        foreground_hwnd = win32gui.GetForegroundWindow()
        if foreground_hwnd == self.hwnd:
            self._last_activate_time = current_time  # 更新激活时间（刷新冷却）
            self.logger.debug(f"窗口已在前台 | 句柄: {self.hwnd} | 无需激活")
            # 激活成功，更新动态信息（可能有状态变化）
            self._update_dynamic_window_info()
            return True

        # 2. 如果允许激活（通常是首次）
        if self._foreground_activation_allowed:
            self.logger.info(f"首次尝试将窗口激活到前台 | 句柄: {self.hwnd}")
            # --- 简化的激活逻辑 ---
            try:
                # 先恢复窗口（防止最小化导致激活无效）
                if self.is_minimized():  # 这里保留最小化检查
                    self.logger.info("检测到窗口最小化，先恢复...")
                    win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                    time.sleep(self.WINDOW_RESTORE_DELAY)
                    # 恢复后立即检查是否已经在前台
                    foreground_hwnd = win32gui.GetForegroundWindow()
                    if foreground_hwnd == self.hwnd:
                        self._last_activate_time = current_time
                        self._foreground_activation_allowed = False # 成功激活后禁止后续自动激活
                        self.logger.info(f"窗口恢复后自动激活成功 | 句柄: {self.hwnd}")
                        # 恢复成功，更新动态信息
                        self._update_dynamic_window_info()
                        return True

                # 尝试标准激活方法
                win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
                success = win32gui.SetForegroundWindow(self.hwnd)
                
                time.sleep(self.WINDOW_ACTIVATE_DELAY)
                final_foreground = win32gui.GetForegroundWindow()
                
                if success and final_foreground == self.hwnd and not self.is_minimized():
                    self._last_activate_time = current_time
                    self._foreground_activation_allowed = False # 成功激活后禁止后续自动激活
                    self.logger.info(f"窗口激活成功 | 句柄: {self.hwnd}")
                    # 激活成功，更新动态信息
                    self._update_dynamic_window_info()
                    return True
                else:
                    self.logger.warning(f"窗口激活尝试失败 | 句柄: {self.hwnd}")
            except Exception as e:
                self.logger.error(f"窗口激活尝试异常: {str(e)} | 句柄: {self.hwnd}")
            # --- 激活逻辑结束 ---
            
            # 如果激活尝试失败，也禁止后续自动激活，并进入等待循环
            self._foreground_activation_allowed = False
            self.logger.warning(f"首次窗口激活失败，进入前台检查等待循环 | 句柄: {self.hwnd}")

        # 3. 如果不允许激活或激活失败，则进入循环等待
        self.logger.info(f"窗口不在前台，进入等待循环，每 {self.FOREGROUND_CHECK_INTERVAL} 秒检查一次 | 句柄: {self.hwnd}")
        while True:
            time.sleep(self.FOREGROUND_CHECK_INTERVAL)
            try:
                foreground_hwnd = win32gui.GetForegroundWindow()
                if foreground_hwnd == self.hwnd:
                    self.logger.info(f"检测到窗口回到前台，退出等待循环 | 句柄: {self.hwnd}")
                    # 窗口回到前台，更新动态信息
                    self._update_dynamic_window_info()
                    return True
                else:
                    self.logger.debug(f"窗口仍未在前台，继续等待 | 句柄: {self.hwnd}")
            except Exception as e:
                self.logger.error(f"检查前台窗口时出错: {e}")
                continue
        # 理论上不会执行到这里
        return False


    def _activate_with_standard_method(self) -> bool:
        """标准激活方法：使用ShowWindow + SetForegroundWindow"""
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        return win32gui.SetForegroundWindow(self.hwnd)

    def _activate_with_thread_attach(self) -> bool:
        """高级激活方法：使用AttachThreadInput绕过Windows前台限制"""
        # 获取当前线程ID和目标窗口线程ID
        current_thread_id = win32api.GetCurrentThreadId()
        target_thread_id, _ = win32process.GetWindowThreadProcessId(self.hwnd)
        # 如果线程ID相同，直接激活
        if current_thread_id == target_thread_id:
            return self._activate_with_standard_method()
        # 否则，附加线程输入上下文
        try:
            win32process.AttachThreadInput(current_thread_id, target_thread_id, True)
            result = self._activate_with_standard_method()
            return result
        finally:
            # 无论如何都要分离线程输入上下文
            try:
                win32process.AttachThreadInput(current_thread_id, target_thread_id, False)
            except Exception as e:
                self.logger.debug(f"分离线程输入上下文异常: {str(e)}")

    def _optimized_minimize_restore(self) -> bool:
        """优化版最小化恢复方法：减少不必要的状态切换"""
        # 只在其他方法都失败时才使用
        try:
            # 尝试不经过最小化直接激活
            if self._activate_with_standard_method():
                return True
            # 作为最后的备选方案，再尝试最小化恢复（但减少延迟）
            win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
            time.sleep(self.WINDOW_RESTORE_DELAY / 2)  # 减少延迟
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            time.sleep(self.WINDOW_RESTORE_DELAY / 2)  # 减少延迟
            return self._activate_with_standard_method()
        except:
            return False

    def get_resolution(self) -> Tuple[int, int]:
        """获取当前客户区分辨率"""
        return self._client_size

    def capture_screen(self, roi: Optional[Tuple[int, int, int, int]] = None) -> Optional[np.ndarray]:
        """
        截取窗口客户区屏幕（彻底排除标题栏/边框，窗口模式精准裁剪）
        Args:
            roi: 可选，基于原始全屏物理像素定义的ROI，格式 (x, y, width, height)。
                 注意：这里的(x,y)是相对于原始全屏左上角(0,0)的物理坐标。
        Returns:
            截取的图像（BGR格式），None表示失败
        """
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return None
        try:
            time.sleep(0.1)

            # ========== 1. 基础尺寸/位置获取 ==========
            # 获取窗口整体在屏幕上的矩形（包含标题栏/边框）
            window_rect = win32gui.GetWindowRect(self.hwnd)
            win_left, win_top, win_right, win_bottom = window_rect
            window_w = win_right - win_left
            window_h = win_bottom - win_top

            # 获取客户区相对窗口的偏移（关键：标题栏/边框的宽度）
            client_rect = win32gui.GetClientRect(self.hwnd)
            client_w_phys = client_rect[2] - client_rect[0]  # 客户区物理宽度
            client_h_phys = client_rect[3] - client_rect[1]  # 客户区物理高度
            if client_w_phys <= 0 or client_h_phys <= 0:
                raise RuntimeError(f"客户区物理尺寸无效: {client_w_phys}x{client_h_phys}")

            # 计算客户区相对屏幕的真实位置（排除标题栏/边框）
            # 方法：通过ClientToScreen转换客户区左上角(0,0)到屏幕坐标
            client_screen_x, client_screen_y = win32gui.ClientToScreen(self.hwnd, (0, 0))

            # 验证：标题栏高度 = 客户区Y偏移 - 窗口顶部Y
            title_bar_height = client_screen_y - win_top
            border_left = client_screen_x - win_left
            self.logger.debug(
                f"窗口位置: ({win_left},{win_top})-{window_w}x{window_h} | "
                f"客户区偏移: 左={border_left}px, 上={title_bar_height}px | "
                f"客户区物理尺寸: {client_w_phys}x{client_h_phys}"
            )

            # ========== 2. 区分全屏/窗口模式 ==========
            if self.is_fullscreen:
                # 全屏模式：保留原有逻辑
                cap_w, cap_h = self.physical_screen_res  # 截图尺寸等于物理屏幕分辨率
                self.logger.debug(f"全屏模式 | 截图尺寸: {cap_w}x{cap_h}")
                # 全屏模式直接截取屏幕
                hdc_screen = win32gui.GetDC(0)
                mfcDC = win32ui.CreateDCFromHandle(hdc_screen)
                saveDC = mfcDC.CreateCompatibleDC()
                saveBitMap = win32ui.CreateBitmap()
                saveBitMap.CreateCompatibleBitmap(mfcDC, cap_w, cap_h)
                saveDC.SelectObject(saveBitMap)
                # BitBlt截取整个屏幕
                ctypes.windll.gdi32.BitBlt(
                    saveDC.GetSafeHdc(), 0, 0, cap_w, cap_h, hdc_screen, 0, 0, win32con.SRCCOPY
                )
            else:
                # 窗口模式：精准截取客户区（核心修复）
                cap_w, cap_h = client_w_phys, client_h_phys  # 截图尺寸等于客户区物理尺寸
                self.logger.debug(f"窗口模式 | 客户区物理尺寸: {cap_w}x{cap_h}")
                # 截取屏幕上的客户区范围（避开标题栏/边框）
                hdc_screen = win32gui.GetDC(0)
                mfcDC = win32ui.CreateDCFromHandle(hdc_screen)
                saveDC = mfcDC.CreateCompatibleDC()
                saveBitMap = win32ui.CreateBitmap()
                saveBitMap.CreateCompatibleBitmap(mfcDC, cap_w, cap_h)
                saveDC.SelectObject(saveBitMap)
                # BitBlt：只截取屏幕上的客户区部分（排除标题栏/边框）
                ctypes.windll.gdi32.BitBlt(
                    saveDC.GetSafeHdc(), 0, 0, cap_w, cap_h,  # 目标位图尺寸（客户区）
                    hdc_screen, client_screen_x, client_screen_y,  # 屏幕上的客户区左上角
                    win32con.SRCCOPY
                )

            # ========== 3. 位图转numpy数组 ==========
            bmpstr = saveBitMap.GetBitmapBits(True)
            im = Image.frombuffer(
                'RGB', (cap_w, cap_h), bmpstr, 'raw', 'BGRX', 0, 1
            )
            img_np = np.array(im)
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            # ========== 4. 资源释放 ==========
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.DeleteObject(saveBitMap.GetHandle())
            win32gui.ReleaseDC(0, hdc_screen)

            # ========== 5. ROI裁剪（统一处理：基于原始全屏物理坐标） ==========
            # 核心思想：无论全屏还是窗口，传入的roi都是基于原始全屏物理分辨率定义的。
            # 全屏模式下，截图就是全屏，roi可以直接应用。
            # 窗口模式下，需要将roi转换到当前客户区的坐标系下进行裁剪。
            if roi:
                roi_x, roi_y, roi_w, roi_h = roi
                if self.is_fullscreen:
                    # 全屏模式：ROI直接用物理像素（和原逻辑一致）
                    if roi_x < 0 or roi_y < 0 or roi_x + roi_w > cap_w or roi_y + roi_h > cap_h:
                        self.logger.warning(f"ROI超出全屏范围 | ROI: {roi} | 忽略ROI")
                    else:
                        img_np = img_np[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
                        self.logger.debug(f"全屏模式裁剪ROI: {roi}")
                else:
                    # 窗口模式：将基于原始全屏物理坐标的ROI，转换为客户区内物理坐标的裁剪区域
                    if not self.coord_transformer:
                        self.logger.warning("窗口模式下裁剪ROI需要CoordinateTransformer，但未提供。忽略ROI。")
                    else:
                        # 1. 将ROI的两个对角顶点从原始坐标系转换到当前客户区坐标系（逻辑坐标）
                        top_left_logical = self.coord_transformer.convert_original_to_current_client(roi_x, roi_y)
                        bottom_right_logical = self.coord_transformer.convert_original_to_current_client(roi_x + roi_w,
                                                                                                       roi_y + roi_h)
                        # 2. 将逻辑坐标转换为客户区内的物理坐标（考虑当前DPI缩放）
                        top_left_physical = (
                            int(round(top_left_logical[0] / self.dpi_scale)),
                            int(round(top_left_logical[1] / self.dpi_scale))
                        )
                        bottom_right_physical = (
                            int(round(bottom_right_logical[0] / self.dpi_scale)),
                            int(round(bottom_right_logical[1] / self.dpi_scale))
                        )
                        # 3. 计算在当前客户区物理图像中的裁剪区域
                        crop_x = max(0, top_left_physical[0])
                        crop_y = max(0, top_left_physical[1])
                        crop_w = min(cap_w, bottom_right_physical[0]) - crop_x
                        crop_h = min(cap_h, bottom_right_physical[1]) - crop_y
                        # 4. 执行裁剪（确保区域有效）
                        if crop_w > 0 and crop_h > 0:
                            img_np = img_np[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]
                            self.logger.debug(
                                f"窗口模式裁剪ROI: 原始({roi}) -> 客户区物理({crop_x}, {crop_y}, {crop_w}, {crop_h})")
                        else:
                            self.logger.warning(f"转换后的ROI无效，忽略裁剪。原始ROI: {roi}")
            return img_np
        except Exception as e:
            self.last_error = f"截图失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return None

    def click(
            self,
            pos: Union[Tuple[int, int], str, List[str]],
            click_time: int = 1,
            duration: float = 0.1,
            right_click: bool = False,
            is_base_coord: bool = False,
            roi: Optional[Tuple[int, int, int, int]] = None,
            is_base_roi: bool = False
    ) -> bool:
        """鼠标点击操作（支持多个模板匹配）"""
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "未连接到窗口或状态异常"
            return False
        try:
            if not self.set_foreground():
                 self.last_error = "无法将窗口置于前台，点击操作终止"
                 self.logger.error(self.last_error)
                 return False
            # ---
            time.sleep(0.1)
            target_pos: Optional[Tuple[int, int]] = None
            if isinstance(pos, (str, list)):
                if not self.image_processor:
                    self.last_error = "未设置图像处理器，无法模板匹配"
                    return False
                screen = self.capture_screen()
                if screen is None:
                    self.last_error = "截图失败，无法模板匹配"
                    return False

                # 处理单个模板或多个模板
                if isinstance(pos, str):
                    templates = [pos]
                else:
                    templates = pos
                match_result = None
                matched_template = None

                # 尝试每个模板，直到找到匹配
                for template_name in templates:
                    match_result = self.image_processor.match_template(
                        image=screen,
                        template=template_name,
                        dpi_scale=self.dpi_scale,
                        hwnd=self.hwnd,
                        threshold=0.6,
                        roi=roi,
                        is_base_roi=is_base_roi
                    )
                    if match_result is not None:
                        matched_template = template_name
                        break
                if match_result is None:
                    self.last_error = f"所有模板匹配失败: {templates}"
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
                self.logger.debug(f"模板 {matched_template} 中心点坐标: {target_pos}")
                is_base_coord = False  # 如果是模板匹配，pos已经是客户区坐标了
            else:
                target_pos = tuple(map(int, pos))
                if not target_pos or len(target_pos) != 2:
                    self.last_error = f"无效的点击位置: {target_pos}"
                    return False

            client_pos = target_pos
            if is_base_coord and self.coord_transformer:
                client_pos = self.coord_transformer.convert_original_to_current_client(*target_pos)
                self.logger.debug(f"原始坐标 {target_pos} → 当前客户区坐标 {client_pos}")

            screen_physical_x, screen_physical_y = self.coord_transformer.convert_current_client_to_screen(
                *client_pos)
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
                f"模板: {matched_template if isinstance(pos, (str, list)) else '直接坐标'}"
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
            if not self.set_foreground():
                 self.last_error = "无法将窗口置于前台，滑动操作终止"
                 self.logger.error(self.last_error)
                 return False
            # ---
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
            if not self.set_foreground():
                 self.last_error = "无法将窗口置于前台，按键操作终止"
                 self.logger.error(self.last_error)
                 return False
            # ---
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
            if not self.set_foreground():
                 self.last_error = "无法将窗口置于前台，文本输入操作终止"
                 self.logger.error(self.last_error)
                 return False
            # ---
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

    def exists(
            self,
            template_name: Union[str, List[str]],
            threshold: float = 0.8,
            roi: Optional[Tuple[int, int, int, int]] = None,
            is_base_roi: bool = False
    ) -> Optional[Tuple[int, int]]:
        """检查模板是否存在（支持多个模板）"""
        try:
            if not self.hwnd:
                self.last_error = "未连接到窗口"
                return None
            # --- 修改：调用 set_foreground 确保前台，但遵循新规则 ---
            if not self.set_foreground():
                 self.logger.debug(f"无法将窗口置于前台，exists检查可能不准确")
                 # 这里可以选择返回None或继续尝试截图
                 # 为了兼容性，暂时选择继续
                 # return None 
            # ---
            if not self.image_processor:
                self.last_error = "未设置图像处理器"
                return None
            screen = self.capture_screen()
            if screen is None:
                self.logger.debug(f"截图为空，无法检查模板: {template_name}")
                return None

            # 处理单个模板或多个模板
            if isinstance(template_name, str):
                templates = [template_name]
            else:
                templates = template_name
            self.logger.debug(f"检查模板: {templates}（阈值: {threshold}）")

            # 尝试每个模板，直到找到匹配
            for template in templates:
                match_result = self.image_processor.match_template(
                    image=screen,
                    template=template,
                    dpi_scale=self.dpi_scale,
                    hwnd=self.hwnd,
                    threshold=threshold,
                    roi=roi,
                    is_base_roi=is_base_roi
                )
                if match_result is not None:
                    if isinstance(match_result, np.ndarray):
                        match_rect = tuple(match_result.tolist())
                    else:
                        match_rect = tuple(match_result)
                    if len(match_rect) != 4:
                        self.logger.warning(f"模板结果格式无效: {match_rect}，模板: {template}")
                        continue
                    center_pos = self.image_processor.get_center(match_rect)
                    if isinstance(center_pos, (list, np.ndarray)):
                        center_pos = tuple(map(int, center_pos))
                    if not isinstance(center_pos, tuple) or len(center_pos) != 2:
                        self.logger.warning(f"模板中心点无效: {center_pos}，模板: {template}")
                        continue
                    self.logger.debug(
                        f"模板找到: {template} | 矩形区域: {match_rect} | "
                        f"中心点: {center_pos}"
                    )
                    return center_pos
            self.logger.debug(f"所有模板未找到: {templates}")
            return None
        except Exception as e:
            self.logger.error(f"模板检查异常: {str(e)}", exc_info=True)
            return None

    def wait(
            self,
            template_name: Union[str, List[str]],
            timeout: float = 10.0,
            interval: float = 0.5,
            roi: Optional[Tuple[int, int, int, int]] = None,
            is_base_roi: bool = False
    ) -> Optional[Tuple[int, int]]:
        """等待模板出现（支持多个模板）"""
        start_time = time.time()
        # 处理单个模板或多个模板
        if isinstance(template_name, str):
            templates = [template_name]
        else:
            templates = template_name
        self.logger.debug(f"开始等待模板: {templates}（超时: {timeout}s，间隔: {interval}s）")
        while time.time() - start_time < timeout:
            center_pos = self.exists(templates, roi=roi, is_base_roi=is_base_roi)
            if center_pos is not None:
                self.logger.info(
                    f"模板 {templates} 已找到（等待耗时: {time.time() - start_time:.1f}s），中心点: {center_pos}")
                return center_pos
            time.sleep(interval)
        self.last_error = f"等待模板超时: {templates}（{timeout}s）"
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