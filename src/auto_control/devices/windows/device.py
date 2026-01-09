import time
from threading import Event
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import win32api
import win32con
import win32gui
import win32process

from src.auto_control.devices.base_device import BaseDevice, DeviceState
from src.auto_control.image.image_processor import ImageProcessor
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.display_context import RuntimeDisplayContext

from .constants import CoordType
from .input_controller import InputController
from .screenshot_manager import ScreenshotManager
from .window_manager import WindowManager


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
    7. 智能截图：支持多种截图策略，可独立配置截图模式
    8. 鼠标复位：点击/滑动操作自动记录并恢复鼠标原始位置
    9. 模式分离：截图模式和点击模式独立配置
    """

    def __init__(
        self,
        device_uri: str,
        logger,
        image_processor: ImageProcessor,
        coord_transformer: CoordinateTransformer,
        display_context: RuntimeDisplayContext,
        stop_event: Event,
        settings_manager=None,
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
            settings_manager: 设置管理器实例（保留参数以兼容）

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
        self.settings_manager = settings_manager

        # 窗口基础属性
        self.hwnd: Optional[int] = None
        self.window_title: str = ""
        self.window_class: str = ""
        self.process_id: int = 0

        # 窗口激活状态缓存
        self._last_activate_time = 0.0
        self._foreground_activation_allowed = True

        # 截图策略与模式（核心修改）
        self._best_screenshot_strategy: Optional[str] = None  # printwindow/bitblt/dxcam/temp_foreground
        self._screenshot_mode: Optional[str] = None  # 截图模式：foreground/background 或具体方法名称
        self._click_mode: Optional[str] = None  # 点击模式：foreground/background
        self._original_topmost_state: Optional[bool] = None  # 保留以兼容现有代码

        self._last_activate_attempt = 0.0
        self.ACTIVATE_RETRY_COOLDOWN = 1.0

        # 解析URI参数
        self.uri_params = self._parse_uri(device_uri)
        self.logger.debug(f"Windows设备URI解析结果: {self.uri_params}")

        # 初始化子模块
        self.window_manager = WindowManager(self)
        self.screenshot_manager = ScreenshotManager(self)
        self.input_controller = InputController(self)

        # 同步hwnd属性，确保device.hwnd与window_manager.hwnd保持一致
        self.hwnd = self.window_manager.hwnd

    def _parse_uri(self, uri: str) -> Dict[str, str]:
        """
        解析设备URI，提取参数。

        Args:
            uri: 设备URI

        Returns:
            Dict[str, str]: 解析后的参数字典
        """
        params = {}
        if "://" in uri:
            _, query = uri.split("://", 1)
            for part in query.split("&"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    params[key.lower()] = value
        return params

    def _get_screen_hardware_res(self) -> Tuple[int, int]:
        """
        获取屏幕硬件分辨率。

        Returns:
            Tuple[int, int]: 屏幕硬件分辨率（宽, 高）
        """
        # 优先使用 display_context 中已存储的值
        if self.display_context.screen_physical_width > 0 and self.display_context.screen_physical_height > 0:
            screen_res = (self.display_context.screen_physical_width, self.display_context.screen_physical_height)
            self.logger.debug(f"使用已存储的物理屏幕分辨率: {screen_res[0]}x{screen_res[1]}")
            return screen_res

        # 否则重新获取
        try:
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            self.logger.debug(f"获取物理屏幕分辨率: {screen_width}x{screen_height}")
            return (screen_width, screen_height)
        except Exception as e:
            self.logger.error(f"获取屏幕分辨率失败：{str(e)}", exc_info=True)
            return (1920, 1080)

    def _update_dynamic_window_info(self) -> bool:
        """
        更新窗口动态信息。

        Returns:
            bool: 更新成功返回True，失败返回False
        """
        try:
            if not self.window_manager.hwnd:
                self.logger.debug("窗口句柄为None，跳过动态信息更新")
                return False

            if self.window_manager.is_minimized():
                self.logger.debug("窗口处于最小化状态，跳过动态信息更新")
                return False

            window_rect = win32gui.GetWindowRect(self.window_manager.hwnd)
            self.logger.debug(f"窗口矩形: {window_rect}")
            if all(coord == 0 for coord in window_rect):
                raise RuntimeError(f"获取窗口矩形失败，返回无效值: {window_rect}")

            dpi_scale = self.window_manager._get_dpi_for_window()
            dpi_scale = max(1.0, dpi_scale)

            client_rect_phys = win32gui.GetClientRect(self.window_manager.hwnd)
            self.logger.debug(f"客户区矩形: {client_rect_phys}")
            client_w_phys = client_rect_phys[2] - client_rect_phys[0]
            client_h_phys = client_rect_phys[3] - client_rect_phys[1]
            self.logger.debug(f"客户区物理尺寸: {client_w_phys}x{client_h_phys}")

            # 如果客户区尺寸无效，使用窗口矩形尺寸作为兜底
            if client_w_phys <= 0 or client_h_phys <= 0:
                self.logger.warning(f"客户区物理尺寸无效({client_w_phys}x{client_h_phys})，使用窗口矩形尺寸作为兜底")
                client_w_phys = window_rect[2] - window_rect[0]
                client_h_phys = window_rect[3] - window_rect[1]
                self.logger.debug(f"兜底客户区物理尺寸: {client_w_phys}x{client_h_phys}")

            client_w_logic = int(round(client_w_phys / dpi_scale))
            client_h_logic = int(round(client_h_phys / dpi_scale))
            client_w_logic = max(800, client_w_logic)
            client_h_logic = max(600, client_h_logic)

            client_origin_x, client_origin_y = win32gui.ClientToScreen(self.window_manager.hwnd, (0, 0))
            screen_res = self._get_screen_hardware_res()

            # 先更新display_context，包括hwnd，避免全屏判定时hwnd为None
            self.display_context.update_from_window(
                hwnd=self.window_manager.hwnd,
                is_fullscreen=False,  # 先设置默认值
                dpi_scale=dpi_scale,
                client_logical=(client_w_logic, client_h_logic),
                client_physical=(client_w_phys, client_h_phys),
                screen_physical=screen_res,
                client_origin=(client_origin_x, client_origin_y),
            )

            # 现在display_context已经有hwnd了，可以安全地获取is_fullscreen
            is_fullscreen = self.coord_transformer.is_fullscreen
            previous_fullscreen = self.display_context.is_fullscreen
            if is_fullscreen != previous_fullscreen:
                self.logger.info(
                    f"窗口显示模式变化: {'全屏' if is_fullscreen else '窗口'} (之前: {'全屏' if previous_fullscreen else '窗口'})"
                )
                # 更新display_context的is_fullscreen属性
                self.display_context.is_fullscreen = is_fullscreen

            self.logger.debug(
                f"窗口动态信息更新完成 | "
                f"模式: {'全屏' if is_fullscreen else '窗口'} | "
                f"逻辑尺寸: {client_w_logic}x{client_h_logic} | "
                f"物理尺寸: {client_w_phys}x{client_h_phys} | "
                f"屏幕分辨率: {screen_res[0]}x{screen_res[1]} | "
                f"DPI缩放: {dpi_scale:.2f} | "
                f"屏幕原点: ({client_origin_x},{client_origin_y})"
            )
            return True
        except Exception as e:
            self.logger.error(f"动态窗口信息更新失败：{str(e)}", exc_info=True)
            return False

    def connect(self, timeout: float = 10.0) -> bool:
        """
        连接Windows设备，初始化窗口控制环境。

        核心功能：
        - 查找并验证目标窗口
        - 检测最优截图策略
        - 初始化截图模式和点击模式
        - 更新设备状态为已连接

        Args:
            timeout: 连接超时时间（秒）

        Returns:
            bool: 连接成功返回True，失败返回False
        """
        self.clear_last_error()
        start_time = time.time()
        last_find_time = 0
        find_interval = 2.0  # 窗口查找间隔，避免频繁查找
        found_once = False  # 标记是否已经找到过窗口

        while time.time() - start_time < timeout:
            if self.stop_event.is_set():
                self._record_error("connect", "连接被停止信号中断")
                self.logger.error(self.last_error)
                self._update_state(DeviceState.DISCONNECTED)
                return False

            current_time = time.time()

            # 只有当距离上次查找超过指定间隔，或者还没有找到过窗口时，才进行查找
            if current_time - last_find_time >= find_interval or not found_once:
                self.window_manager.hwnd = self.window_manager._get_window_handle()
                if self.window_manager.hwnd:
                    found_once = True
                    last_find_time = current_time
                    self.window_manager.window_class = win32gui.GetClassName(self.window_manager.hwnd)
                    _, self.window_manager.process_id = win32process.GetWindowThreadProcessId(self.window_manager.hwnd)

                    # 直接调用 update_from_window 方法更新所有窗口信息
                    self._update_dynamic_window_info()

                    # 检测截图策略
                    self.screenshot_manager._best_screenshot_strategy = (
                        self.screenshot_manager._detect_best_screenshot_strategy()
                    )

                    # 初始化点击模式（默认foreground）
                    if not self._click_mode:
                        self._click_mode = "foreground"

                    # 初始化截图模式
                    if not self.screenshot_manager._screenshot_mode:
                        self.screenshot_manager._screenshot_mode = self.screenshot_manager._best_screenshot_strategy
            elif self.window_manager.hwnd:
                # 已找到窗口，只更新窗口状态，不重新查找
                self._update_dynamic_window_info()

            if self.window_manager.hwnd:
                # 如果窗口最小化，尝试恢复
                if self.window_manager.is_minimized():
                    self.logger.info(f"窗口处于最小化状态，尝试恢复 | 句柄: {self.window_manager.hwnd}")
                    win32gui.ShowWindow(self.window_manager.hwnd, win32con.SW_RESTORE)
                    time.sleep(self.window_manager.WINDOW_RESTORE_DELAY)

                # 检查窗口是否已经在前台
                if win32gui.GetForegroundWindow() != self.window_manager.hwnd:
                    # 根据模式处理激活逻辑
                    if self.screenshot_manager._best_screenshot_strategy == "printwindow":
                        # 后台模式：自动激活
                        self.logger.info("后台模式，自动激活窗口")
                        if not self.window_manager._activate_window(temp_activation=True):
                            self.logger.warning("后台模式窗口激活失败")
                        else:
                            self.logger.info("后台模式窗口激活成功")
                    else:
                        # 前台模式：首次连接时不自动激活，等待用户手动激活
                        self.logger.info("前台模式，窗口已恢复，等待用户手动激活到前台")
                else:
                    self.logger.debug("窗口已在前台，无需激活")

                # 检查窗口状态，只要窗口存在即可连接（如果最小化已尝试恢复）
                if win32gui.IsWindow(self.window_manager.hwnd):
                    # 同步hwnd属性，确保device.hwnd与window_manager.hwnd保持一致
                    self.hwnd = self.window_manager.hwnd
                    self._update_state(DeviceState.CONNECTED)
                    self.logger.info(
                        f"Windows设备连接成功 | "
                        f"标题: {self.window_manager.window_title} | 句柄: {self.window_manager.hwnd} | "
                        f"类名: {self.window_manager.
                    window_class} | PID: {self.window_manager.process_id} | "
                        f"截图策略: {self.screenshot_manager._best_screenshot_strategy} | 截图模式: {self.screenshot_manager._screenshot_mode} | "
                        f"点击模式: {self._click_mode}"
                    )
                    return True
                elif current_time - last_find_time < 1.0:  # 只在刚找到窗口时记录一次警告
                    self.logger.warning(f"窗口状态不满足连接条件，句柄: {self.window_manager.hwnd}")

            time.sleep(0.5)

        self._record_error("connect", f"连接超时（{timeout}秒），未找到匹配窗口")
        self.logger.error(self.last_error)
        self._update_state(DeviceState.DISCONNECTED)
        return False

    def disconnect(self) -> bool:
        """
        断开设备连接，清理窗口控制环境。

        核心功能：
        - background模式下：恢复窗口原始置顶状态
        - 重置显示上下文
        - 重置所有窗口相关属性
        - 更新设备状态为已断开

        Returns:
            bool: 断开成功返回True
        """
        self.clear_last_error()

        if self.window_manager.hwnd:
            self.logger.info(
                f"断开窗口连接 | 标题: {self.window_manager.window_title} | 句柄: {self.window_manager.hwnd}"
            )

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
            self.window_manager.hwnd = None
            self.window_manager.window_title = ""
            self.window_manager.window_class = ""
            self.window_manager.process_id = 0
            self._last_activate_time = 0.0
            self._foreground_activation_allowed = True
            self.screenshot_manager._best_screenshot_strategy = None
            self.screenshot_manager._screenshot_mode = None
            self._click_mode = None

            self._update_state(DeviceState.DISCONNECTED)
            return True

        self.logger.debug("未连接到任何窗口，无需断开")
        return True

    def is_minimized(self) -> bool:
        """
        检查窗口是否处于最小化状态。

        Returns:
            bool: 最小化返回True，否则返回False
        """
        return self.window_manager.is_minimized()

    # -------------------------- 核心功能方法 --------------------------
    def capture_screen(self, roi: Optional[Tuple[int, int, int, int]] = None) -> Optional[np.ndarray]:
        """
        屏幕截图，支持多种截图策略和ROI裁剪。

        Args:
            roi: 可选，感兴趣区域，格式为(x, y, width, height)

        Returns:
            Optional[np.ndarray]: 截图图像（BGR格式），失败返回None
        """
        return self.screenshot_manager.capture_screen(roi)

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
        执行鼠标点击操作。

        Args:
            pos: 点击位置，可以是坐标元组、模板名称或模板名称列表
            click_time: 点击次数
            duration: 点击持续时间（秒）
            right_click: 是否为右键点击
            coord_type: 坐标类型
            roi: 可选，感兴趣区域，用于模板匹配

        Returns:
            bool: 操作成功返回True，否则返回False
        """
        return self.input_controller.click(pos, click_time, duration, right_click, coord_type, roi)

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
        执行鼠标滑动操作。

        Args:
            start_x: 起始X坐标
            start_y: 起始Y坐标
            end_x: 结束X坐标
            end_y: 结束Y坐标
            duration: 滑动持续时间（秒）
            steps: 滑动步数
            coord_type: 坐标类型

        Returns:
            bool: 操作成功返回True，否则返回False
        """
        return self.input_controller.swipe(start_x, start_y, end_x, end_y, duration, steps, coord_type)

    def key_press(self, key: str, duration: float = 0.1) -> bool:
        """
        执行键盘按键操作。

        Args:
            key: 按键名称
            duration: 按键持续时间（秒）

        Returns:
            bool: 操作成功返回True，否则返回False
        """
        return self.input_controller.key_press(key, duration)

    def _ensure_window_foreground(self, max_attempts: int = 3) -> bool:
        """
        确保窗口在前台，最多尝试指定次数。

        Args:
            max_attempts: 最大尝试次数

        Returns:
            bool: 成功返回True，否则返回False
        """
        current_time = time.time()
        foreground_hwnd = win32gui.GetForegroundWindow()

        # 检查窗口句柄是否有效
        if not self.window_manager.hwnd:
            self.logger.warning("窗口句柄无效，无法确保窗口在前台")
            return False

        # 检查窗口是否已在前台
        if self.window_manager._is_window_ready() and foreground_hwnd == self.window_manager.hwnd:
            self._last_activate_time = current_time
            self.logger.debug(f"窗口已在前台（句柄: {self.window_manager.hwnd}），无需激活")
            # 窗口已在前台且状态就绪，无需更新动态信息
            return True

        # 前台模式：不自动激活，等待用户手动操作
        if self.screenshot_manager._best_screenshot_strategy != "printwindow":
            self.logger.debug(f"前台模式，等待用户手动激活窗口 | 句柄: {self.window_manager.hwnd}")
            # 前台模式下，只要窗口未最小化且存在，就返回True
            return self.window_manager._is_window_ready()

        # 后台模式：执行正常激活逻辑
        if current_time - self._last_activate_attempt < self.ACTIVATE_RETRY_COOLDOWN:
            self.logger.debug(
                f"激活操作冷却中（剩余{self.ACTIVATE_RETRY_COOLDOWN - (current_time - self._last_activate_attempt):.1f}秒）"
            )
            return False
        self._last_activate_attempt = current_time

        self.logger.info(f"开始激活窗口（最多{max_attempts}次尝试）| 句柄: {self.window_manager.hwnd}")
        if self.window_manager._activate_window(temp_activation=False, max_attempts=max_attempts):
            self._last_activate_time = current_time

            self._update_dynamic_window_info()
            return True
        else:
            self._record_error(
                "_ensure_window_foreground", f"窗口激活失败（已尝试{max_attempts}次），可能被遮挡/权限不足"
            )
            self.logger.info(self.last_error)
            return False

    @BaseDevice.require_operable
    def text_input(self, text: str, interval: float = 0.05) -> bool:
        """
        输入指定文本，长文本（>5字符）自动使用粘贴，短文本逐字符输入。

        Args:
            text: 待输入的文本内容
            interval: 逐字符输入时的间隔时间（秒），默认0.05秒

        Returns:
            bool: 输入成功返回True，失败返回False
        """
        # 记录原始前台窗口，仅在background模式下恢复
        original_foreground_hwnd = None
        if self._click_mode == "background":
            original_foreground_hwnd = self.window_manager._get_original_foreground()

        # 激活目标窗口
        activate_success = self._ensure_window_foreground(max_attempts=3)
        if not activate_success:
            self._record_error("text_input", "无法激活窗口至前台")
            self.logger.error(self.last_error)
            # background模式下恢复原始前台窗口
            if original_foreground_hwnd and win32gui.IsWindow(original_foreground_hwnd):
                self.window_manager._restore_foreground(original_foreground_hwnd)
            return False

        # 模式适配：临时置顶（background点击模式生效，foreground点击模式跳过）
        temp_topmost_success = self.window_manager._set_window_temp_topmost()

        time.sleep(0.1)
        input_success = True
        try:
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
                except Exception as e:
                    self._record_error("text_input", f"文本粘贴失败：{str(e)}")
                    self.logger.error(self.last_error, exc_info=True)
                    input_success = False
            else:
                # 短文本逐字符输入
                for char in text:
                    if self.stop_event.is_set():
                        raise RuntimeError("文本输入被停止信号中断")
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
        except Exception as e:
            self._record_error("text_input", f"文本逐字符输入失败：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            input_success = False
        finally:
            # 模式适配：恢复置顶状态（仅background点击模式生效）
            self.window_manager._restore_window_original_topmost()

        if input_success:
            # 仅在background模式下且操作成功时恢复原始前台窗口
            if (
                self._click_mode == "background"
                and original_foreground_hwnd
                and win32gui.IsWindow(original_foreground_hwnd)
            ):
                self.window_manager._restore_foreground(original_foreground_hwnd)
            # foreground模式下保持目标窗口在前台
        return input_success

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
            if not self.window_manager.hwnd:
                self._record_error("exists", "设备未连接")
                self.logger.error(self.last_error)
                return None

            # 根据截图模式选择对应截图策略
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
            self.logger.debug(
                f"模板检查 | 模板列表: {templates} | 阈值: {threshold} | ROI: {processed_roi} | 截图模式: {self._screenshot_mode} | 点击模式: {self._click_mode}"
            )

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

    # -------------------------- 属性访问器 --------------------------
    @property
    def is_connected(self) -> bool:
        """
        检查设备是否已连接。

        Returns:
            bool: 已连接返回True，否则返回False
        """
        return self.state == DeviceState.CONNECTED and self.window_manager._is_window_ready()

    @property
    def is_operable(self) -> bool:
        """
        检查设备是否可操作。

        Returns:
            bool: 可操作返回True，否则返回False
        """
        return self.is_connected

    def get_state(self) -> DeviceState:
        """
        获取设备当前状态，对齐基类状态定义。

        Returns:
            DeviceState: 设备状态枚举值（DISCONNECTED/CONNECTED/BUSY/ERROR）
        """
        if not self.window_manager.hwnd:
            return DeviceState.DISCONNECTED

        try:
            if not win32gui.IsWindow(self.window_manager.hwnd):
                self.logger.warning(f"窗口句柄无效: {self.window_manager.hwnd}，需要重新连接")
                # 不直接设置hwnd为None，让上层决定如何处理
                return DeviceState.DISCONNECTED

            # 窗口被遮挡时，只记录日志，不返回DISCONNECTED
            if not win32gui.IsWindowVisible(self.window_manager.hwnd):
                self.logger.info(f"窗口被遮挡: {self.window_manager.hwnd}")
                # 窗口被遮挡时仍然返回CONNECTED，因为窗口并没有关闭
                return self.state

            # 简化：仅检查窗口激活状态，不再检查置顶状态
            is_foreground = win32gui.GetForegroundWindow() == self.window_manager.hwnd
            if self._screenshot_mode == "foreground" and not is_foreground:
                self.logger.info("foreground截图模式窗口不在前台，可能影响截图效果")

            return self.state
        except Exception as e:
            self._record_error("get_state", f"获取设备状态异常：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            return DeviceState.ERROR

    @property
    def available_screenshot_methods(self) -> List[str]:
        """
        获取所有可用的截图方法列表，用于UI展示。

        Returns:
            List[str]: 可用截图方法列表
        """
        return self._available_screenshot_methods.copy()

    @property
    def current_screenshot_method(self) -> Optional[str]:
        """
        获取当前使用的截图方法，用于UI展示。

        Returns:
            Optional[str]: 当前截图方法名称
        """
        return self._best_screenshot_strategy
