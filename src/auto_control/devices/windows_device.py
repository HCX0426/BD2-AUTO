import ctypes
import time
from enum import Enum, auto
from threading import Event
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
from src.auto_control.image.image_processor import ImageProcessor
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.display_context import RuntimeDisplayContext


class CoordType(Enum):
    """
    坐标类型枚举，定义Windows设备支持的坐标体系。
    
    枚举值说明：
    - LOGICAL: 逻辑坐标（适配DPI缩放后的客户区坐标）
    - PHYSICAL: 物理坐标（屏幕像素坐标，未缩放）
    - BASE: 基准坐标（原始设计分辨率坐标，需转换为当前窗口坐标）
    """
    LOGICAL = auto()
    PHYSICAL = auto()
    BASE = auto()


class WindowsDevice(BaseDevice):
    """
    Windows窗口设备控制器，实现BaseDevice抽象接口，提供Windows平台下的窗口控制能力。
    
    核心能力：
    1. 窗口管理：支持多策略查找窗口、激活窗口、状态检测
    2. 坐标体系：基准/逻辑/物理坐标自动转换，适配全屏/窗口模式
    3. 输入控制：鼠标点击/滑动、键盘按键、文本输入
    4. 图像操作：屏幕截图（支持ROI裁剪）、模板匹配检查
    5. 中断支持：所有阻塞操作支持通过stop_event优雅中断
    6. DPI适配：自动处理系统DPI缩放，避免坐标偏移
    """
    # 窗口操作延迟配置
    WINDOW_RESTORE_DELAY = 0.5
    WINDOW_ACTIVATE_DELAY = 0.1
    ACTIVATE_COOLDOWN = 5.0
    FOREGROUND_CHECK_INTERVAL = 5.0

    def __init__(
        self,
        device_uri: str,
        logger,
        image_processor: ImageProcessor,
        coord_transformer: CoordinateTransformer,
        display_context: RuntimeDisplayContext,
        stop_event: Event,
    ):
        """
        初始化Windows设备控制器。
        
        Args:
            device_uri: 设备URI，格式示例："windows://title=测试窗口&title_re=.*BrownDust2.*"
            logger: 日志记录器对象（需实现debug/info/warning/error方法）
            image_processor: 图像处理器实例，用于模板匹配
            coord_transformer: 坐标转换器实例，处理不同坐标体系转换
            display_context: 显示上下文实例，维护窗口动态信息
            stop_event: 线程停止事件，用于中断阻塞操作
            
        Raises:
            ValueError: 任一必填参数为空或类型不匹配时触发
        """
        super().__init__(device_uri)

        # 必填参数校验
        if not logger:
            raise ValueError("[WindowsDevice.__init__] 参数logger不能为空")
        if not image_processor:
            raise ValueError("[WindowsDevice.__init__] 参数image_processor不能为空")
        if not isinstance(coord_transformer, CoordinateTransformer):
            raise ValueError("[WindowsDevice.__init__] 参数coord_transformer必须是CoordinateTransformer实例")
        if not isinstance(display_context, RuntimeDisplayContext):
            raise ValueError("[WindowsDevice.__init__] 参数display_context必须是RuntimeDisplayContext实例")
        if not isinstance(stop_event, Event):
            raise ValueError("[WindowsDevice.__init__] 参数stop_event必须是threading.Event实例")

        # 基础属性赋值
        self.logger = logger
        self.image_processor = image_processor
        self.coord_transformer = coord_transformer
        self.display_context = display_context
        self.stop_event = stop_event

        # 窗口基础属性
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

    # -------------- 私有工具方法 --------------
    def _parse_uri(self, uri: str) -> Dict[str, str]:
        """
        解析设备URI参数，提取键值对并转换为小写键名。
        
        Args:
            uri: 设备URI字符串，格式为 "协议://key1=value1&key2=value2"
            
        Returns:
            Dict[str, str]: 解析后的参数字典（键为小写）
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
        多策略查找目标窗口句柄，按优先级依次尝试：精确标题→正则标题→进程名→类名。
        
        Returns:
            Optional[int]: 找到的窗口句柄，未找到返回None
        """
        self.logger.info("开始查找目标窗口...")
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

        self._record_error("_get_window_handle", "所有查找策略均未找到匹配窗口")
        self.logger.error(self.last_error)
        return None

    def _find_by_title_regex(self) -> Optional[int]:
        """
        通过正则表达式匹配窗口标题，查找目标窗口。
        
        依赖URI参数：title_re（正则表达式字符串，支持*通配符自动转换为.*）
        
        Returns:
            Optional[int]: 匹配到的窗口句柄，未匹配/参数缺失返回None
        """
        if "title_re" not in self.uri_params:
            self.logger.debug("URI未配置title_re参数，跳过正则标题查找")
            return None

        import re
        pattern_str = self.uri_params["title_re"]
        if "*" in pattern_str and not (pattern_str.startswith(".*") or pattern_str.endswith(".*")):
            pattern_str = pattern_str.replace("*", ".*")

        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
        except re.error as e:
            self._record_error("_find_by_title_regex", f"正则表达式编译失败：{str(e)} | 表达式: {pattern_str}")
            self.logger.error(self.last_error, exc_info=True)
            return None

        def window_callback(hwnd, result_list):
            title = win32gui.GetWindowText(hwnd)
            if title and pattern.search(title):
                result_list.append(hwnd)
                return False
            return True

        match_results = []
        win32gui.EnumWindows(window_callback, match_results)
        return match_results[0] if match_results else None

    def _find_window_by_process_name(self, process_name: str) -> Optional[int]:
        """
        通过进程名查找关联的窗口句柄。
        
        Args:
            process_name: 目标进程名（如"BrownDust2.exe"）
            
        Returns:
            Optional[int]: 进程关联的窗口句柄，未找到/依赖缺失返回None
            
        Notes:
            需安装psutil库（pip install psutil），否则会跳过该策略
        """
        try:
            import psutil
            for proc in psutil.process_iter(["name", "pid"]):
                if proc.info["name"] and proc.info["name"].lower() == process_name.lower():
                    pid = proc.info["pid"]
                    self.logger.info(f"找到目标进程 | 名称: {process_name} | PID: {pid}")

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
            self._record_error("_find_window_by_process_name", f"进程名查找窗口异常：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
        return None

    def _enable_dpi_awareness(self) -> None:
        """
        启用进程DPI感知，优先使用Per-Monitor模式，降级使用系统级模式。
        
        Notes:
            启用DPI感知可避免高DPI屏幕下坐标偏移问题
        """
        try:
            shcore = ctypes.windll.shcore
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
            self.logger.error(f"启用Per-Monitor DPI感知失败: {str(e)}", exc_info=True)
            # 降级启用系统DPI感知
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                self.logger.debug("已启用系统级DPI感知模式")
            except Exception as e2:
                self.logger.error(f"所有DPI感知模式启用失败：{str(e2)}，可能导致坐标偏移", exc_info=True)

    def _get_dpi_for_window(self) -> float:
        """
        获取目标窗口的DPI缩放因子（标准DPI=96，缩放因子=窗口DPI/96）。
        
        Returns:
            float: DPI缩放因子（默认返回1.0）
        """
        if not self.hwnd:
            self.logger.warning("窗口句柄未初始化，返回默认DPI缩放因子1.0")
            return 1.0

        try:
            if hasattr(ctypes.windll.user32, "GetDpiForWindow"):
                window_dpi = ctypes.windll.user32.GetDpiForWindow(self.hwnd)
                if window_dpi > 0:
                    return window_dpi / 96.0
            system_dpi = ctypes.windll.user32.GetDpiForSystem()
            return system_dpi / 96.0
        except Exception as e:
            self._record_error("_get_dpi_for_window", f"获取DPI缩放因子异常：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            return 1.0

    def _get_screen_hardware_res(self) -> Tuple[int, int]:
        """
        获取物理屏幕分辨率（像素）。
        
        Returns:
            Tuple[int, int]: (宽度, 高度)，异常时返回默认值(1920, 1080)
        """
        try:
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            self.logger.debug(f"物理屏幕分辨率: {screen_width}x{screen_height}")
            return (screen_width, screen_height)
        except Exception as e:
            self._record_error("_get_screen_hardware_res", f"获取屏幕分辨率失败：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            return (1920, 1080)

    def _update_dynamic_window_info(self) -> bool:
        """
        更新窗口动态信息到display_context，包括尺寸、DPI、位置等。
        
        Returns:
            bool: 更新成功返回True，失败/窗口最小化返回False
        """
        try:
            if self.is_minimized():
                self.logger.debug("窗口处于最小化状态，跳过动态信息更新")
                return False

            window_rect = win32gui.GetWindowRect(self.hwnd)
            if all(coord == 0 for coord in window_rect):
                raise RuntimeError(f"获取窗口矩形失败，返回无效值: {window_rect}")

            dpi_scale = self._get_dpi_for_window()
            dpi_scale = max(1.0, dpi_scale)

            client_rect_phys = win32gui.GetClientRect(self.hwnd)
            client_w_phys = client_rect_phys[2] - client_rect_phys[0]
            client_h_phys = client_rect_phys[3] - client_rect_phys[1]
            if client_w_phys <= 0 or client_h_phys <= 0:
                raise RuntimeError(f"客户区物理尺寸无效: {client_w_phys}x{client_h_phys}")

            client_w_logic = int(round(client_w_phys / dpi_scale))
            client_h_logic = int(round(client_h_phys / dpi_scale))
            client_w_logic = max(800, client_w_logic)
            client_h_logic = max(600, client_h_logic)

            client_origin_x, client_origin_y = win32gui.ClientToScreen(self.hwnd, (0, 0))
            is_fullscreen = self.coord_transformer.is_fullscreen

            self.display_context.update_from_window(
                hwnd=self.hwnd,
                is_fullscreen=is_fullscreen,
                dpi_scale=dpi_scale,
                client_logical=(client_w_logic, client_h_logic),
                client_physical=(client_w_phys, client_h_phys),
                screen_physical=self._get_screen_hardware_res(),
                client_origin=(client_origin_x, client_origin_y),
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
            self._record_error("_update_dynamic_window_info", f"动态窗口信息更新失败：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            return False

    def _ensure_window_foreground(self) -> bool:
        """
        确保窗口处于前台激活状态，支持自动恢复最小化窗口、循环等待激活。
        
        Returns:
            bool: 窗口激活成功返回True，被停止信号中断返回False
        """
        current_time = time.time()
        foreground_hwnd = win32gui.GetForegroundWindow()

        # 已在前台，直接返回
        if foreground_hwnd == self.hwnd:
            self._last_activate_time = current_time
            self.logger.debug(f"窗口已在前台（句柄: {self.hwnd}），无需激活")
            self._update_dynamic_window_info()
            return True

        # 首次激活尝试
        if self._foreground_activation_allowed:
            self.logger.info(f"尝试激活窗口到前台（句柄: {self.hwnd}）")
            try:
                # 恢复最小化窗口
                if self.is_minimized():
                    self.logger.info("窗口处于最小化状态，正在恢复...")
                    win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                    time.sleep(self.WINDOW_RESTORE_DELAY)
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
                self._record_error("_ensure_window_foreground", f"激活窗口异常：{str(e)}")
                self.logger.error(self.last_error, exc_info=True)

            # 禁用重复激活，进入等待模式
            self._foreground_activation_allowed = False
            self.logger.info(f"每{self.FOREGROUND_CHECK_INTERVAL}秒检查一次前台状态")

        # 循环等待前台状态（支持中断）
        while True:
            if self.stop_event.is_set():
                self._record_error("_ensure_window_foreground", "窗口激活等待被停止信号中断")
                self.logger.info(self.last_error)
                return False

            if self.stop_event.wait(timeout=self.FOREGROUND_CHECK_INTERVAL):
                self._record_error("_ensure_window_foreground", "窗口激活等待被停止信号中断")
                self.logger.info(self.last_error)
                return False

            try:
                if win32gui.GetForegroundWindow() == self.hwnd:
                    self.logger.info("窗口已回到前台，激活成功")
                    self._update_dynamic_window_info()
                    return True
                self.logger.debug("窗口仍未在前台，继续等待...")
            except Exception as e:
                self._record_error("_ensure_window_foreground", f"检查前台窗口状态异常：{str(e)}")
                self.logger.error(self.last_error, exc_info=True)

        return False

    # -------------- 核心方法 --------------
    def connect(self, timeout: float = 10.0) -> bool:
        """
        连接Windows设备，查找并初始化目标窗口。
        
        Args:
            timeout: 连接超时时间（秒），默认10.0秒
            
        Returns:
            bool: 连接成功返回True，超时/被中断返回False
        """
        self.clear_last_error()
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # 检查停止信号
            if self.stop_event.is_set():
                self._record_error("connect", "连接被停止信号中断")
                self.logger.error(self.last_error)
                self._update_state(DeviceState.DISCONNECTED)
                return False

            # 查找窗口句柄
            self.hwnd = self._get_window_handle()
            if self.hwnd:
                # 初始化窗口基础属性
                self.window_class = win32gui.GetClassName(self.hwnd)
                _, self.process_id = win32process.GetWindowThreadProcessId(self.hwnd)
                screen_res = self._get_screen_hardware_res()

                # 初始化显示上下文
                self.display_context.original_base_width = self.display_context.original_base_width
                self.display_context.original_base_height = self.display_context.original_base_height
                self.display_context.hwnd = self.hwnd
                self.display_context.screen_physical_width, self.display_context.screen_physical_height = screen_res

                # 激活窗口
                self.set_foreground()
                time.sleep(0.5)

                # 验证窗口有效性
                if win32gui.IsWindow(self.hwnd) and win32gui.IsWindowVisible(self.hwnd):
                    self._update_state(DeviceState.CONNECTED)
                    self.logger.info(
                        f"Windows设备连接成功 | "
                        f"标题: {self.window_title} | 句柄: {self.hwnd} | "
                        f"类名: {self.window_class} | PID: {self.process_id} | "
                        f"屏幕分辨率: {screen_res}"
                    )
                    return True

            # 未找到窗口，重试间隔
            time.sleep(0.5)

        # 连接超时
        self._record_error("connect", f"连接超时（{timeout}秒），未找到匹配窗口")
        self.logger.error(self.last_error)
        self._update_state(DeviceState.DISCONNECTED)
        return False

    def disconnect(self) -> bool:
        """
        断开设备连接，清理窗口相关资源和状态。
        
        Returns:
            bool: 断开成功返回True，未连接返回True（无操作）
        """
        self.clear_last_error()
        if self.hwnd:
            self.logger.info(f"断开窗口连接 | 标题: {self.window_title} | 句柄: {self.hwnd}")

            # 重置显示上下文
            self.display_context.update_from_window(
                hwnd=None,
                is_fullscreen=False,
                dpi_scale=1.0,
                client_logical=(0, 0),
                client_physical=(0, 0),
                client_origin=(0, 0),
            )

            # 重置属性
            self.hwnd = None
            self.window_title = ""
            self.window_class = ""
            self.process_id = 0
            self._last_activate_time = 0.0
            self._foreground_activation_allowed = True
            
            # 更新状态
            self._update_state(DeviceState.DISCONNECTED)
            return True
        
        self.logger.debug("未连接到任何窗口，无需断开")
        return False

    def is_minimized(self) -> bool:
        """
        检查窗口是否处于最小化状态。
        
        Returns:
            bool: 最小化返回True，否则返回False（未连接时默认返回True）
        """
        if not self.hwnd:
            return True
        return win32gui.IsIconic(self.hwnd)

    def set_foreground(self) -> bool:
        """
        将窗口置为前台（激活窗口）。
        
        Returns:
            bool: 置前成功返回True，失败返回False
        """
        self.clear_last_error()
        return self._ensure_window_foreground()

    def get_resolution(self) -> Tuple[int, int]:
        """
        获取窗口客户区逻辑分辨率。
        
        Returns:
            Tuple[int, int]: (宽度, 高度)，未连接时返回(0, 0)
        """
        return self.display_context.client_logical_res

    def capture_screen(self, roi: Optional[Tuple[int, int, int, int]] = None) -> Optional[np.ndarray]:
        """
        捕获窗口/全屏截图，支持ROI区域裁剪，返回BGR格式numpy数组。
        
        Args:
            roi: 感兴趣区域，格式为(x, y, width, height)，None表示全屏/全窗口
            
        Returns:
            Optional[np.ndarray]: BGR格式截图数组，失败返回None
        """
        self.clear_last_error()
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

            # 全屏模式截图
            if is_fullscreen:
                cap_w, cap_h = self.display_context.screen_physical_res
                saveBitMap.CreateCompatibleBitmap(mfcDC, cap_w, cap_h)
                saveDC.SelectObject(saveBitMap)
                ctypes.windll.gdi32.BitBlt(saveDC.GetSafeHdc(), 0, 0, cap_w, cap_h, hdc_screen, 0, 0, win32con.SRCCOPY)
                self.logger.debug(f"全屏模式截图 | 尺寸: {cap_w}x{cap_h}")
            else:
                # 窗口模式截图
                cap_w, cap_h = client_w_phys, client_h_phys
                saveBitMap.CreateCompatibleBitmap(mfcDC, cap_w, cap_h)
                saveDC.SelectObject(saveBitMap)
                ctypes.windll.gdi32.BitBlt(
                    saveDC.GetSafeHdc(),
                    0,
                    0,
                    cap_w,
                    cap_h,
                    hdc_screen,
                    client_origin_x,
                    client_origin_y,
                    win32con.SRCCOPY,
                )
                self.logger.debug(f"窗口模式截图 | 客户区物理尺寸: {cap_w}x{cap_h}")

            # 位图转numpy数组（BGR格式）
            bmp_str = saveBitMap.GetBitmapBits(True)
            img_pil = Image.frombuffer("RGB", (cap_w, cap_h), bmp_str, "raw", "BGRX", 0, 1)
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
                    is_valid, err_msg = self.coord_transformer.validate_roi_format(roi)
                    if not is_valid:
                        self.logger.warning(f"全屏ROI无效: {err_msg}")
                    else:
                        limited_roi = self.coord_transformer.limit_rect_to_boundary(roi, cap_w, cap_h)
                        crop_x, crop_y, crop_w, crop_h = limited_roi
                        img_np = img_np[crop_y : crop_y + crop_h, crop_x : crop_x + crop_w]
                        self.logger.debug(f"全屏ROI裁剪 | 原始ROI: {roi} → 限制后: {limited_roi}")
                else:
                    screen_phys_rect = self.coord_transformer.convert_client_logical_rect_to_screen_physical(
                        roi, is_base_coord=True
                    )
                    if not screen_phys_rect:
                        self.logger.warning(f"窗口ROI转换失败: {roi}")
                    else:
                        phys_x, phys_y, phys_w, phys_h = screen_phys_rect
                        limited_roi = self.coord_transformer.limit_rect_to_boundary(
                            (phys_x, phys_y, phys_w, phys_h), cap_w, cap_h
                        )
                        crop_x, crop_y, crop_w, crop_h = limited_roi
                        if crop_w > 0 and crop_h > 0:
                            img_np = img_np[crop_y : crop_y + crop_h, crop_x : crop_x + crop_w]
                            self.logger.debug(f"窗口ROI裁剪 | 基准ROI: {roi} → 物理ROI: {limited_roi}")
                        else:
                            self.logger.warning(f"窗口ROI转换后无效: {roi} → 物理ROI: {screen_phys_rect}")

            return img_np
        except Exception as e:
            self._record_error("capture_screen", f"截图失败：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            return None

    @BaseDevice.require_operable
    def click(
        self,
        pos: Union[Tuple[int, int], str, List[str]],
        click_time: int = 1,
        duration: float = 0.1,
        right_click: bool = False,
        coord_type: CoordType = CoordType.LOGICAL,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> bool:
        """
        执行鼠标点击操作，支持直接坐标点击或模板匹配点击。
        
        Args:
            pos: 点击位置，支持三种格式：
                 - (x, y): 直接坐标（对应coord_type类型）
                 - str: 模板名称（模板匹配点击）
                 - list: 模板名称列表（多模板匹配，匹配到任一即点击）
            click_time: 点击次数，默认1次
            duration: 单次点击按住时长（秒），默认0.1秒
            right_click: 是否右键点击，默认False（左键）
            coord_type: 坐标类型（LOGICAL/PHYSICAL/BASE），默认LOGICAL
            roi: 模板匹配时的ROI区域，None表示全图
            
        Returns:
            bool: 点击成功返回True，失败返回False
        """
        # 激活窗口
        if not self._ensure_window_foreground():
            self._record_error("click", "无法激活窗口至前台")
            self.logger.error(self.last_error)
            return False

        time.sleep(0.1)
        target_pos: Optional[Tuple[int, int]] = None
        ctx = self.display_context
        click_source = "直接坐标"

        # 模板匹配点击
        if isinstance(pos, (str, list)):
            click_source = "模板匹配"
            screen_img = self.capture_screen()
            if screen_img is None:
                self._record_error("click", "截图失败，无法执行模板匹配")
                self.logger.error(self.last_error)
                return False

            # ROI预处理
            processed_roi = roi
            if roi:
                is_valid, err_msg = self.coord_transformer.validate_roi_format(roi)
                if not is_valid:
                    self.logger.warning(f"ROI预处理失败: {err_msg}，切换为全图匹配")
                    processed_roi = None
                else:
                    boundary_w, boundary_h = (
                        ctx.screen_physical_res if ctx.is_fullscreen else ctx.client_logical_res
                    )
                    processed_roi = self.coord_transformer.limit_rect_to_boundary(roi, boundary_w, boundary_h)
                    self.logger.debug(f"ROI预处理完成 | 原始: {roi} → 处理后: {processed_roi}")

            # 多模板匹配
            templates = [pos] if isinstance(pos, str) else pos
            matched_template = None
            match_result = None
            for template_name in templates:
                match_result = self.image_processor.match_template(
                    image=screen_img, template=template_name, threshold=0.6, roi=processed_roi
                )
                if match_result is not None:
                    matched_template = template_name
                    break

            if match_result is None:
                self._record_error("click", f"所有模板匹配失败: {templates}")
                self.logger.error(self.last_error)
                return False

            # 解析匹配结果
            match_rect = self.coord_transformer._convert_numpy_to_tuple(match_result)
            is_valid, err_msg = self.coord_transformer.validate_roi_format(match_rect)
            if not is_valid:
                self._record_error("click", f"模板匹配结果无效: {err_msg} | 模板: {matched_template}")
                self.logger.error(self.last_error)
                return False
            target_pos = self.coord_transformer.get_rect_center(match_rect)
            self.logger.debug(
                f"模板匹配成功 | 模板: {matched_template} | 匹配矩形: {match_rect} | 逻辑中心点: {target_pos}"
            )
            coord_type = CoordType.LOGICAL

        # 直接坐标点击
        else:
            target_pos = self.coord_transformer._convert_numpy_to_tuple(pos)
            if not isinstance(target_pos, tuple) or len(target_pos) != 2:
                self._record_error("click", f"点击坐标格式无效（需2元组）: {pos}")
                self.logger.error(self.last_error)
                return False
            x, y = target_pos
            if x < 0 or y < 0:
                self._record_error("click", f"点击坐标无效（非负）: ({x},{y})")
                self.logger.error(self.last_error)
                return False

        # 坐标转换
        x_target, y_target = target_pos
        logical_x, logical_y = 0, 0

        if coord_type == CoordType.PHYSICAL:
            logical_x, logical_y = x_target, y_target
            self.logger.debug(f"坐标类型：物理坐标 | 输入: ({x_target},{y_target})")
        elif coord_type == CoordType.BASE:
            logical_x, logical_y = self.coord_transformer.convert_original_to_current_client(x_target, y_target)
            self.logger.debug(f"基准坐标转换 | 基准: ({x_target},{y_target}) → 逻辑: ({logical_x},{logical_y})")
        else:
            logical_x, logical_y = x_target, y_target

        # 逻辑/物理坐标 → 屏幕坐标
        if ctx.is_fullscreen:
            screen_x, screen_y = logical_x, logical_y
            screen_w, screen_h = ctx.screen_physical_res
            screen_x = max(0, min(screen_x, screen_w - 1))
            screen_y = max(0, min(screen_y, screen_h - 1))
            self.logger.debug(
                f"全屏模式跳过坐标转换 | 最终点击坐标: ({screen_x},{screen_y}) | 屏幕边界: {screen_w}x{screen_h}"
            )
        else:
            if coord_type == CoordType.PHYSICAL:
                screen_x, screen_y = self.coord_transformer.convert_client_physical_to_screen_physical(
                    logical_x, logical_y
                )
                self.logger.debug(
                    f"窗口模式物理坐标转换 | 物理: ({logical_x},{logical_y}) → 屏幕: ({screen_x},{screen_y})"
                )
            else:
                screen_x, screen_y = self.coord_transformer.convert_client_logical_to_screen_physical(
                    logical_x, logical_y
                )
                self.logger.debug(
                    f"窗口模式逻辑坐标转换 | 逻辑: ({logical_x},{logical_y}) → 屏幕: ({screen_x},{screen_y})"
                )

        # 执行鼠标点击
        win32api.SetCursorPos((screen_x, screen_y))
        time.sleep(0.05)

        mouse_down = win32con.MOUSEEVENTF_RIGHTDOWN if right_click else win32con.MOUSEEVENTF_LEFTDOWN
        mouse_up = win32con.MOUSEEVENTF_RIGHTUP if right_click else win32con.MOUSEEVENTF_LEFTUP

        for i in range(click_time):
            if i > 0:
                time.sleep(0.1)
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

    @BaseDevice.require_operable
    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.3,
        steps: int = 10,
        coord_type: CoordType = CoordType.LOGICAL,
    ) -> bool:
        """
        执行鼠标滑动操作，从起始坐标平滑滑动到结束坐标。
        
        Args:
            start_x: 滑动起始点X坐标
            start_y: 滑动起始点Y坐标
            end_x: 滑动结束点X坐标
            end_y: 滑动结束点Y坐标
            duration: 滑动总时长（秒），默认0.3秒
            steps: 滑动步数（越大越平滑），默认10步
            coord_type: 坐标类型（LOGICAL/PHYSICAL/BASE），默认LOGICAL
            
        Returns:
            bool: 滑动成功返回True，失败返回False
        """
        # 激活窗口
        if not self._ensure_window_foreground():
            self._record_error("swipe", "无法激活窗口至前台")
            self.logger.error(self.last_error)
            return False

        time.sleep(0.1)
        start_pos = (start_x, start_y)
        end_pos = (end_x, end_y)

        # 坐标类型转换
        if coord_type == CoordType.BASE:
            start_pos = self.coord_transformer.convert_original_to_current_client(*start_pos)
            end_pos = self.coord_transformer.convert_original_to_current_client(*end_pos)
            self.logger.debug(f"基准坐标转换 | 起始: {start_pos} → 结束: {end_pos}")
        elif coord_type == CoordType.PHYSICAL:
            start_pos = self.coord_transformer.convert_client_physical_to_logical(*start_pos)
            end_pos = self.coord_transformer.convert_client_physical_to_logical(*end_pos)
            self.logger.debug(f"物理坐标转换 | 起始: {start_pos} → 结束: {end_pos}")

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

        self.logger.info(f"滑动成功 | 逻辑坐标: {start_pos} → {end_pos} | 时长: {duration}s | 步数: {steps}")
        return True

    @BaseDevice.require_operable
    def key_press(self, key: str, duration: float = 0.1) -> bool:
        """
        执行键盘按键操作，按下并释放指定按键。
        
        Args:
            key: 按键名称（如"enter"、"space"、"ctrl"，参考pydirectinput键名）
            duration: 按键按住时长（秒），默认0.1秒
            
        Returns:
            bool: 按键成功返回True，失败返回False
        """
        # 激活窗口
        if not self._ensure_window_foreground():
            self._record_error("key_press", "无法激活窗口至前台")
            self.logger.error(self.last_error)
            return False

        time.sleep(0.1)
        # 执行按键
        pydirectinput.keyDown(key)
        time.sleep(duration)
        pydirectinput.keyUp(key)

        self.logger.info(f"按键成功 | 按键: {key} | 按住时长: {duration}s")
        return True

    @BaseDevice.require_operable
    def text_input(self, text: str, interval: float = 0.05) -> bool:
        """
        输入指定文本，长文本（>5字符）自动使用粘贴，短文本逐字符输入。
        
        Args:
            text: 待输入的文本内容
            interval: 逐字符输入时的间隔时间（秒），默认0.05秒
            
        Returns:
            bool: 输入成功返回True，失败返回False
            
        Notes:
            长文本粘贴依赖pyperclip库（pip install pyperclip）
        """
        # 激活窗口
        if not self._ensure_window_foreground():
            self._record_error("text_input", "无法激活窗口至前台")
            self.logger.error(self.last_error)
            return False

        time.sleep(0.1)
        # 长文本粘贴
        if len(text) > 5:
            try:
                import pyperclip
                pyperclip.copy(text)
                # 执行Ctrl+V粘贴
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                win32api.keybd_event(ord("V"), 0, 0, 0)
                time.sleep(0.05)
                win32api.keybd_event(ord("V"), 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(0.1)
                log_text = text[:20] + "..." if len(text) > 20 else text
                self.logger.info(f"文本粘贴成功 | 内容: {log_text} | 长度: {len(text)}")
                return True
            except Exception as e:
                self._record_error("text_input", f"文本粘贴失败：{str(e)}")
                self.logger.error(self.last_error, exc_info=True)
                return False

        # 短文本逐字符输入
        try:
            for char in text:
                if char == " ":
                    self.key_press("space", 0.02)
                elif char == "\n":
                    self.key_press("enter", 0.02)
                elif char == "\t":
                    self.key_press("tab", 0.02)
                else:
                    shift_required = char.isupper() or char in '~!@#$%^&*()_+{}|:"<>?'
                    if shift_required:
                        win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
                    win32api.keybd_event(ord(char.upper()), 0, 0, 0)
                    time.sleep(0.02)
                    win32api.keybd_event(ord(char.upper()), 0, win32con.KEYEVENTF_KEYUP, 0)
                    if shift_required:
                        win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)
                    time.sleep(interval)
            self.logger.info(f"文本输入成功 | 内容: {text}")
            return True
        except Exception as e:
            self._record_error("text_input", f"文本逐字符输入失败：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            return False

    def exists(
        self,
        template_name: Union[str, List[str]],
        threshold: float = 0.8,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[Tuple[int, int]]:
        """
        检查指定模板是否存在，返回匹配到的模板中心点坐标。
        
        Args:
            template_name: 模板名称（str）或模板列表（list）
            threshold: 模板匹配阈值（0-1），默认0.8
            roi: 模板匹配的ROI区域，None表示全图
            
        Returns:
            Optional[Tuple[int, int]]: 匹配到的中心点坐标，未匹配/失败返回None
        """
        self.clear_last_error()
        try:
            if not self.hwnd:
                self._record_error("exists", "设备未连接")
                self.logger.error(self.last_error)
                return None

            # 尝试激活窗口（不强制，失败仅警告）
            if not self._ensure_window_foreground():
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
                    image=screen_img, template=template, threshold=threshold, roi=processed_roi
                )
                if match_result is not None:
                    # 解析匹配结果
                    match_rect = self.coord_transformer._convert_numpy_to_tuple(match_result)
                    center_pos = self.coord_transformer.get_rect_center(match_rect)
                    center_pos = tuple(map(int, center_pos))
                    self.logger.info(f"模板找到 | 名称: {template} | 匹配矩形: {match_rect} | 逻辑中心点: {center_pos}")
                    return center_pos

            self.logger.debug(f"所有模板未找到: {templates}")
            return None
        except Exception as e:
            self._record_error("exists", f"模板检查异常：{str(e)}")
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
        等待指定模板出现，超时未出现返回None。
        
        Args:
            template_name: 模板名称（str）或模板列表（list）
            timeout: 等待超时时间（秒），默认10.0秒
            interval: 模板检查间隔（秒），默认0.5秒
            roi: 模板匹配的ROI区域，None表示全图
            
        Returns:
            Optional[Tuple[int, int]]: 匹配到的中心点坐标，超时/中断返回None
        """
        self.clear_last_error()
        start_time = time.time()
        templates = [template_name] if isinstance(template_name, str) else template_name
        self.logger.info(f"开始等待模板 | 列表: {templates} | 超时: {timeout}s | 检查间隔: {interval}s | ROI: {roi}")

        while time.time() - start_time < timeout:
            # 检查停止信号
            if self.stop_event.is_set():
                self._record_error("wait", "模板等待被停止信号中断")
                self.logger.info(self.last_error)
                return None

            center_pos = self.exists(templates, threshold=0.8, roi=roi)
            if center_pos is not None:
                elapsed_time = time.time() - start_time
                self.logger.info(f"模板等待成功 | 列表: {templates} | 耗时: {elapsed_time:.1f}s | 中心点: {center_pos}")
                return center_pos

            # 等待检查间隔（支持中断）
            if self.stop_event.wait(timeout=interval):
                self._record_error("wait", "模板等待被停止信号中断")
                self.logger.info(self.last_error)
                return None

        self._record_error("wait", f"模板等待超时（{timeout}s）| 列表: {templates}")
        self.logger.error(self.last_error)
        return None

    def get_state(self) -> DeviceState:
        """
        获取设备当前状态，对齐基类状态定义。
        
        Returns:
            DeviceState: 设备状态枚举值（DISCONNECTED/CONNECTED/BUSY/ERROR）
        """
        if not self.hwnd:
            return DeviceState.DISCONNECTED

        try:
            if not win32gui.IsWindow(self.hwnd):
                self.hwnd = None
                return DeviceState.DISCONNECTED
            if not win32gui.IsWindowVisible(self.hwnd):
                return DeviceState.DISCONNECTED
            return self.state
        except Exception as e:
            self._record_error("get_state", f"获取设备状态异常：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            return DeviceState.ERROR