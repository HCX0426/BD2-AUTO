import ctypes
import time
from typing import Dict, List, Optional, Tuple, Union
from threading import Event

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
from src.auto_control.image.image_processor import ImageProcessor
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.display_context import RuntimeDisplayContext


class DCHandle:
    """DC资源上下文管理器：安全获取/释放窗口客户区DC（排除标题栏/边框）"""

    def __init__(self, hwnd: int, logger):
        self.hwnd = hwnd
        self.hdc = None
        self.logger = logger

    def __enter__(self) -> int:
        self.hdc = win32gui.GetDC(self.hwnd)
        if not self.hdc:
            raise RuntimeError(f"获取客户区DC失败（窗口句柄: {self.hwnd}）")
        self.logger.debug(f"客户区DC获取成功（句柄: {self.hwnd}, DC: {self.hdc}）")
        return self.hdc

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.hdc and self.hwnd:
            try:
                win32gui.ReleaseDC(self.hwnd, self.hdc)
                self.logger.debug(f"客户区DC释放成功（DC: {self.hdc}）")
            except Exception as e:
                self.logger.error(f"释放客户区DC失败: {str(e)}")


class BitmapHandle:
    """位图资源上下文管理器：自动释放位图对象，避免资源泄漏"""

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
    """
    Windows窗口设备控制器：集成坐标转换、窗口操作、输入控制能力
    核心特性：
    1. 坐标体系：支持基准坐标→逻辑坐标→物理坐标的自动转换，适配全屏/窗口模式
    2. 资源管理：通过上下文管理器安全管理DC/位图资源，避免泄漏
    3. 中断支持：所有阻塞操作（连接、激活、等待）支持stop_event中断
    4. 输入控制：实现鼠标点击/滑动、键盘按键、文本输入等标准化操作
    5. 状态同步：基于RuntimeDisplayContext维护窗口动态信息（分辨率、DPI、位置）
    """

    # 窗口操作延迟配置
    WINDOW_RESTORE_DELAY = 0.5    # 窗口恢复后的稳定等待时间
    WINDOW_ACTIVATE_DELAY = 0.1   # 窗口激活后的验证等待时间
    ACTIVATE_COOLDOWN = 5.0       # 激活冷却时间（避免短时间重复激活）
    FOREGROUND_CHECK_INTERVAL = 5.0  # 前台窗口检查间隔

    def __init__(
            self,
            device_uri: str,
            logger,
            image_processor: ImageProcessor,
            coord_transformer: CoordinateTransformer,
            display_context: RuntimeDisplayContext,
            stop_event: Event
    ):
        """
        初始化Windows设备控制器
        
        Args:
            device_uri: 设备标识URI（格式：windows://key1=value1&key2=value2）
            logger: 日志实例（必填）
            image_processor: 图像处理器实例（必填）
            coord_transformer: 坐标转换器实例（必填）
            display_context: 运行时显示上下文实例（必填）
            stop_event: 全局停止事件（用于中断阻塞操作，必填）
        
        Raises:
            ValueError: 任意必填参数缺失/类型错误时抛出
        """
        super().__init__(device_uri)
        
        # 必填参数校验
        if not logger:
            raise ValueError("参数logger不能为空")
        if not image_processor:
            raise ValueError("参数image_processor不能为空")
        if not isinstance(coord_transformer, CoordinateTransformer):
            raise ValueError("参数coord_transformer必须是CoordinateTransformer实例")
        if not isinstance(display_context, RuntimeDisplayContext):
            raise ValueError("参数display_context必须是RuntimeDisplayContext实例")
        if not isinstance(stop_event, Event):
            raise ValueError("参数stop_event必须是threading.Event实例")
        
        # 基础属性赋值
        self.logger = logger
        self.device_uri = device_uri
        self.image_processor = image_processor
        self.coord_transformer = coord_transformer
        self.display_context = display_context
        self.stop_event = stop_event

        # 窗口基础属性（连接时初始化）
        self.hwnd: Optional[int] = None        
        self.window_title: str = ""            
        self.window_class: str = ""            
        self.process_id: int = 0               

        # 窗口激活状态缓存
        self._last_activate_time = 0.0         
        self._foreground_activation_allowed = True  

        # 解析URI参数
        self.uri_params = self._parse_uri(device_uri)
        self.logger.debug(f"Windows设备URI解析结果: {self.uri_params}")

        # 启用DPI感知
        self._enable_dpi_awareness()

    def _parse_uri(self, uri: str) -> Dict[str, str]:
        """
        解析设备URI参数
        
        Args:
            uri: 设备标识URI（格式：windows://key1=value1&key2=value2）
        
        Returns:
            小写键名的参数字典
        """
        params = {}
        if "://" in uri:
            _, query = uri.split("://", 1)
            for part in query.split("&"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    params[key.lower()] = value
        return params

    def _get_window_handle(self) -> Optional[int]:
        """
        根据URI参数查找目标窗口句柄（按优先级匹配）
        匹配优先级：精确标题 → 正则标题 → 进程名 → 窗口类名
        
        Returns:
            找到的窗口句柄，未找到返回None
        """
        self.logger.info("开始查找目标窗口...")

        # 窗口查找策略列表（按优先级排序）
        strategies = [
            ("精确标题", lambda: self.uri_params.get("title") and win32gui.FindWindow(None, self.uri_params["title"])),
            ("正则标题", self._find_by_title_regex),
            ("进程名", lambda: self._find_window_by_process_name("BrownDust2")),
            ("类名", lambda: win32gui.FindWindow("UnityWndClass", None)),
        ]

        for strategy_name, strategy_func in strategies:
            self.logger.info(f"尝试通过「{strategy_name}」查找窗口")
            hwnd = strategy_func()
            if hwnd:
                self.window_title = win32gui.GetWindowText(hwnd)
                self.logger.info(f"窗口查找成功 | 标题: {self.window_title} | 句柄: {hwnd} | 查找方式: {strategy_name}")
                return hwnd

        self.logger.error("所有查找策略均未找到匹配窗口")
        return None

    def _find_by_title_regex(self) -> Optional[int]:
        """
        通过正则表达式匹配窗口标题（URI参数：title_re）
        
        Returns:
            匹配的窗口句柄，未找到返回None
        """
        if "title_re" not in self.uri_params:
            self.logger.debug("URI未配置title_re参数，跳过正则标题查找")
            return None

        import re
        pattern_str = self.uri_params["title_re"]
        # 兼容通配符*（自动转换为正则.*）
        if '*' in pattern_str and not (pattern_str.startswith('.*') or pattern_str.endswith('.*')):
            pattern_str = pattern_str.replace('*', '.*')

        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
        except re.error as e:
            self.logger.error(f"正则表达式编译失败: {e} | 表达式: {pattern_str}")
            return None

        # 枚举所有窗口匹配正则
        def window_callback(hwnd, result_list):
            title = win32gui.GetWindowText(hwnd)
            if title and pattern.search(title):
                result_list.append(hwnd)
                return False  # 找到第一个匹配项即停止枚举
            return True

        match_results = []
        win32gui.EnumWindows(window_callback, match_results)
        return match_results[0] if match_results else None

    def _find_window_by_process_name(self, process_name: str) -> Optional[int]:
        """
        通过进程名查找关联窗口句柄
        
        Args:
            process_name: 目标进程名（不含.exe）
        
        Returns:
            匹配的窗口句柄，未找到返回None
        """
        try:
            import psutil
            # 遍历所有进程查找目标进程
            for proc in psutil.process_iter(['name', 'pid']):
                if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
                    pid = proc.info['pid']
                    self.logger.info(f"找到目标进程 | 名称: {process_name} | PID: {pid}")

                    # 枚举窗口匹配进程ID
                    def match_pid_callback(hwnd, ctx):
                        _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                        if window_pid == ctx[0] and win32gui.GetWindowText(hwnd):
                            ctx.append(hwnd)
                            return False
                        return True

                    ctx = [pid]
                    win32gui.EnumWindows(match_pid_callback, ctx)
                    if len(ctx) > 1:
                        self.logger.info(f"找到进程关联窗口 | 句柄: {ctx[1]}")
                        return ctx[1]
        except ImportError:
            self.logger.warning("psutil未安装，无法通过进程名查找窗口")
        except Exception as e:
            self.logger.error(f"进程名查找窗口异常: {str(e)}")
        return None

    def _enable_dpi_awareness(self) -> None:
        """启用DPI感知模式（优先Per-Monitor，兼容旧系统）"""
        try:
            shcore = ctypes.windll.shcore
            # 优先启用Per-Monitor DPI感知（Windows 8.1+）
            result = shcore.SetProcessDpiAwareness(2)
            if result == 0:
                self.logger.debug("已启用Per-Monitor DPI感知模式")
                try:
                    system_dpi = ctypes.windll.user32.GetDpiForSystem()
                    self.logger.debug(f"系统DPI: {system_dpi}（标准DPI=96）")
                except Exception:
                    pass
            else:
                self.logger.warning(f"SetProcessDpiAwareness调用失败，错误码: {result}")
        except Exception as e:
            self.logger.error(f"启用Per-Monitor DPI感知失败: {str(e)}")
            # 降级启用系统DPI感知（Windows Vista+）
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                self.logger.debug("已启用系统级DPI感知模式")
            except Exception:
                self.logger.error("所有DPI感知模式启用失败，可能导致坐标偏移")

    def _get_dpi_for_window(self) -> float:
        """
        获取当前窗口的DPI缩放因子（物理像素/逻辑像素）
        
        Returns:
            DPI缩放因子（默认1.0）
        """
        if not self.hwnd:
            self.logger.warning("窗口句柄未初始化，返回默认DPI缩放因子1.0")
            return 1.0

        try:
            # 优先获取窗口专属DPI（Windows 8.1+）
            if hasattr(ctypes.windll.user32, 'GetDpiForWindow'):
                window_dpi = ctypes.windll.user32.GetDpiForWindow(self.hwnd)
                if window_dpi > 0:
                    return window_dpi / 96.0
            # 降级获取系统DPI
            system_dpi = ctypes.windll.user32.GetDpiForSystem()
            return system_dpi / 96.0
        except Exception as e:
            self.logger.error(f"获取DPI缩放因子异常: {str(e)}，返回默认值1.0")
            return 1.0

    def _get_screen_hardware_res(self) -> Tuple[int, int]:
        """
        获取物理屏幕分辨率（不含缩放的原始像素尺寸）
        
        Returns:
            (屏幕宽度, 屏幕高度)
        """
        try:
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            self.logger.debug(f"物理屏幕分辨率: {screen_width}x{screen_height}")
            return (screen_width, screen_height)
        except Exception as e:
            self.logger.error(f"获取屏幕分辨率失败: {str(e)}，返回默认1920x1080")
            return (1920, 1080)

    def _update_dynamic_window_info(self) -> bool:
        """
        更新窗口动态信息到全局RuntimeDisplayContext（分辨率、DPI、位置等）
        窗口非最小化时才更新，确保数据有效性
        
        Returns:
            更新成功返回True，失败返回False
        """
        try:
            if self.is_minimized():
                self.logger.debug("窗口处于最小化状态，跳过动态信息更新")
                return False

            # 获取窗口边界矩形（屏幕全局坐标）
            window_rect = win32gui.GetWindowRect(self.hwnd)
            if all(coord == 0 for coord in window_rect):
                raise RuntimeError(f"获取窗口矩形失败，返回无效值: {window_rect}")

            # 获取DPI缩放因子
            dpi_scale = self._get_dpi_for_window()
            dpi_scale = max(1.0, dpi_scale)  # 避免异常缩放因子

            # 获取客户区物理尺寸（原始像素，不含边框）
            client_rect_phys = win32gui.GetClientRect(self.hwnd)
            client_w_phys = client_rect_phys[2] - client_rect_phys[0]
            client_h_phys = client_rect_phys[3] - client_rect_phys[1]
            if client_w_phys <= 0 or client_h_phys <= 0:
                raise RuntimeError(f"客户区物理尺寸无效: {client_w_phys}x{client_h_phys}")

            # 计算客户区逻辑尺寸（物理尺寸 ÷ DPI缩放因子）
            client_w_logic = int(round(client_w_phys / dpi_scale))
            client_h_logic = int(round(client_h_phys / dpi_scale))
            # 确保最小逻辑尺寸（避免异常值）
            client_w_logic = max(800, client_w_logic)
            client_h_logic = max(600, client_h_logic)

            # 获取客户区左上角屏幕坐标（全局物理坐标）
            client_origin_x, client_origin_y = win32gui.ClientToScreen(self.hwnd, (0, 0))

            # 判断是否为全屏模式
            is_fullscreen = self.coord_transformer.is_fullscreen

            # 更新全局显示上下文
            self.display_context.update_from_window(
                hwnd=self.hwnd,
                is_fullscreen=is_fullscreen,
                dpi_scale=dpi_scale,
                client_logical=(client_w_logic, client_h_logic),
                client_physical=(client_w_phys, client_h_phys),
                screen_physical=self._get_screen_hardware_res(),
                client_origin=(client_origin_x, client_origin_y)
            )

            self.logger.debug(
                f"窗口动态信息更新完成 | "
                f"模式: {'全屏' if is_fullscreen else '窗口'} | "
                f"逻辑尺寸: {client_w_logic}x{client_h_logic} | "
                f"物理尺寸: {client_w_phys}x{client_h_phys} | "
                f"DPI缩放: {dpi_scale:.2f} | "
                f"屏幕原点: ({client_origin_x},{client_origin_y})"
            )
            return True
        except Exception as e:
            self.last_error = f"动态窗口信息更新失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    def connect(self, timeout: float = 10.0) -> bool:
        """
        连接到目标Windows窗口（超时重试，支持stop_event中断）
        
        Args:
            timeout: 连接超时时间（秒）
        
        Returns:
            连接成功返回True，失败返回False
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            # 检查停止信号
            if self.stop_event.is_set():
                self.last_error = "连接被停止信号中断"
                self.logger.error(self.last_error)
                return False
            
            # 查找窗口句柄
            self.hwnd = self._get_window_handle()
            if self.hwnd:
                # 初始化窗口基础属性
                self.window_class = win32gui.GetClassName(self.hwnd)
                _, self.process_id = win32process.GetWindowThreadProcessId(self.hwnd)
                screen_res = self._get_screen_hardware_res()

                # 初始化显示上下文基础信息
                self.display_context.original_base_width = self.display_context.original_base_width
                self.display_context.original_base_height = self.display_context.original_base_height
                self.display_context.hwnd = self.hwnd
                self.display_context.screen_physical_width, self.display_context.screen_physical_height = screen_res

                # 激活窗口并更新动态信息
                self.set_foreground()
                time.sleep(0.5)

                # 验证窗口有效性
                if win32gui.IsWindow(self.hwnd) and win32gui.IsWindowVisible(self.hwnd):
                    self.state = DeviceState.CONNECTED
                    self.logger.info(
                        f"Windows设备连接成功 | "
                        f"标题: {self.window_title} | 句柄: {self.hwnd} | "
                        f"类名: {self.window_class} | PID: {self.process_id} | "
                        f"屏幕分辨率: {screen_res}"
                    )
                    return True

            # 未找到窗口，重试间隔
            time.sleep(0.5)

        self.last_error = f"连接超时（{timeout}秒），未找到匹配窗口"
        self.state = DeviceState.DISCONNECTED
        self.logger.error(f"连接失败: {self.last_error}")
        return False

    def disconnect(self) -> bool:
        """
        断开与窗口的连接，清理资源和状态
        
        Returns:
            断开成功返回True，未连接返回False
        """
        if self.hwnd:
            self.logger.info(f"断开窗口连接 | 标题: {self.window_title} | 句柄: {self.hwnd}")

            # 重置显示上下文
            self.display_context.update_from_window(
                hwnd=None,
                is_fullscreen=False,
                dpi_scale=1.0,
                client_logical=(0, 0),
                client_physical=(0, 0),
                client_origin=(0, 0)
            )

            # 重置设备状态
            self.hwnd = None
            self.window_title = ""
            self.window_class = ""
            self.process_id = 0
            self._last_activate_time = 0.0
            self._foreground_activation_allowed = True
            self.state = DeviceState.DISCONNECTED
            return True
        self.logger.debug("未连接到任何窗口，无需断开")
        return False

    def is_minimized(self) -> bool:
        """
        检查窗口是否处于最小化状态
        
        Returns:
            最小化返回True，否则返回False
        """
        if not self.hwnd:
            return True
        return win32gui.IsIconic(self.hwnd)

    def set_foreground(self) -> bool:
        """
        将窗口激活到前台（支持stop_event中断）
        
        Returns:
            激活成功返回True，中断/失败返回False
        """
        current_time = time.time()
        foreground_hwnd = win32gui.GetForegroundWindow()

        # 已在前台，直接返回成功
        if foreground_hwnd == self.hwnd:
            self._last_activate_time = current_time
            self.logger.debug(f"窗口已在前台（句柄: {self.hwnd}），无需激活")
            self._update_dynamic_window_info()
            return True

        # 首次激活尝试（冷却期内仅尝试一次）
        if self._foreground_activation_allowed:
            self.logger.info(f"尝试激活窗口到前台（句柄: {self.hwnd}）")
            try:
                # 恢复最小化窗口
                if self.is_minimized():
                    self.logger.info("窗口处于最小化状态，正在恢复...")
                    win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                    time.sleep(self.WINDOW_RESTORE_DELAY)
                    # 恢复后自动激活校验
                    if win32gui.GetForegroundWindow() == self.hwnd:
                        self._last_activate_time = current_time
                        self._foreground_activation_allowed = False
                        self.logger.info("窗口恢复后自动激活成功")
                        self._update_dynamic_window_info()
                        return True

                # 标准激活流程
                win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
                activate_success = win32gui.SetForegroundWindow(self.hwnd)
                time.sleep(self.WINDOW_ACTIVATE_DELAY)
                final_foreground = win32gui.GetForegroundWindow()

                if activate_success and final_foreground == self.hwnd and not self.is_minimized():
                    self._last_activate_time = current_time
                    self._foreground_activation_allowed = False
                    self.logger.info(f"窗口激活成功（句柄: {self.hwnd}）")
                    self._update_dynamic_window_info()
                    return True
                else:
                    self.logger.warning("窗口激活尝试失败，进入前台等待模式（可通过stop_event中断）")
            except Exception as e:
                self.logger.error(f"激活窗口异常: {str(e)}", exc_info=True)

            # 禁用重复激活尝试，进入等待模式
            self._foreground_activation_allowed = False
            self.logger.info(f"每{self.FOREGROUND_CHECK_INTERVAL}秒检查一次前台状态")

        # 循环等待前台状态（支持中断）
        while True:
            # 检查停止信号
            if self.stop_event.is_set():
                self.logger.info("窗口激活等待被停止信号中断")
                self.last_error = "窗口激活被用户中断"
                return False

            # 等待检查间隔
            if self.stop_event.wait(timeout=self.FOREGROUND_CHECK_INTERVAL):
                self.logger.info("窗口激活等待被停止信号中断")
                self.last_error = "窗口激活被用户中断"
                return False

            try:
                if win32gui.GetForegroundWindow() == self.hwnd:
                    self.logger.info("窗口已回到前台，激活成功")
                    self._update_dynamic_window_info()
                    return True
                self.logger.debug("窗口仍未在前台，继续等待...")
            except Exception as e:
                self.logger.error(f"检查前台窗口状态异常: {str(e)}")

        return False

    def get_resolution(self) -> Tuple[int, int]:
        """
        获取当前窗口客户区逻辑分辨率（与DPI缩放无关）
        
        Returns:
            (客户区逻辑宽度, 客户区逻辑高度)
        """
        return self.display_context.client_logical_res

    def capture_screen(self, roi: Optional[Tuple[int, int, int, int]] = None) -> Optional[np.ndarray]:
        """
        截取窗口客户区图像（自动适配全屏/窗口模式，支持ROI裁剪）
        
        Args:
            roi: 裁剪区域（基准ROI格式：(x, y, width, height)，None则截取整个客户区）
        
        Returns:
            BGR格式numpy图像数组，失败返回None
        """
        try:
            time.sleep(0.1)  # 确保窗口渲染完成

            # 从上下文获取基础参数
            is_fullscreen = self.display_context.is_fullscreen
            client_w_phys, client_h_phys = self.display_context.client_physical_res
            client_origin_x, client_origin_y = self.display_context.client_screen_origin

            # 初始化截图DC和位图
            hdc_screen = win32gui.GetDC(0)
            mfcDC = win32ui.CreateDCFromHandle(hdc_screen)
            saveDC = mfcDC.CreateCompatibleDC()
            saveBitMap = win32ui.CreateBitmap()

            # 全屏模式截图（截取整个屏幕）
            if is_fullscreen:
                cap_w, cap_h = self.display_context.screen_physical_res
                saveBitMap.CreateCompatibleBitmap(mfcDC, cap_w, cap_h)
                saveDC.SelectObject(saveBitMap)
                # 复制屏幕图像
                ctypes.windll.gdi32.BitBlt(
                    saveDC.GetSafeHdc(), 0, 0, cap_w, cap_h,
                    hdc_screen, 0, 0, win32con.SRCCOPY
                )
                self.logger.debug(f"全屏模式截图 | 尺寸: {cap_w}x{cap_h}")
            else:
                # 窗口模式截图（仅截取客户区）
                cap_w, cap_h = client_w_phys, client_h_phys
                saveBitMap.CreateCompatibleBitmap(mfcDC, cap_w, cap_h)
                saveDC.SelectObject(saveBitMap)
                # 复制客户区图像（基于屏幕原点坐标）
                ctypes.windll.gdi32.BitBlt(
                    saveDC.GetSafeHdc(), 0, 0, cap_w, cap_h,
                    hdc_screen, client_origin_x, client_origin_y,
                    win32con.SRCCOPY
                )
                self.logger.debug(f"窗口模式截图 | 客户区物理尺寸: {cap_w}x{cap_h}")

            # 位图转numpy数组（BGR格式）
            bmp_str = saveBitMap.GetBitmapBits(True)
            img_pil = Image.frombuffer('RGB', (cap_w, cap_h), bmp_str, 'raw', 'BGRX', 0, 1)
            img_np = np.array(img_pil)
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            # 资源释放
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.DeleteObject(saveBitMap.GetHandle())
            win32gui.ReleaseDC(0, hdc_screen)

            # ROI裁剪处理
            if roi:
                if is_fullscreen:
                    # 全屏模式：基准ROI直接作为物理坐标，校验并限制边界
                    is_valid, err_msg = self.coord_transformer.validate_roi_format(roi)
                    if not is_valid:
                        self.logger.warning(f"全屏ROI无效: {err_msg}")
                    else:
                        # 限制ROI在屏幕物理边界内
                        limited_roi = self.coord_transformer.limit_rect_to_boundary(roi, cap_w, cap_h)
                        crop_x, crop_y, crop_w, crop_h = limited_roi
                        img_np = img_np[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]
                        self.logger.debug(f"全屏ROI裁剪 | 原始ROI: {roi} → 限制后: {limited_roi}")
                else:
                    # 窗口模式：基准ROI→客户区物理ROI
                    screen_phys_rect = self.coord_transformer.convert_client_logical_rect_to_screen_physical(
                        roi, is_base_coord=True
                    )
                    if not screen_phys_rect:
                        self.logger.warning(f"窗口ROI转换失败: {roi}")
                    else:
                        # 提取客户区物理坐标（截图已为客户区，无需屏幕原点偏移）
                        phys_x, phys_y, phys_w, phys_h = screen_phys_rect
                        # 限制在客户区物理边界内
                        limited_roi = self.coord_transformer.limit_rect_to_boundary(
                            (phys_x, phys_y, phys_w, phys_h), cap_w, cap_h
                        )
                        crop_x, crop_y, crop_w, crop_h = limited_roi
                        if crop_w > 0 and crop_h > 0:
                            img_np = img_np[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]
                            self.logger.debug(f"窗口ROI裁剪 | 基准ROI: {roi} → 物理ROI: {limited_roi}")
                        else:
                            self.logger.warning(f"窗口ROI转换后无效: {roi} → 物理ROI: {screen_phys_rect}")

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
            roi: Optional[Tuple[int, int, int, int]] = None
    ) -> bool:
        """
        鼠标点击操作（支持直接坐标点击和模板匹配点击）
        
        Args:
            pos: 点击目标（2元组坐标/单个模板名/模板名列表）
            click_time: 点击次数（默认1次）
            duration: 单次点击按住时长（秒，默认0.1s）
            right_click: 是否右键点击（默认False：左键）
            is_base_coord: pos为坐标时，是否是基准坐标（默认False：客户区逻辑坐标）
            roi: 模板匹配时的搜索区域（基准ROI，None则全图搜索）
        
        Returns:
            点击成功返回True，失败返回False
        """
        # 基础有效性校验
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "设备未连接或状态异常"
            self.logger.error(f"点击失败: {self.last_error}")
            return False

        try:
            # 激活窗口（确保点击生效）
            if not self.set_foreground():
                self.last_error = "无法激活窗口至前台"
                self.logger.error(f"点击失败: {self.last_error}")
                return False

            time.sleep(0.1)  # 激活后稳定等待
            target_pos: Optional[Tuple[int, int]] = None
            ctx = self.display_context
            click_source = "直接坐标"

            # 模板匹配点击逻辑
            if isinstance(pos, (str, list)):
                click_source = "模板匹配"
                # 截图并执行模板匹配
                screen_img = self.capture_screen()
                if screen_img is None:
                    self.last_error = "截图失败，无法执行模板匹配"
                    self.logger.error(f"点击失败: {self.last_error}")
                    return False

                # ROI预处理
                processed_roi = roi
                if roi:
                    # 统一校验ROI格式
                    is_valid, err_msg = self.coord_transformer.validate_roi_format(roi)
                    if not is_valid:
                        self.logger.warning(f"ROI预处理失败: {err_msg}，切换为全图匹配")
                        processed_roi = None
                    else:
                        # 根据模式获取对应的边界尺寸，自动适配全屏/窗口
                        boundary_w, boundary_h = (
                            ctx.screen_physical_res if ctx.is_fullscreen else ctx.client_logical_res
                        )
                        # 限制ROI在有效边界内
                        processed_roi = self.coord_transformer.limit_rect_to_boundary(roi, boundary_w, boundary_h)
                        self.logger.debug(f"ROI预处理完成 | 原始: {roi} → 处理后: {processed_roi}")

                # 多模板匹配（按顺序尝试，找到即停止）
                templates = [pos] if isinstance(pos, str) else pos
                matched_template = None
                match_result = None
                for template_name in templates:
                    match_result = self.image_processor.match_template(
                        image=screen_img,
                        template=template_name,
                        threshold=0.6,
                        roi=processed_roi
                    )
                    if match_result is not None:
                        matched_template = template_name
                        break

                if match_result is None:
                    self.last_error = f"所有模板匹配失败: {templates}"
                    self.logger.error(f"点击失败: {self.last_error}")
                    return False

                # 解析匹配结果
                match_rect = self.coord_transformer._convert_numpy_to_tuple(match_result)
                is_valid, err_msg = self.coord_transformer.validate_roi_format(match_rect)
                if not is_valid:
                    self.last_error = f"模板匹配结果无效: {err_msg} | 模板: {matched_template}"
                    self.logger.error(f"点击失败: {self.last_error}")
                    return False
                # 计算矩形中心点（逻辑坐标）
                target_pos = self.coord_transformer.get_rect_center(match_rect)
                self.logger.debug(
                    f"模板匹配成功 | 模板: {matched_template} | 匹配矩形: {match_rect} | 逻辑中心点: {target_pos}"
                )
                is_base_coord = False  # 模板匹配结果已为逻辑坐标，无需额外转换

            # 直接坐标点击逻辑
            else:
                # 坐标格式校验和标准化
                target_pos = self.coord_transformer._convert_numpy_to_tuple(pos)
                if not isinstance(target_pos, tuple) or len(target_pos) != 2:
                    self.last_error = f"点击坐标格式无效（需2元组）: {pos}"
                    self.logger.error(f"点击失败: {self.last_error}")
                    return False
                x, y = target_pos
                # 坐标有效性校验（非负）
                if x < 0 or y < 0:
                    self.last_error = f"点击坐标无效（非负）: ({x},{y})"
                    self.logger.error(f"点击失败: {self.last_error}")
                    return False

            # 坐标转换
            if not target_pos:
                self.last_error = "未获取到有效点击坐标"
                self.logger.error(f"点击失败: {self.last_error}")
                return False

            x_target, y_target = target_pos
            # 1. 基准坐标→客户区逻辑坐标（如需）
            if is_base_coord:
                logical_x, logical_y = self.coord_transformer.convert_original_to_current_client(x_target, y_target)
                self.logger.debug(f"基准坐标转换 | 基准: ({x_target},{y_target}) → 逻辑: ({logical_x},{logical_y})")
            else:
                logical_x, logical_y = x_target, y_target

            # 2. 逻辑坐标→屏幕物理坐标
            screen_x, screen_y = self.coord_transformer.convert_client_logical_to_screen_physical(logical_x, logical_y)

            # 执行鼠标点击
            win32api.SetCursorPos((screen_x, screen_y))
            time.sleep(0.05)

            # 配置鼠标事件（左键/右键）
            mouse_down = win32con.MOUSEEVENTF_RIGHTDOWN if right_click else win32con.MOUSEEVENTF_LEFTDOWN
            mouse_up = win32con.MOUSEEVENTF_RIGHTUP if right_click else win32con.MOUSEEVENTF_LEFTUP

            # 执行多次点击
            for i in range(click_time):
                if i > 0:
                    time.sleep(0.1)  # 多次点击间隔
                win32api.mouse_event(mouse_down, 0, 0, 0, 0)
                time.sleep(duration)
                win32api.mouse_event(mouse_up, 0, 0, 0, 0)

            # 日志输出
            click_type = "右键" if right_click else "左键"
            self.logger.info(
                f"点击成功 | 类型: {click_type} | 次数: {click_time} | 按住时长: {duration}s | "
                f"屏幕坐标: ({screen_x},{screen_y}) | 模式: {'全屏' if ctx.is_fullscreen else '窗口'} | 来源: {click_source}"
            )
            return True

        except Exception as e:
            self.last_error = f"点击执行异常: {str(e)}"
            self.logger.error(f"点击失败: {self.last_error}", exc_info=True)
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
        鼠标滑动操作（平滑移动，支持基准坐标/逻辑坐标）
        
        Args:
            start_x: 滑动起始X坐标
            start_y: 滑动起始Y坐标
            end_x: 滑动结束X坐标
            end_y: 滑动结束Y坐标
            duration: 滑动总时长（秒，默认0.3s）
            steps: 滑动步数（步数越多越平滑，默认10步）
            is_base_coord: 坐标是否为基准坐标（默认False：客户区逻辑坐标）
        
        Returns:
            滑动成功返回True，失败返回False
        """
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "设备未连接或状态异常"
            self.logger.error(self.last_error)
            return False

        try:
            # 激活窗口
            if not self.set_foreground():
                self.last_error = "无法激活窗口至前台"
                self.logger.error(self.last_error)
                return False

            time.sleep(0.1)
            start_pos = (start_x, start_y)
            end_pos = (end_x, end_y)

            # 坐标转换：基准坐标 → 客户区逻辑坐标
            if is_base_coord:
                start_pos = self.coord_transformer.convert_original_to_current_client(*start_pos)
                end_pos = self.coord_transformer.convert_original_to_current_client(*end_pos)
                self.logger.debug(f"基准坐标转换 | 起始: {start_pos} → 结束: {end_pos}")

            # 逻辑坐标 → 屏幕物理坐标
            screen_start = self.coord_transformer.convert_client_logical_to_screen_physical(*start_pos)
            screen_end = self.coord_transformer.convert_client_logical_to_screen_physical(*end_pos)
            self.logger.debug(f"滑动物理坐标 | 起始: {screen_start} → 结束: {screen_end}")

            # 计算每步偏移和延迟
            step_x = (screen_end[0] - screen_start[0]) / steps
            step_y = (screen_end[1] - screen_start[1]) / steps
            step_delay = duration / steps

            # 执行滑动
            win32api.SetCursorPos(screen_start)
            time.sleep(0.1)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)

            for i in range(1, steps + 1):
                current_x = int(round(screen_start[0] + step_x * i))
                current_y = int(round(screen_start[1] + step_y * i))
                win32api.SetCursorPos((current_x, current_y))
                time.sleep(step_delay)

            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

            self.logger.info(
                f"滑动成功 | 逻辑坐标: {start_pos} → {end_pos} | 时长: {duration}s | 步数: {steps}"
            )
            return True
        except Exception as e:
            self.last_error = f"滑动失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    def key_press(self, key: str, duration: float = 0.1) -> bool:
        """
        按键操作（激活窗口后执行，支持系统按键和普通字符）
        
        Args:
            key: 按键标识（如 'enter'、'a'、'ctrl+c'，参考pydirectinput按键定义）
            duration: 按键按住时长（秒，默认0.1s）
        
        Returns:
            按键成功返回True，失败返回False
        """
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "设备未连接或状态异常"
            self.logger.error(self.last_error)
            return False

        try:
            # 激活窗口
            if not self.set_foreground():
                self.last_error = "无法激活窗口至前台"
                self.logger.error(self.last_error)
                return False

            time.sleep(0.1)
            # 执行按键
            pydirectinput.keyDown(key)
            time.sleep(duration)
            pydirectinput.keyUp(key)

            self.logger.info(f"按键成功 | 按键: {key} | 按住时长: {duration}s")
            return True
        except Exception as e:
            self.last_error = f"按键失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    def text_input(self, text: str, interval: float = 0.05) -> bool:
        """
        文本输入操作（长文本优先粘贴，短文本逐字符输入）
        
        Args:
            text: 待输入文本（支持空格、换行、制表符）
            interval: 逐字符输入时间间隔（秒，默认0.05s）
        
        Returns:
            输入成功返回True，失败返回False
        """
        if not self.hwnd or self.state != DeviceState.CONNECTED:
            self.last_error = "设备未连接或状态异常"
            self.logger.error(self.last_error)
            return False

        try:
            # 激活窗口
            if not self.set_foreground():
                self.last_error = "无法激活窗口至前台"
                self.logger.error(self.last_error)
                return False

            time.sleep(0.1)
            # 长文本（>5字符）使用粘贴模式（效率更高）
            if len(text) > 5:
                import pyperclip
                pyperclip.copy(text)
                # 执行Ctrl+V粘贴
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                win32api.keybd_event(ord('V'), 0, 0, 0)
                time.sleep(0.05)
                win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(0.1)
                log_text = text[:20] + "..." if len(text) > 20 else text
                self.logger.info(f"文本粘贴成功 | 内容: {log_text} | 长度: {len(text)}")
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
                    # 处理大小写和特殊字符（需要Shift的字符）
                    shift_required = char.isupper() or char in '~!@#$%^&*()_+{}|:"<>?'
                    if shift_required:
                        win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
                    # 转换为大写后发送（Shift已处理大小写）
                    win32api.keybd_event(ord(char.upper()), 0, 0, 0)
                    time.sleep(0.02)
                    win32api.keybd_event(ord(char.upper()), 0, win32con.KEYEVENTF_KEYUP, 0)
                    if shift_required:
                        win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)
                    time.sleep(interval)

            self.logger.info(f"文本输入成功 | 内容: {text}")
            return True
        except Exception as e:
            self.last_error = f"文本输入失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    def exists(
            self,
            template_name: Union[str, List[str]],
            threshold: float = 0.8,
            roi: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Tuple[int, int]]:
        """
        检查模板元素是否存在（支持多模板匹配）
        
        Args:
            template_name: 模板名（单个或列表）
            threshold: 匹配阈值（0-1，默认0.8，值越高匹配越严格）
            roi: 搜索区域（基准ROI，None则全图搜索）
        
        Returns:
            找到返回元素中心点（客户区逻辑坐标），未找到返回None
        """
        try:
            if not self.hwnd:
                self.last_error = "设备未连接"
                self.logger.error(self.last_error)
                return None

            # 尝试激活窗口（不强制，失败仅警告）
            if not self.set_foreground():
                self.logger.warning("窗口未激活至前台，模板匹配结果可能不准确")

            # 截图
            screen_img = self.capture_screen()
            if screen_img is None:
                self.logger.warning("截图失败，无法执行模板检查")
                return None

            # ROI预处理
            processed_roi = roi
            if roi:
                is_valid, err_msg = self.coord_transformer.validate_roi_format(roi)
                if not is_valid:
                    self.logger.warning(f"ROI无效: {err_msg}，切换为全图搜索")
                    processed_roi = None

            # 多模板匹配
            templates = [template_name] if isinstance(template_name, str) else template_name
            self.logger.debug(f"模板检查 | 模板列表: {templates} | 阈值: {threshold} | ROI: {processed_roi}")

            for template in templates:
                match_result = self.image_processor.match_template(
                    image=screen_img,
                    template=template,
                    threshold=threshold,
                    roi=processed_roi
                )
                if match_result is not None:
                    # 解析匹配结果
                    match_rect = self.coord_transformer._convert_numpy_to_tuple(match_result)
                    is_valid, err_msg = self.coord_transformer.validate_roi_format(match_rect)
                    if not is_valid:
                        self.logger.warning(f"模板匹配结果无效: {err_msg} | 模板: {template}")
                        continue
                    # 计算中心点
                    center_pos = self.coord_transformer.get_rect_center(match_rect)
                    center_pos = tuple(map(int, center_pos))
                    self.logger.info(
                        f"模板找到 | 名称: {template} | 匹配矩形: {match_rect} | 逻辑中心点: {center_pos}"
                    )
                    return center_pos

            self.logger.debug(f"所有模板未找到: {templates}")
            return None
        except Exception as e:
            self.last_error = f"模板检查异常: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return None

    def wait(
            self,
            template_name: Union[str, List[str]],
            timeout: float = 10.0,
            interval: float = 0.5,
            roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[Tuple[int, int]]:
        """
        等待模板元素出现（支持stop_event中断）
        
        Args:
            template_name: 模板名（单个或列表）
            timeout: 等待超时时间（秒，默认10s）
            interval: 检查间隔（秒，默认0.5s）
            roi: 搜索区域（基准ROI，None则全图搜索）
        
        Returns:
            找到返回元素中心点（客户区逻辑坐标），超时/中断返回None
        """
        start_time = time.time()
        templates = [template_name] if isinstance(template_name, str) else template_name
        self.logger.info(
            f"开始等待模板 | 列表: {templates} | 超时: {timeout}s | 检查间隔: {interval}s | ROI: {roi}"
        )

        while time.time() - start_time < timeout:
            # 检查停止信号
            if self.stop_event.is_set():
                self.logger.info("模板等待被停止信号中断")
                self.last_error = "模板等待被用户中断"
                return None

            center_pos = self.exists(templates, threshold=0.8, roi=roi)
            if center_pos is not None:
                elapsed_time = time.time() - start_time
                self.logger.info(
                    f"模板等待成功 | 列表: {templates} | 耗时: {elapsed_time:.1f}s | 中心点: {center_pos}"
                )
                return center_pos

            # 等待检查间隔（支持中断）
            if self.stop_event.wait(timeout=interval):
                self.logger.info("模板等待被停止信号中断")
                self.last_error = "模板等待被用户中断"
                return None

        self.last_error = f"模板等待超时（{timeout}s）| 列表: {templates}"
        self.logger.error(self.last_error)
        return None

    def get_state(self) -> DeviceState:
        """
        获取设备当前状态
        
        Returns:
            DeviceState枚举值（CONNECTED/INVISIBLE/DISCONNECTED/ERROR）
        """
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
            self.logger.error(f"获取设备状态异常: {str(e)}")
            return DeviceState.ERROR

    def sleep(self, secs: float, stop_event: Optional[Event] = None) -> bool:
        """
        设备睡眠（支持stop_event中断）
        
        Args:
            secs: 睡眠时长（秒，需大于0）
            stop_event: 停止事件（优先使用实例的stop_event）
        
        Returns:
            睡眠完成返回True，中断/异常返回False
        """
        if secs <= 0:
            self.logger.warning(f"无效睡眠时间: {secs}秒（需大于0）")
            return False

        # 优先使用传入的stop_event，否则使用实例的
        event = stop_event or self.stop_event
        try:
            self.logger.debug(f"设备睡眠开始 | 时长: {secs}秒（支持中断）")
            if event.wait(timeout=secs):
                self.logger.info(f"设备睡眠被中断 | 时长: {secs}秒")
                return False
            self.logger.debug(f"设备睡眠完成 | 时长: {secs}秒")
            return True
        except Exception as e:
            self.last_error = f"睡眠操作失败: {str(e)}"
            self.logger.error(self.last_error)
            return False