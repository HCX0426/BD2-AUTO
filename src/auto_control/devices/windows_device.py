import ctypes
import time
from enum import Enum, auto
from threading import Event, Lock, Thread
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
    7. 智能截图：支持多种截图策略，可独立配置截图模式
    8. 鼠标复位：点击/滑动操作自动记录并恢复鼠标原始位置
    9. 模式分离：截图模式和点击模式独立配置

    全屏/窗口模式处理：
    - 全屏模式：自动检测窗口是否全屏显示，使用屏幕分辨率作为基准
    - 坐标处理：全屏模式下逻辑坐标直接映射到物理屏幕坐标，无需DPI缩放
    - 截图策略：全屏模式支持所有截图方法，根据性能自动选择
    - ROI裁剪：全屏模式下直接使用屏幕物理坐标进行裁剪
    - 点击操作：全屏模式下逻辑坐标直接转换为屏幕物理坐标

    截图模式：
    - printwindow：后台截图，无需窗口置顶
    - bitblt：前台截图，临时激活窗口
    - dxcam：硬件加速截图，临时激活窗口
    - temp_foreground：临时激活窗口截图

    点击模式：
    - foreground：点击时窗口保持激活状态
    - background：点击时临时激活窗口，点击后恢复
    """

    # 窗口操作延迟配置
    WINDOW_RESTORE_DELAY = 0.5
    WINDOW_ACTIVATE_DELAY = 0.1
    ACTIVATE_COOLDOWN = 5.0
    FOREGROUND_CHECK_INTERVAL = 5.0
    # 新增：临时置顶截图延迟（视觉无感知）
    TEMP_FOREGROUND_DELAY = 0.1
    # 新增：临时置顶生效延迟（确保窗口稳定置顶）
    TEMP_TOPMOST_DELAY = 0.05
    # 置顶检查间隔（秒）
    TOPMOST_CHECK_INTERVAL = 3.0

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
        self._available_screenshot_methods: List[str] = []  # 所有可用的截图方法列表

        # 临时置顶相关状态
        self._original_window_ex_style: Optional[int] = None
        self._is_temp_topmost = False

        # 解析URI参数
        self.uri_params = self._parse_uri(device_uri)
        self.logger.debug(f"Windows设备URI解析结果: {self.uri_params}")

        self._last_activate_attempt = 0.0
        self.ACTIVATE_RETRY_COOLDOWN = 1.0

        self._topmost_lock = Lock()

        # 启用DPI感知
        self._enable_dpi_awareness()

    # -------------- 修改：简化foreground模式置顶检查方法 --------------
    def _check_topmost_status(self):
        """
        foreground模式专用：后台线程持续检查窗口状态，未激活则记录日志。
        每3秒检查一次，直到stop_event触发或窗口断开。
        """
        self.logger.info(f"foreground模式状态检查线程启动 | 检查间隔: {self.TOPMOST_CHECK_INTERVAL}秒")
        # 新增：定义停止事件
        self._topmost_check_stop = Event()

        while not self.stop_event.is_set() and not self._topmost_check_stop.is_set():
            try:
                if not self.hwnd or not win32gui.IsWindow(self.hwnd):
                    self.logger.warning("窗口句柄无效，退出状态检查线程")
                    break

                # 检查当前窗口是否在前台
                is_foreground = win32gui.GetForegroundWindow() == self.hwnd

                if is_foreground:
                    self.logger.debug("foreground模式窗口激活状态正常")
                else:
                    self.logger.info("foreground模式窗口不在前台，可能影响截图效果")

                # 等待检查间隔（支持中断）
                if self.stop_event.wait(timeout=self.TOPMOST_CHECK_INTERVAL):
                    break
            except Exception as e:
                self.logger.error(f"foreground模式状态检查异常: {e}", exc_info=True)
                # 异常后等待1秒再重试，避免频繁报错
                time.sleep(1.0)

        self.logger.info("foreground模式状态检查线程退出")

    # -------------- 新增：统一的窗口激活方法 --------------
    def _activate_window(self, temp_activation: bool = False, max_attempts: int = 1) -> bool:
        """
        统一的窗口激活方法，支持临时激活和多次尝试。

        Args:
            temp_activation: 是否为临时激活（仅用于截图等操作）
            max_attempts: 最大尝试次数

        Returns:
            bool: 激活成功返回True，否则返回False
        """
        if not self._is_window_ready():
            self.logger.warning(f"窗口未就绪，无法激活 | 句柄: {self.hwnd}")
            return False

        # 检查窗口是否已经在前台
        if win32gui.GetForegroundWindow() == self.hwnd:
            self.logger.debug(f"窗口已在前台，无需激活 | 句柄: {self.hwnd}")
            return True

        # 优化激活策略：减少尝试次数，避免多次激活导致闪烁
        # 对于临时激活，只尝试一次
        if temp_activation:
            max_attempts = 1

        for attempt in range(max_attempts):
            if self.stop_event.is_set():
                self.logger.debug(f"激活操作被中断 | 句柄: {self.hwnd}")
                return False

            try:
                # 如果窗口最小化，先恢复
                if self.is_minimized():
                    win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                    time.sleep(self.WINDOW_RESTORE_DELAY)

                # 使用SwitchToThisWindow激活窗口（绕过SetForegroundWindow限制）
                # 这是最可靠的激活方法，避免多次尝试不同的激活方式导致闪烁
                ctypes.windll.user32.SwitchToThisWindow(self.hwnd, True)

                # 等待窗口稳定，减少延迟时间，避免闪烁
                delay = self.TEMP_FOREGROUND_DELAY / 2 if temp_activation else self.WINDOW_ACTIVATE_DELAY / 2
                time.sleep(delay)

                # 验证激活结果
                if win32gui.GetForegroundWindow() == self.hwnd:
                    self.logger.debug(f"窗口激活成功 | 句柄: {self.hwnd} | 尝试次数: {attempt+1}")
                    return True
                else:
                    self.logger.warning(f"窗口激活失败 | 句柄: {self.hwnd} | 尝试次数: {attempt+1}")
                    # 只在最后一次尝试失败后才等待重试
                    if attempt < max_attempts - 1:
                        time.sleep(0.3)  # 减少等待时间，避免闪烁

            except Exception as e:
                self.logger.warning(f"窗口激活异常 | 句柄: {self.hwnd} | 尝试次数: {attempt+1} | 错误: {e}")
                # 只在最后一次尝试失败后才等待重试
                if attempt < max_attempts - 1:
                    time.sleep(0.3)  # 减少等待时间，避免闪烁

        self.logger.warning(f"窗口激活失败，已尝试{max_attempts}次 | 句柄: {self.hwnd}")
        return False

    # -------------- 临时激活窗口方法（基于统一激活方法） --------------
    def _temp_activate_window(self) -> Optional[int]:
        """
        临时激活目标窗口，保存原始前台窗口句柄。

        Returns:
            Optional[int]: 原始前台窗口句柄，失败返回None
        """
        if not self.hwnd:
            return None

        try:
            # 保存原始前台窗口
            original_foreground = win32gui.GetForegroundWindow()

            # 如果目标窗口已经在前台，直接返回
            if original_foreground == self.hwnd:
                return original_foreground

            # 使用统一激活方法
            if self._activate_window(temp_activation=True):
                return original_foreground
            else:
                return None

        except Exception as e:
            self.logger.warning(f"临时激活窗口异常: {e}")
            return None

    # -------------- 模式适配：临时置顶逻辑修改 --------------
    def _set_window_temp_topmost(self) -> bool:
        """
        background点击模式专用：临时设置窗口置顶，foreground点击模式下直接返回True。
        """
        # foreground点击模式无需临时置顶
        if self._click_mode == "foreground":
            return True

        with self._topmost_lock:
            if not self.hwnd or self._is_temp_topmost:
                return False

            try:
                current_ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
                if (current_ex_style & win32con.WS_EX_TOPMOST) != 0:
                    self._is_temp_topmost = True
                    self._original_window_ex_style = current_ex_style
                    self.logger.debug(f"background点击模式窗口已置顶，标记临时置顶状态 | 句柄: {self.hwnd}")
                    return True

                self._original_window_ex_style = current_ex_style
                new_ex_style = self._original_window_ex_style | win32con.WS_EX_TOPMOST
                win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, new_ex_style)

                win32gui.SetWindowPos(
                    self.hwnd,
                    win32con.HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )

                time.sleep(self.TEMP_TOPMOST_DELAY)
                self._is_temp_topmost = True
                self.logger.debug(f"background点击模式窗口临时置顶成功 | 句柄: {self.hwnd}")
                return True
            except Exception as e:
                self.logger.warning(f"background点击模式设置临时置顶失败: {e}")
                self._original_window_ex_style = None
                self._is_temp_topmost = False
                return False

    def _restore_window_original_topmost(self, pre_delay: float = 0.1) -> None:
        """
        background点击模式专用：恢复窗口原始置顶状态；foreground点击模式下直接返回（不恢复）。
        """
        # foreground点击模式不恢复置顶状态
        if self._click_mode == "foreground":
            self.logger.debug("foreground点击模式跳过窗口置顶状态恢复")
            return

        with self._topmost_lock:
            if not self.hwnd or not self._is_temp_topmost or self._original_window_ex_style is None:
                self.logger.debug("background点击模式无需恢复置顶状态：窗口句柄/临时置顶标记/原始样式缺失")
                return

            try:
                if pre_delay > 0:
                    time.sleep(pre_delay)

                # 恢复原始扩展样式
                win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, self._original_window_ex_style)

                # 取消置顶
                win32gui.SetWindowPos(
                    self.hwnd,
                    win32con.HWND_NOTOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )

                time.sleep(self.TEMP_TOPMOST_DELAY)

                # 验证恢复结果
                current_ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
                is_still_topmost = (current_ex_style & win32con.WS_EX_TOPMOST) != 0

                if is_still_topmost:
                    self.logger.warning(
                        f"background点击模式窗口仍置顶 | 当前样式: {hex(current_ex_style)} | 原始样式: {hex(self._original_window_ex_style)}"
                    )
                    win32gui.SetWindowPos(
                        self.hwnd,
                        win32con.HWND_NOTOPMOST,
                        0,
                        0,
                        0,
                        0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER,
                    )
                else:
                    self.logger.debug(f"background点击模式窗口恢复原始置顶状态成功 | 句柄: {self.hwnd}")
            except Exception as e:
                self.logger.warning(f"background点击模式恢复置顶状态失败: {e}", exc_info=True)
            finally:
                self._original_window_ex_style = None
                self._is_temp_topmost = False

    # -------------- 截图策略检测 --------------
    def _select_best_method(
        self, method_priority: List[str], available_methods: List[str], default_method: str = None
    ) -> str:
        """
        根据优先级列表选择最优可用方法。

        Args:
            method_priority: 方法优先级列表，按优先级从高到低排列
            available_methods: 可用方法列表
            default_method: 默认方法，当没有匹配方法时使用

        Returns:
            str: 最优可用方法
        """
        for method in method_priority:
            if method in available_methods:
                return method
        return default_method or method_priority[-1]

    def _detect_best_screenshot_strategy(self) -> str:
        """
        检测并选择最优截图策略，初始化截图模式和可用方法列表。

        核心功能：
        - 检测所有可用截图方法
        - 更新可用截图方法列表
        - 根据截图模式选择最优方法
        - 处理窗口未就绪情况

        检测流程：
        1. 检查窗口状态，未就绪则默认使用temp_foreground
        2. 更新窗口动态信息
        3. 依次检测printwindow、bitblt、dxcam截图方法
        4. 始终将temp_foreground作为兜底方法
        5. 根据已设置的截图模式或自动选择最优方法

        方法优先级（foreground模式）：
        - bitblt > dxcam > temp_foreground

        Returns:
            str: 最优截图策略名称
        """
        if not self._is_window_ready():
            self.logger.warning("窗口未就绪，默认使用temp_foreground（foreground模式）")
            self._screenshot_mode = "foreground"
            self._available_screenshot_methods = ["temp_foreground"]
            return "temp_foreground"

        self._update_dynamic_window_info()
        client_w_phys, client_h_phys = self.display_context.client_physical_res
        if client_w_phys <= 0 or client_h_phys <= 0:
            self.logger.warning("窗口尺寸无效，默认使用temp_foreground（foreground模式）")
            self._screenshot_mode = "foreground"
            self._available_screenshot_methods = ["temp_foreground"]
            return "temp_foreground"

        # 检测1: PrintWindow（background模式）
        def test_printwindow():
            try:
                hwnd_dc = win32gui.GetWindowDC(self.hwnd)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                mem_dc = mfc_dc.CreateCompatibleDC()
                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, client_w_phys, client_h_phys)
                mem_dc.SelectObject(bitmap)

                result = ctypes.windll.user32.PrintWindow(self.hwnd, mem_dc.GetSafeHdc(), 0)
                if not result:
                    raise RuntimeError("PrintWindow调用失败")

                bmp_str = bitmap.GetBitmapBits(True)
                img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                img_np = np.array(img_pil)
                mean_val = np.mean(img_np)

                # 释放资源
                mem_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(self.hwnd, hwnd_dc)
                win32gui.DeleteObject(bitmap.GetHandle())

                return mean_val > 10
            except Exception as e:
                self.logger.debug(f"PrintWindow检测失败: {e}")
                return False

        # 检测2: BitBlt（foreground模式）
        def test_bitblt():
            try:
                # 检查窗口是否已经在前台
                is_already_foreground = win32gui.GetForegroundWindow() == self.hwnd
                original_foreground = None

                # 只有当窗口不在前台时，才临时激活窗口
                if not is_already_foreground:
                    original_foreground = self._temp_activate_window()

                hwnd_dc = win32gui.GetWindowDC(self.hwnd)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                mem_dc = mfc_dc.CreateCompatibleDC()
                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, client_w_phys, client_h_phys)
                mem_dc.SelectObject(bitmap)

                mem_dc.BitBlt((0, 0), (client_w_phys, client_h_phys), mfc_dc, (0, 0), win32con.SRCCOPY)

                bmp_str = bitmap.GetBitmapBits(True)
                img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                img_np = np.array(img_pil)
                mean_val = np.mean(img_np)

                # 释放资源
                mem_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(self.hwnd, hwnd_dc)
                win32gui.DeleteObject(bitmap.GetHandle())

                # 只有当窗口不在前台时，才恢复原始前台窗口
                if not is_already_foreground and original_foreground and original_foreground != self.hwnd:
                    self._restore_foreground(original_foreground)

                return mean_val > 10
            except Exception as e:
                self.logger.debug(f"BitBlt检测失败: {e}")
                return False

        # 检测3: DXCam（foreground模式）
        def test_dxcam():
            try:
                import dxcam

                # 检查窗口是否已经在前台
                is_already_foreground = win32gui.GetForegroundWindow() == self.hwnd
                original_foreground = None

                # 只有当窗口不在前台时，才临时激活窗口
                if not is_already_foreground:
                    original_foreground = self._temp_activate_window()

                camera = dxcam.create()
                if not camera:
                    raise RuntimeError("DXCam无法创建摄像头实例")

                client_origin_x, client_origin_y = win32gui.ClientToScreen(self.hwnd, (0, 0))
                client_end_x = client_origin_x + client_w_phys
                client_end_y = client_origin_y + client_h_phys

                img_np = camera.grab(region=(client_origin_x, client_origin_y, client_end_x, client_end_y))
                if img_np is None:
                    raise RuntimeError("DXCam返回空图像")

                mean_val = np.mean(img_np)

                # 只有当窗口不在前台时，才恢复原始前台窗口
                if not is_already_foreground and original_foreground and original_foreground != self.hwnd:
                    self._restore_foreground(original_foreground)

                return mean_val > 10
            except ImportError:
                self.logger.debug("dxcam未安装，跳过硬件加速截图检测")
                return False
            except Exception as e:
                self.logger.debug(f"DXCam检测失败: {e}")
                return False

        # 检测所有截图方法并记录可用方法
        available_methods = []

        # 优化：优先检测printwindow（后台截图，不激活窗口）
        if test_printwindow():
            available_methods.append("printwindow")

        # 检查窗口是否已经在前台
        is_already_foreground = win32gui.GetForegroundWindow() == self.hwnd

        # 只有当窗口已经在前台时，才检测bitblt和dxcam（避免不必要的窗口激活）
        if is_already_foreground:
            if test_bitblt():
                available_methods.append("bitblt")
            if test_dxcam():
                available_methods.append("dxcam")
        else:
            # 窗口不在前台，优先使用temp_foreground作为兜底，避免多次激活窗口
            self.logger.debug("窗口不在前台，跳过bitblt和dxcam检测，优先使用temp_foreground")

        # temp_foreground 总是可用作为兜底
        available_methods.append("temp_foreground")

        self._available_screenshot_methods = available_methods
        self.logger.info(f"检测到可用的截图方法: {available_methods}")

        # 执行检测流程并判定截图模式
        # 优先使用已经设置的截图模式
        if self._screenshot_mode:
            # 如果已经设置了具体的截图方法，直接使用
            if self._screenshot_mode in available_methods:
                self.logger.info(f"使用已设置的截图模式：{self._screenshot_mode}")
                return self._screenshot_mode
            # 如果设置的是background模式，使用printwindow
            elif self._screenshot_mode == "background" and "printwindow" in available_methods:
                self.logger.info("使用已设置的background模式：PrintWindow")
                return "printwindow"
            # 如果设置的是foreground模式，选择最优前台截图方法
            elif self._screenshot_mode == "foreground":
                best_method = self._select_best_method(["bitblt", "dxcam", "temp_foreground"], available_methods)
                self.logger.info(f"使用已设置的foreground模式：{best_method}")
                return best_method

        # 未指定截图模式或指定模式不可用，自动选择最优模式
        # 默认优先使用foreground模式
        # 按性能排序：bitblt > dxcam > temp_foreground
        best_method = self._select_best_method(["bitblt", "dxcam", "temp_foreground"], available_methods)
        self.logger.info(f"截图策略检测结果：{best_method}（foreground模式）")
        return best_method

    # -------------- 原有工具方法（无修改） --------------
    def _parse_uri(self, uri: str) -> Dict[str, str]:
        params = {}
        if "://" in uri:
            _, query = uri.split("://", 1)
            for part in query.split("&"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    params[key.lower()] = value
        return params

    def _get_window_handle(self) -> Optional[int]:
        self.logger.info("开始查找目标窗口...")
        strategies = [
            ("精确标题", lambda: self.uri_params.get("title") and win32gui.FindWindow(None, self.uri_params["title"])),
            ("正则标题", self._find_by_title_regex),
            (
                "进程名",
                lambda: self.uri_params.get("process")
                and self._find_window_by_process_name(self.uri_params["process"]),
            ),
            ("类名", lambda: self.uri_params.get("class") and win32gui.FindWindow(self.uri_params["class"], None)),
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
        try:
            import os

            import psutil

            # 从文件路径中提取进程名
            if os.path.isfile(process_name):
                process_name = os.path.basename(process_name)
                self.logger.info(f"从路径中提取进程名: {process_name}")

            # 收集所有匹配的进程
            matched_processes = []
            for proc in psutil.process_iter(["name", "pid"]):
                if proc.info["name"] and proc.info["name"].lower() == process_name.lower():
                    matched_processes.append(proc)

            if not matched_processes:
                self.logger.warning(f"未找到进程: {process_name}")
                return None

            self.logger.info(f"找到 {len(matched_processes)} 个匹配进程: {process_name}")

            # 收集所有可见窗口
            all_visible_windows = []

            def collect_visible_windows(hwnd, ctx):
                _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                if win32gui.IsWindowVisible(hwnd):
                    ctx.append((window_pid, hwnd))

            win32gui.EnumWindows(collect_visible_windows, all_visible_windows)

            # 筛选出与目标进程相关的窗口
            related_windows = []
            process_pids = {proc.info["pid"] for proc in matched_processes}

            for window_pid, hwnd in all_visible_windows:
                if window_pid in process_pids:
                    window_title = win32gui.GetWindowText(hwnd)
                    if window_title:
                        related_windows.append(hwnd)

            if related_windows:
                hwnd = related_windows[0]
                window_title = win32gui.GetWindowText(hwnd)
                self.logger.info(f"找到进程关联窗口 | 句柄: {hwnd} | 标题: {window_title}")
                return hwnd
        except ImportError:
            self.logger.warning("psutil未安装，无法通过进程名查找窗口")
        except Exception as e:
            self._record_error("_find_window_by_process_name", f"进程名查找窗口异常：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
        return None

    def _enable_dpi_awareness(self) -> None:
        try:
            # 定义DPI感知级别常量
            PROCESS_DPI_UNAWARE = 0
            PROCESS_SYSTEM_DPI_AWARE = 1
            PROCESS_PER_MONITOR_DPI_AWARE = 2

            shcore = ctypes.windll.shcore

            # 首先尝试获取当前DPI感知级别，避免重复设置
            try:
                current_awareness = ctypes.c_int()
                result = shcore.GetProcessDpiAwareness(ctypes.byref(current_awareness))
                if result == 0:
                    self.logger.debug(f"当前DPI感知级别: {current_awareness.value}")
                    if current_awareness.value > 0:
                        # 已经设置了合适的DPI感知级别，无需再次设置
                        return
            except Exception:
                # GetProcessDpiAwareness可能不可用，继续尝试设置
                pass

            # 尝试不同的DPI感知级别，从高到低
            for awareness_level in [PROCESS_PER_MONITOR_DPI_AWARE, PROCESS_SYSTEM_DPI_AWARE]:
                try:
                    result = shcore.SetProcessDpiAwareness(awareness_level)
                    if result == 0:
                        self.logger.debug(f"已启用DPI感知模式，级别: {awareness_level}")
                        try:
                            system_dpi = ctypes.windll.user32.GetDpiForSystem()
                            self.logger.debug(f"系统DPI: {system_dpi}（标准DPI=96）")
                        except Exception:
                            pass
                        return
                except Exception:
                    # 尝试下一个级别
                    continue

            # 如果SetProcessDpiAwareness所有级别都失败，尝试旧版API
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                self.logger.debug("已启用系统级DPI感知模式（旧版API）")
            except Exception as e:
                self.logger.error(f"所有DPI感知模式启用失败：{str(e)}，可能导致坐标偏移", exc_info=True)
        except Exception as e:
            self.logger.error(f"启用DPI感知失败: {str(e)}", exc_info=True)

    def _get_dpi_for_window(self) -> float:
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
            self._record_error("_get_screen_hardware_res", f"获取屏幕分辨率失败：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            return (1920, 1080)

    def _update_dynamic_window_info(self) -> bool:
        try:
            if self.is_minimized():
                self.logger.debug("窗口处于最小化状态，跳过动态信息更新")
                return False

            window_rect = win32gui.GetWindowRect(self.hwnd)
            self.logger.debug(f"窗口矩形: {window_rect}")
            if all(coord == 0 for coord in window_rect):
                raise RuntimeError(f"获取窗口矩形失败，返回无效值: {window_rect}")

            dpi_scale = self._get_dpi_for_window()
            dpi_scale = max(1.0, dpi_scale)

            client_rect_phys = win32gui.GetClientRect(self.hwnd)
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

            client_origin_x, client_origin_y = win32gui.ClientToScreen(self.hwnd, (0, 0))
            screen_res = self._get_screen_hardware_res()

            # 先更新display_context，包括hwnd，避免全屏判定时hwnd为None
            self.display_context.update_from_window(
                hwnd=self.hwnd,
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
            self._record_error("_update_dynamic_window_info", f"动态窗口信息更新失败：{str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            return False

    def _ensure_window_foreground(self, max_attempts: int = 3) -> bool:
        current_time = time.time()
        foreground_hwnd = win32gui.GetForegroundWindow()

        if current_time - self._last_activate_attempt < self.ACTIVATE_RETRY_COOLDOWN:
            self.logger.debug(
                f"激活操作冷却中（剩余{self.ACTIVATE_RETRY_COOLDOWN - (current_time - self._last_activate_attempt):.1f}秒）"
            )
            if self._is_window_ready() and foreground_hwnd == self.hwnd:
                return True
            return False
        self._last_activate_attempt = current_time

        if self._is_window_ready() and foreground_hwnd == self.hwnd:
            self._last_activate_time = current_time
            self.logger.debug(f"窗口已在前台（句柄: {self.hwnd}），无需激活")
            # 窗口已在前台且状态就绪，无需更新动态信息
            return True

        self.logger.info(f"开始激活窗口（最多{max_attempts}次尝试）| 句柄: {self.hwnd}")
        if self._activate_window(temp_activation=False, max_attempts=max_attempts):
            self._last_activate_time = current_time
            self._update_dynamic_window_info()
            return True
        else:
            self._record_error(
                "_ensure_window_foreground", f"窗口激活失败（已尝试{max_attempts}次），可能被遮挡/权限不足"
            )
            self.logger.info(self.last_error)
            return False

    # -------------- 核心方法：connect --------------
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
                self.hwnd = self._get_window_handle()
                if self.hwnd:
                    found_once = True
                    last_find_time = current_time
                    self.window_class = win32gui.GetClassName(self.hwnd)
                    _, self.process_id = win32process.GetWindowThreadProcessId(self.hwnd)

                    # 直接调用 update_from_window 方法更新所有窗口信息
                    self._update_dynamic_window_info()

                    # 检测截图策略
                    self._best_screenshot_strategy = self._detect_best_screenshot_strategy()

                    # 初始化点击模式（默认foreground）
                    if not self._click_mode:
                        self._click_mode = "foreground"

                    # 初始化截图模式
                    if not self._screenshot_mode:
                        self._screenshot_mode = self._best_screenshot_strategy
            elif self.hwnd:
                # 已找到窗口，只更新窗口状态，不重新查找
                self._update_dynamic_window_info()

            if self.hwnd:
                # 前台模式初始化：仅在窗口不在前台时激活
                if self._best_screenshot_strategy in ["bitblt", "dxcam", "temp_foreground"]:
                    # 检查窗口是否已经在前台
                    if win32gui.GetForegroundWindow() != self.hwnd:
                        # 首次连接时，确保窗口被激活
                        if not self._activate_window(temp_activation=True):
                            self.logger.warning("前台模式窗口首次激活失败")
                        else:
                            self.logger.info("前台模式窗口首次激活成功")
                    else:
                        self.logger.debug("窗口已在前台，无需首次激活")

                # 检查窗口状态，只要窗口存在且未被最小化即可连接
                if self._is_window_ready():
                    self._update_state(DeviceState.CONNECTED)
                    self.logger.info(
                        f"Windows设备连接成功 | "
                        f"标题: {self.window_title} | 句柄: {self.hwnd} | "
                        f"类名: {self.window_class} | PID: {self.process_id} | "
                        f"截图策略: {self._best_screenshot_strategy} | 截图模式: {self._screenshot_mode} | "
                        f"点击模式: {self._click_mode}"
                    )
                    return True
                elif current_time - last_find_time < 1.0:  # 只在刚找到窗口时记录一次警告
                    self.logger.warning(f"窗口状态不满足连接条件，句柄: {self.hwnd}")

            time.sleep(0.5)

        self._record_error("connect", f"连接超时（{timeout}秒），未找到匹配窗口")
        self.logger.error(self.last_error)
        self._update_state(DeviceState.DISCONNECTED)
        return False

    # -------------- 核心方法：disconnect --------------
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
            self._best_screenshot_strategy = None
            self._screenshot_mode = None
            self._click_mode = None
            self._original_window_ex_style = None
            self._is_temp_topmost = False
            self._original_topmost_state = None
            self._available_screenshot_methods = []

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
        if not self.hwnd:
            return False
        try:
            window_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_STYLE)
            return (window_style & win32con.WS_MINIMIZE) != 0
        except Exception as e:
            self.logger.warning(f"检查窗口最小化状态失败: {e}")
            return False

    def _is_window_ready(self) -> bool:
        """
        统一检查窗口是否就绪。

        Returns:
            bool: 窗口就绪返回True，否则返回False
        """
        return self.hwnd and win32gui.IsWindow(self.hwnd) and not self.is_minimized()

    # -------------- 上下文管理器：用于资源管理 --------------
    class _DCCtxManager:
        """
        DC资源上下文管理器，自动处理DC和位图资源的获取和释放。
        """

        def __init__(self, hwnd, width, height):
            self.hwnd = hwnd
            self.width = width
            self.height = height
            self.hwnd_dc = None
            self.mfc_dc = None
            self.mem_dc = None
            self.bitmap = None

        def __enter__(self):
            """获取资源"""
            self.hwnd_dc = win32gui.GetDC(self.hwnd)
            self.mfc_dc = win32ui.CreateDCFromHandle(self.hwnd_dc)
            self.mem_dc = self.mfc_dc.CreateCompatibleDC()
            self.bitmap = win32ui.CreateBitmap()
            self.bitmap.CreateCompatibleBitmap(self.mfc_dc, self.width, self.height)
            self.mem_dc.SelectObject(self.bitmap)
            return self.mem_dc, self.bitmap

        def __exit__(self, exc_type, exc_val, exc_tb):
            """释放资源"""
            if self.mem_dc:
                self.mem_dc.DeleteDC()
            if self.mfc_dc:
                self.mfc_dc.DeleteDC()
            if self.hwnd_dc:
                win32gui.ReleaseDC(self.hwnd, self.hwnd_dc)
            if self.bitmap:
                win32gui.DeleteObject(self.bitmap.GetHandle())

    # -------------- 截图策略实现方法 --------------
    def _try_print_window(self, client_w_phys: int, client_h_phys: int) -> Optional[np.ndarray]:
        """
        使用PrintWindow方法进行后台截图。

        Args:
            client_w_phys: 客户区物理宽度
            client_h_phys: 客户区物理高度

        Returns:
            Optional[np.ndarray]: 截图图像，失败返回None
        """
        try:
            with self._DCCtxManager(self.hwnd, client_w_phys, client_h_phys) as (mem_dc, bitmap):
                PW_CLIENTONLY = 1
                PW_RENDERFULLCONTENT = 0x00000002
                print_flags = PW_CLIENTONLY | PW_RENDERFULLCONTENT

                result = ctypes.windll.user32.PrintWindow(self.hwnd, mem_dc.GetSafeHdc(), print_flags)
                if not result:
                    raise RuntimeError("PrintWindow调用返回失败")

                bmp_str = bitmap.GetBitmapBits(True)
                img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                img_np = np.array(img_pil)
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            if np.mean(img_np) < 10:
                raise RuntimeError("PrintWindow截图为黑屏")
            self.logger.debug("使用PrintWindow后台截图成功（仅客户区）")
            return img_np
        except Exception as e:
            self.logger.debug(f"PrintWindow执行失败: {e}")
            return None

    def _try_bitblt(self, client_w_phys: int, client_h_phys: int) -> Optional[np.ndarray]:
        """
        使用BitBlt方法进行前台截图。

        Args:
            client_w_phys: 客户区物理宽度
            client_h_phys: 客户区物理高度

        Returns:
            Optional[np.ndarray]: 截图图像，失败返回None
        """
        original_foreground = None
        try:
            # 临时激活窗口
            original_foreground = self._temp_activate_window()

            with self._DCCtxManager(self.hwnd, client_w_phys, client_h_phys) as (mem_dc, bitmap):
                # 获取原始DC用于BitBlt操作
                hwnd_dc = win32gui.GetDC(self.hwnd)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)

                mem_dc.BitBlt((0, 0), (client_w_phys, client_h_phys), mfc_dc, (0, 0), win32con.SRCCOPY)

                # 释放原始DC资源
                win32gui.ReleaseDC(self.hwnd, hwnd_dc)
                mfc_dc.DeleteDC()

                bmp_str = bitmap.GetBitmapBits(True)
                img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                img_np = np.array(img_pil)
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            if np.mean(img_np) < 10:
                raise RuntimeError("BitBlt截图为黑屏")

            self.logger.debug("使用BitBlt截图成功（仅客户区）")
            return img_np
        except Exception as e:
            self.logger.debug(f"BitBlt执行失败: {e}")
            return None
        finally:
            # 恢复原始前台窗口
            if original_foreground and original_foreground != self.hwnd:
                self._restore_foreground(original_foreground)

    def _try_dxcam(self, client_w_phys: int, client_h_phys: int) -> Optional[np.ndarray]:
        """
        使用DXCam方法进行硬件加速截图。

        Args:
            client_w_phys: 客户区物理宽度
            client_h_phys: 客户区物理高度

        Returns:
            Optional[np.ndarray]: 截图图像，失败返回None
        """
        original_foreground = None
        try:
            import dxcam

            # 临时激活窗口
            original_foreground = self._temp_activate_window()

            camera = dxcam.create()
            if not camera:
                raise RuntimeError("DXCam无法初始化，无可用显卡")

            client_origin_x, client_origin_y = win32gui.ClientToScreen(self.hwnd, (0, 0))
            client_end_x = client_origin_x + client_w_phys
            client_end_y = client_origin_y + client_h_phys

            img_np = camera.grab(region=(client_origin_x, client_origin_y, client_end_x, client_end_y))
            if img_np is None:
                raise RuntimeError("DXCam截图返回空图像")

            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            self.logger.debug("使用DXCam硬件加速截图成功（仅客户区）")
            return img_np
        except ImportError:
            self.logger.debug("dxcam未安装，跳过硬件加速截图")
            return None
        except Exception as e:
            self.logger.debug(f"DXCam执行失败: {e}")
            return None
        finally:
            # 恢复原始前台窗口
            if original_foreground and original_foreground != self.hwnd:
                self._restore_foreground(original_foreground)

    def _try_temp_foreground_screenshot(self, client_w_phys: int, client_h_phys: int) -> Optional[np.ndarray]:
        """
        使用临时置顶窗口方法进行截图。

        Args:
            client_w_phys: 客户区物理宽度
            client_h_phys: 客户区物理高度

        Returns:
            Optional[np.ndarray]: 截图图像，失败返回None
        """
        self.logger.debug(f"开始temp_foreground截图 | 窗口句柄: {self.hwnd} | 尺寸: {client_w_phys}x{client_h_phys}")
        original_foreground = self._get_original_foreground()
        try:
            # 使用SwitchToThisWindow激活窗口（绕过SetForegroundWindow限制）
            try:
                ctypes.windll.user32.SwitchToThisWindow(self.hwnd, True)
                self.logger.debug("SwitchToThisWindow成功")
            except Exception as e1:
                self.logger.debug(f"SwitchToThisWindow失败: {e1}")
                try:
                    win32gui.SetForegroundWindow(self.hwnd)
                    self.logger.debug("SetForegroundWindow成功")
                except Exception as e2:
                    self.logger.debug(f"SetForegroundWindow失败: {e2}")

            # 等待窗口置顶，确保截图成功
            time.sleep(self.TEMP_FOREGROUND_DELAY)

            # 确保窗口是当前前台窗口
            if win32gui.GetForegroundWindow() != self.hwnd:
                self.logger.warning(
                    f"窗口未成功置顶，当前前台句柄: {win32gui.GetForegroundWindow()}，目标句柄: {self.hwnd}"
                )
                # 再次尝试激活
                try:
                    win32gui.SetForegroundWindow(self.hwnd)
                    time.sleep(self.TEMP_FOREGROUND_DELAY)
                except Exception:
                    pass

            client_origin_x, client_origin_y = win32gui.ClientToScreen(self.hwnd, (0, 0))
            client_end_x = client_origin_x + client_w_phys
            client_end_y = client_origin_y + client_h_phys
            self.logger.debug(f"客户区屏幕坐标: ({client_origin_x}, {client_origin_y})")

            hdc_screen = win32gui.GetDC(0)
            mfc_dc = win32ui.CreateDCFromHandle(hdc_screen)
            mem_dc = mfc_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, client_w_phys, client_h_phys)
            mem_dc.SelectObject(bitmap)

            result = mem_dc.BitBlt(
                (0, 0),
                (client_w_phys, client_h_phys),
                mfc_dc,
                (client_origin_x, client_origin_y),
                win32con.SRCCOPY,
            )
            self.logger.debug(f"BitBlt结果: {result}")

            bmp_str = bitmap.GetBitmapBits(True)
            img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
            img_np = np.array(img_pil)
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            mem_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(0, hdc_screen)
            win32gui.DeleteObject(bitmap.GetHandle())

            self._restore_foreground(original_foreground)
            self.logger.debug("使用临时置顶屏幕截图成功（仅客户区，终极兜底）")
            return img_np
        except Exception as e:
            self.logger.debug(f"临时置顶屏幕截图失败: {e}")
            if original_foreground:
                try:
                    self._restore_foreground(original_foreground)
                except Exception:
                    pass
            return None

    # -------------- 核心方法：capture_screen --------------
    def capture_screen(self, roi: Optional[Tuple[int, int, int, int]] = None) -> Optional[np.ndarray]:
        """
        屏幕截图，支持多种截图策略和ROI裁剪。

        截图策略说明：
        - background模式：使用PrintWindow，后台截图，无需窗口置顶
        - foreground模式：优先使用bitblt/dxcam，前台截图，临时激活窗口，失败降级到temp_foreground

        截图方法优先级：
        1. 已设置的特定截图方法
        2. 根据截图模式选择最优方法
        3. 失败时自动降级到可用方法

        Args:
            roi: 可选，感兴趣区域，格式为(x, y, width, height)

        Returns:
            Optional[np.ndarray]: 截图图像（BGR格式），失败返回None
        """
        self.clear_last_error()
        if not self._is_window_ready():
            self._record_error("capture_screen", "窗口未连接/最小化，无法截图")
            self.logger.error(self.last_error)
            return None

        if not self._update_dynamic_window_info():
            self.logger.warning("窗口动态信息更新失败，使用缓存尺寸")

        client_w_phys, client_h_phys = self.display_context.client_physical_res
        self.logger.debug(f"截图客户区尺寸: {client_w_phys}x{client_h_phys}")

        # 如果客户区尺寸无效，直接使用窗口矩形进行截图
        if client_w_phys <= 0 or client_h_phys <= 0:
            self.logger.warning(f"窗口客户区尺寸无效({client_w_phys}x{client_h_phys})，使用窗口矩形进行截图")
            try:
                window_rect = win32gui.GetWindowRect(self.hwnd)
                self.logger.debug(f"兜底窗口矩形: {window_rect}")
                if all(coord == 0 for coord in window_rect):
                    self._record_error("capture_screen", f"窗口矩形无效: {window_rect}")
                    self.logger.error(self.last_error)
                    return None

                client_w_phys = window_rect[2] - window_rect[0]
                client_h_phys = window_rect[3] - window_rect[1]
                self.logger.debug(f"兜底客户区尺寸: {client_w_phys}x{client_h_phys}")
            except Exception as e:
                self._record_error("capture_screen", f"获取窗口矩形失败: {str(e)}")
                self.logger.error(self.last_error)
                return None

        # 最终兜底：使用屏幕分辨率
        if client_w_phys <= 0 or client_h_phys <= 0:
            self.logger.warning("窗口尺寸仍无效，使用屏幕分辨率作为最终兜底")
            screen_res = self._get_screen_hardware_res()
            client_w_phys, client_h_phys = screen_res
            self.logger.debug(f"兜底屏幕分辨率: {client_w_phys}x{client_h_phys}")

        # -------------------------- 各策略实现 --------------------------
        def try_print_window():
            try:
                with self._DCCtxManager(self.hwnd, client_w_phys, client_h_phys) as (mem_dc, bitmap):
                    PW_CLIENTONLY = 1
                    PW_RENDERFULLCONTENT = 0x00000002
                    print_flags = PW_CLIENTONLY | PW_RENDERFULLCONTENT

                    result = ctypes.windll.user32.PrintWindow(self.hwnd, mem_dc.GetSafeHdc(), print_flags)
                    if not result:
                        raise RuntimeError("PrintWindow调用返回失败")

                    bmp_str = bitmap.GetBitmapBits(True)
                    img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                    img_np = np.array(img_pil)
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                if np.mean(img_np) < 10:
                    raise RuntimeError("PrintWindow截图为黑屏")
                self.logger.debug("使用PrintWindow后台截图成功（仅客户区）")
                return img_np
            except Exception as e:
                self.logger.debug(f"PrintWindow执行失败: {e}")
                return None

        def try_bitblt():
            """增强版bitblt：添加临时激活窗口逻辑"""
            original_foreground = None
            try:
                # 临时激活窗口
                original_foreground = self._temp_activate_window()

                with self._DCCtxManager(self.hwnd, client_w_phys, client_h_phys) as (mem_dc, bitmap):
                    # 获取原始DC用于BitBlt操作
                    hwnd_dc = win32gui.GetDC(self.hwnd)
                    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)

                    mem_dc.BitBlt((0, 0), (client_w_phys, client_h_phys), mfc_dc, (0, 0), win32con.SRCCOPY)

                    # 释放原始DC资源
                    win32gui.ReleaseDC(self.hwnd, hwnd_dc)
                    mfc_dc.DeleteDC()

                    bmp_str = bitmap.GetBitmapBits(True)
                    img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                    img_np = np.array(img_pil)
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                if np.mean(img_np) < 10:
                    raise RuntimeError("BitBlt截图为黑屏")

                self.logger.debug("使用BitBlt截图成功（仅客户区）")
                return img_np
            except Exception as e:
                self.logger.debug(f"BitBlt执行失败: {e}")
                return None
            finally:
                # 恢复原始前台窗口
                if original_foreground and original_foreground != self.hwnd:
                    self._restore_foreground(original_foreground)

        def try_dxcam():
            """增强版dxcam：添加临时激活窗口逻辑"""
            original_foreground = None
            try:
                import dxcam

                # 临时激活窗口
                original_foreground = self._temp_activate_window()

                camera = dxcam.create()
                if not camera:
                    raise RuntimeError("DXCam无法初始化，无可用显卡")

                client_origin_x, client_origin_y = win32gui.ClientToScreen(self.hwnd, (0, 0))
                client_end_x = client_origin_x + client_w_phys
                client_end_y = client_origin_y + client_h_phys

                img_np = camera.grab(region=(client_origin_x, client_origin_y, client_end_x, client_end_y))
                if img_np is None:
                    raise RuntimeError("DXCam截图返回空图像")

                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                self.logger.debug("使用DXCam硬件加速截图成功（仅客户区）")
                return img_np
            except ImportError:
                self.logger.debug("dxcam未安装，跳过硬件加速截图")
                return None
            except Exception as e:
                self.logger.debug(f"DXCam执行失败: {e}")
                return None
            finally:
                # 恢复原始前台窗口
                if original_foreground and original_foreground != self.hwnd:
                    self._restore_foreground(original_foreground)

        def try_temp_foreground_screenshot():
            self.logger.debug(
                f"开始temp_foreground截图 | 窗口句柄: {self.hwnd} | 尺寸: {client_w_phys}x{client_h_phys}"
            )
            original_foreground = self._get_original_foreground()
            try:
                # 使用SwitchToThisWindow激活窗口（绕过SetForegroundWindow限制）
                try:
                    ctypes.windll.user32.SwitchToThisWindow(self.hwnd, True)
                    self.logger.debug("SwitchToThisWindow成功")
                except Exception as e1:
                    self.logger.debug(f"SwitchToThisWindow失败: {e1}")
                    try:
                        win32gui.SetForegroundWindow(self.hwnd)
                        self.logger.debug("SetForegroundWindow成功")
                    except Exception as e2:
                        self.logger.debug(f"SetForegroundWindow失败: {e2}")

                # 等待窗口置顶，确保截图成功
                time.sleep(self.TEMP_FOREGROUND_DELAY)

                # 确保窗口是当前前台窗口
                if win32gui.GetForegroundWindow() != self.hwnd:
                    self.logger.warning(
                        f"窗口未成功置顶，当前前台句柄: {win32gui.GetForegroundWindow()}，目标句柄: {self.hwnd}"
                    )
                    # 再次尝试激活
                    try:
                        win32gui.SetForegroundWindow(self.hwnd)
                        time.sleep(self.TEMP_FOREGROUND_DELAY)
                    except Exception:
                        pass

                client_origin_x, client_origin_y = win32gui.ClientToScreen(self.hwnd, (0, 0))
                client_end_x = client_origin_x + client_w_phys
                client_end_y = client_origin_y + client_h_phys
                self.logger.debug(f"客户区屏幕坐标: ({client_origin_x}, {client_origin_y})")

                hdc_screen = win32gui.GetDC(0)
                mfc_dc = win32ui.CreateDCFromHandle(hdc_screen)
                mem_dc = mfc_dc.CreateCompatibleDC()
                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, client_w_phys, client_h_phys)
                mem_dc.SelectObject(bitmap)

                result = mem_dc.BitBlt(
                    (0, 0),
                    (client_w_phys, client_h_phys),
                    mfc_dc,
                    (client_origin_x, client_origin_y),
                    win32con.SRCCOPY,
                )
                self.logger.debug(f"BitBlt结果: {result}")

                bmp_str = bitmap.GetBitmapBits(True)
                img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                img_np = np.array(img_pil)
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                mem_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(0, hdc_screen)
                win32gui.DeleteObject(bitmap.GetHandle())

                self._restore_foreground(original_foreground)
                self.logger.debug("使用临时置顶屏幕截图成功（仅客户区，终极兜底）")
                return img_np
            except Exception as e:
                self.logger.debug(f"临时置顶屏幕截图失败: {e}")
                if original_foreground:
                    try:
                        self._restore_foreground(original_foreground)
                    except Exception:
                        pass
                return None

        # -------------------------- 模式适配：执行截图策略 --------------------------
        img_np = None

        # 检查窗口是否在前台
        is_foreground = win32gui.GetForegroundWindow() == self.hwnd

        # 窗口在前台时，优先使用更稳定的截图方法，避免temp_foreground导致的闪烁
        if is_foreground:
            self.logger.debug("窗口在前台，优先使用更稳定的截图方法")
            # 优先使用bitblt或dxcam，失败再尝试printwindow
            img_np = self._try_bitblt(client_w_phys, client_h_phys)
            if img_np is None:
                img_np = self._try_dxcam(client_w_phys, client_h_phys)
            if img_np is None:
                img_np = self._try_print_window(client_w_phys, client_h_phys)

        # 如果temp_foreground失败或者窗口不在前台，再尝试其他截图方法
        if img_np is None:
            # 如果设置了具体的截图方法，尝试该方法
            if self._screenshot_mode in ["temp_foreground", "bitblt", "dxcam", "printwindow"]:
                self.logger.debug(f"使用已设置的截图方法: {self._screenshot_mode}")
                if self._screenshot_mode == "temp_foreground":
                    img_np = self._try_temp_foreground_screenshot(client_w_phys, client_h_phys)
                elif self._screenshot_mode == "bitblt":
                    img_np = self._try_bitblt(client_w_phys, client_h_phys)
                elif self._screenshot_mode == "dxcam":
                    img_np = self._try_dxcam(client_w_phys, client_h_phys)
                elif self._screenshot_mode == "printwindow":
                    img_np = self._try_print_window(client_w_phys, client_h_phys)
            # background截图模式：强制使用PrintWindow，失败则降级
            elif self._screenshot_mode == "background":
                img_np = self._try_print_window(client_w_phys, client_h_phys)
            # foreground截图模式：优先使用更稳定的截图方法，避免temp_foreground导致的闪烁
            elif self._screenshot_mode == "foreground":
                self.logger.debug("foreground截图模式优先使用更稳定的截图方法")
                # 优先使用bitblt或dxcam，失败再尝试printwindow，最后才使用temp_foreground
                img_np = self._try_bitblt(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_dxcam(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_print_window(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_temp_foreground_screenshot(client_w_phys, client_h_phys)
            else:
                # 兜底：优先使用更稳定的截图方法，避免temp_foreground导致的闪烁
                self.logger.warning(f"未知截图模式: {self._screenshot_mode}，使用更稳定的截图方法兜底")
                img_np = self._try_print_window(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_bitblt(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_dxcam(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_temp_foreground_screenshot(client_w_phys, client_h_phys)

            # 如果指定的截图方法失败，执行降级流程
            if img_np is None:
                self.logger.debug(f"指定截图方法 {self._screenshot_mode} 失败，执行降级流程")
                # 尝试所有其他可用方法，按优先级排序
                img_np = self._try_temp_foreground_screenshot(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_bitblt(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_dxcam(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_print_window(client_w_phys, client_h_phys)

        # 所有策略均失败
        if img_np is None:
            self._record_error("capture_screen", "所有截图策略均失败")
            self.logger.error(self.last_error)
            return None

        # -------------------------- ROI裁剪处理 --------------------------
        if roi:
            is_valid, err_msg = self.coord_transformer.validate_roi_format(roi)
            if not is_valid:
                self.logger.warning(f"ROI无效: {err_msg}")
            else:
                screen_phys_rect = self.coord_transformer.convert_client_logical_rect_to_screen_physical(
                    roi, is_base_coord=True
                )
                if screen_phys_rect:
                    phys_x, phys_y, phys_w, phys_h = screen_phys_rect

                    # 全屏/窗口模式区分处理
                    ctx = self.display_context
                    if ctx.is_fullscreen:
                        # 全屏模式：截图直接对应屏幕物理坐标，无需考虑客户区原点
                        crop_x = max(0, phys_x)
                        crop_y = max(0, phys_y)
                        # 使用屏幕物理尺寸作为边界
                        screen_w, screen_h = ctx.screen_physical_res
                        crop_w = min(phys_w, screen_w - crop_x)
                        crop_h = min(phys_h, screen_h - crop_y)
                        self.logger.debug(
                            f"全屏模式ROI裁剪 | 屏幕物理坐标: ({phys_x},{phys_y},{phys_w},{phys_h}) → 裁剪区域: ({crop_x},{crop_y},{crop_w},{crop_h})"
                        )
                    else:
                        # 窗口模式：计算相对客户区的裁剪坐标
                        crop_x = max(0, phys_x - self.display_context.client_screen_origin[0])
                        crop_y = max(0, phys_y - self.display_context.client_screen_origin[1])
                        crop_w = min(phys_w, client_w_phys - crop_x)
                        crop_h = min(phys_h, client_h_phys - crop_y)
                        self.logger.debug(
                            f"窗口模式ROI裁剪 | 屏幕物理坐标: ({phys_x},{phys_y},{phys_w},{phys_h}) → 客户区: ({crop_x},{crop_y},{crop_w},{crop_h})"
                        )

                    if crop_w > 0 and crop_h > 0:
                        img_np = img_np[crop_y : crop_y + crop_h, crop_x : crop_x + crop_w]
                        self.logger.debug(
                            f"截图ROI裁剪完成 | 原始: {roi} → 实际裁剪: ({crop_x},{crop_y},{crop_w},{crop_h})"
                        )
                    else:
                        self.logger.warning(f"ROI转换后无效: {roi}")

        return img_np

    # -------------- 输入操作方法（模式适配，无核心逻辑修改） --------------
    def _get_original_foreground(self) -> Optional[int]:
        try:
            return win32gui.GetForegroundWindow()
        except Exception as e:
            self.logger.warning(f"获取原始前台窗口失败: {e}")
            return None

    def _restore_foreground(self, original_hwnd: Optional[int]) -> None:
        if original_hwnd and win32gui.IsWindow(original_hwnd):
            try:
                win32gui.SetForegroundWindow(original_hwnd)
                time.sleep(self.WINDOW_ACTIVATE_DELAY)
            except Exception as e:
                self.logger.warning(f"恢复原始前台窗口失败: {e}")

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
        # 记录原始前台窗口，仅在background模式下恢复
        original_foreground_hwnd = None
        if self._click_mode == "background":
            original_foreground_hwnd = self._get_original_foreground()

        # 激活目标窗口
        activate_success = self._ensure_window_foreground(max_attempts=3)
        if not activate_success:
            self._record_error("click", "无法激活窗口至前台（所有尝试失败）")
            self.logger.error(self.last_error)
            # background模式下恢复原始前台窗口
            if original_foreground_hwnd and win32gui.IsWindow(original_foreground_hwnd):
                self._restore_foreground(original_foreground_hwnd)
            return False

        # 模式适配：临时置顶（background点击模式生效，foreground点击模式跳过）
        temp_topmost_success = self._set_window_temp_topmost()

        time.sleep(0.2)  # 增加临时置顶后的延迟，确保窗口状态稳定
        target_pos: Optional[Tuple[int, int]] = None
        ctx = self.display_context
        click_source = "直接坐标"

        if isinstance(pos, (str, list)):
            click_source = "模板匹配"
            screen_img = self.capture_screen()
            if screen_img is None:
                self._record_error("click", "截图失败，无法执行模板匹配")
                self.logger.error(self.last_error)
                self._restore_window_original_topmost()
                return False

            processed_roi = roi
            if roi:
                is_valid, err_msg = self.coord_transformer.validate_roi_format(roi)
                if not is_valid:
                    self.logger.warning(f"ROI预处理失败: {err_msg}，切换为全图匹配")
                    processed_roi = None
                # Note: 不在这里手动限制ROI边界，因为模板匹配前会调用coord_transformer.process_roi进行统一处理
                # 统一的ROI处理逻辑会根据全屏/窗口模式自动适配不同坐标系统
                self.logger.debug(f"使用原始ROI: {roi}")

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
                self._restore_window_original_topmost()
                return False

            match_rect = self.coord_transformer._convert_numpy_to_tuple(match_result)
            is_valid, err_msg = self.coord_transformer.validate_roi_format(match_rect)
            if not is_valid:
                self._record_error("click", f"模板匹配结果无效: {err_msg} | 模板: {matched_template}")
                self.logger.error(self.last_error)
                self._restore_window_original_topmost()
                return False
            target_pos = self.coord_transformer.get_rect_center(match_rect)
            self.logger.debug(
                f"模板匹配成功 | 模板: {matched_template} | 匹配矩形: {match_rect} | 逻辑中心点: {target_pos}"
            )
            coord_type = CoordType.LOGICAL
        else:
            target_pos = self.coord_transformer._convert_numpy_to_tuple(pos)
            if not isinstance(target_pos, tuple) or len(target_pos) != 2:
                self._record_error("click", f"点击坐标格式无效（需2元组）: {pos}")
                self.logger.error(self.last_error)
                self._restore_window_original_topmost()
                return False
            x, y = target_pos
            if x < 0 or y < 0:
                self._record_error("click", f"点击坐标无效（非负）: ({x},{y})")
                self.logger.error(self.last_error)
                self._restore_window_original_topmost()
                return False

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

        if ctx.is_fullscreen:
            screen_x, screen_y = logical_x, logical_y
            screen_w, screen_h = ctx.screen_physical_res
            screen_x = max(0, min(screen_x, screen_w - 1))
            screen_y = max(0, min(screen_y, screen_h - 1))
        else:
            if coord_type == CoordType.PHYSICAL:
                screen_x, screen_y = self.coord_transformer.convert_client_physical_to_screen_physical(
                    logical_x, logical_y
                )
            else:
                screen_x, screen_y = self.coord_transformer.convert_client_logical_to_screen_physical(
                    logical_x, logical_y
                )

        click_success = True
        # 只有在执行实际点击操作时，才记录和恢复鼠标位置
        original_mouse_pos = win32api.GetCursorPos()
        self.logger.debug(f"记录原鼠标位置: {original_mouse_pos}")

        try:
            win32api.SetCursorPos((screen_x, screen_y))
            time.sleep(0.1)  # 增加鼠标移动后的延迟，确保系统识别到鼠标位置变化

            mouse_down = win32con.MOUSEEVENTF_RIGHTDOWN if right_click else win32con.MOUSEEVENTF_LEFTDOWN
            mouse_up = win32con.MOUSEEVENTF_RIGHTUP if right_click else win32con.MOUSEEVENTF_LEFTUP

            for i in range(click_time):
                if i > 0:
                    time.sleep(0.2)  # 增加多次点击之间的间隔
                win32api.mouse_event(mouse_down, 0, 0, 0, 0)
                time.sleep(duration)
                win32api.mouse_event(mouse_up, 0, 0, 0, 0)
                time.sleep(0.1)  # 增加点击完成后的延迟，确保系统响应点击事件
        except Exception as e:
            self._record_error("click", f"执行鼠标点击操作失败: {str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            click_success = False
        finally:
            # 恢复原始鼠标位置
            win32api.SetCursorPos(original_mouse_pos)
            self.logger.debug(f"恢复原鼠标位置: {original_mouse_pos}")

            # 模式适配：恢复置顶状态（仅background点击模式生效）
            self._restore_window_original_topmost()

        if click_success:
            click_type = "右键" if right_click else "左键"
            self.logger.info(
                f"点击成功 | 类型: {click_type} | 次数: {click_time} | 按住时长: {duration}s | "
                f"屏幕坐标: ({screen_x},{screen_y}) | 模式: {'全屏' if ctx.is_fullscreen else '窗口'} | 来源: {click_source}"
            )

            # 仅在background模式下且操作成功时恢复原始前台窗口
            if (
                self._click_mode == "background"
                and original_foreground_hwnd
                and win32gui.IsWindow(original_foreground_hwnd)
            ):
                self._restore_foreground(original_foreground_hwnd)
            # foreground模式下保持目标窗口在前台
        return click_success

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
        # 记录原始前台窗口，仅在background模式下恢复
        original_foreground_hwnd = None
        if self._click_mode == "background":
            original_foreground_hwnd = self._get_original_foreground()

        # 激活目标窗口
        activate_success = self._ensure_window_foreground(max_attempts=3)
        if not activate_success:
            self._record_error("swipe", "无法激活窗口至前台（所有尝试失败）")
            self.logger.error(self.last_error)
            # background模式下恢复原始前台窗口
            if original_foreground_hwnd and win32gui.IsWindow(original_foreground_hwnd):
                self._restore_foreground(original_foreground_hwnd)
            return False

        # 模式适配：临时置顶（background点击模式生效，foreground点击模式跳过）
        temp_topmost_success = self._set_window_temp_topmost()

        time.sleep(0.1)
        start_pos = (start_x, start_y)
        end_pos = (end_x, end_y)

        if coord_type == CoordType.BASE:
            start_pos = self.coord_transformer.convert_original_to_current_client(*start_pos)
            end_pos = self.coord_transformer.convert_original_to_current_client(*end_pos)
        elif coord_type == CoordType.PHYSICAL:
            start_pos = self.coord_transformer.convert_client_physical_to_logical(*start_pos)
            end_pos = self.coord_transformer.convert_client_physical_to_logical(*end_pos)

        screen_start = self.coord_transformer.convert_client_logical_to_screen_physical(*start_pos)
        screen_end = self.coord_transformer.convert_client_logical_to_screen_physical(*end_pos)
        step_x = (screen_end[0] - screen_start[0]) / steps
        step_y = (screen_end[1] - screen_start[1]) / steps
        step_delay = duration / steps

        swipe_success = True
        try:
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
        except Exception as e:
            self._record_error("swipe", f"执行鼠标滑动操作失败: {str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            swipe_success = False
        finally:
            # 模式适配：恢复置顶状态
            self._restore_window_original_topmost()

        if swipe_success:
            self.logger.info(f"滑动成功 | 逻辑坐标: {start_pos} → {end_pos} | 时长: {duration}s | 步数: {steps}")

            # 仅在background模式下且操作成功时恢复原始前台窗口
            if (
                self._click_mode == "background"
                and original_foreground_hwnd
                and win32gui.IsWindow(original_foreground_hwnd)
            ):
                self._restore_foreground(original_foreground_hwnd)
            # foreground模式下保持目标窗口在前台
        return swipe_success

    @BaseDevice.require_operable
    def key_press(self, key: str, duration: float = 0.1) -> bool:
        # 记录原始前台窗口，仅在background模式下恢复
        original_foreground_hwnd = None
        if self._click_mode == "background":
            original_foreground_hwnd = self._get_original_foreground()

        # 激活目标窗口
        activate_success = self._ensure_window_foreground(max_attempts=3)
        if not activate_success:
            self._record_error("key_press", "无法激活窗口至前台")
            self.logger.error(self.last_error)
            # background模式下恢复原始前台窗口
            if original_foreground_hwnd and win32gui.IsWindow(original_foreground_hwnd):
                self._restore_foreground(original_foreground_hwnd)
            return False

        # 模式适配：临时置顶
        temp_topmost_success = self._set_window_temp_topmost()
        # 初始化点击模式（默认foreground）
        if self._click_mode is None:
            self._click_mode = "foreground"
        if not temp_topmost_success and self._click_mode == "background":
            self.logger.warning("background点击模式窗口临时置顶失败，按键操作可能不稳定")

        time.sleep(0.1)
        press_success = True
        try:
            pydirectinput.keyDown(key)
            time.sleep(duration)
            pydirectinput.keyUp(key)
        except Exception as e:
            self._record_error("key_press", f"执行键盘按键操作失败: {str(e)}")
            self.logger.error(self.last_error, exc_info=True)
            press_success = False
        finally:
            # 模式适配：恢复置顶状态（仅background点击模式生效）
            self._restore_window_original_topmost()

        if press_success:
            self.logger.info(f"按键成功 | 按键: {key} | 按住时长: {duration}s")

            # 仅在background模式下且操作成功时恢复原始前台窗口
            if (
                self._click_mode == "background"
                and original_foreground_hwnd
                and win32gui.IsWindow(original_foreground_hwnd)
            ):
                self._restore_foreground(original_foreground_hwnd)
            # foreground模式下保持目标窗口在前台
        return press_success

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
        # 记录原始前台窗口，仅在background模式下恢复
        original_foreground_hwnd = None
        if self._click_mode == "background":
            original_foreground_hwnd = self._get_original_foreground()

        # 激活目标窗口
        activate_success = self._ensure_window_foreground(max_attempts=3)
        if not activate_success:
            self._record_error("text_input", "无法激活窗口至前台")
            self.logger.error(self.last_error)
            # background模式下恢复原始前台窗口
            if original_foreground_hwnd and win32gui.IsWindow(original_foreground_hwnd):
                self._restore_foreground(original_foreground_hwnd)
            return False

        # 模式适配：临时置顶（background点击模式生效，foreground点击模式跳过）
        temp_topmost_success = self._set_window_temp_topmost()

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
            self._restore_window_original_topmost()

        if input_success:
            # 仅在background模式下且操作成功时恢复原始前台窗口
            if (
                self._click_mode == "background"
                and original_foreground_hwnd
                and win32gui.IsWindow(original_foreground_hwnd)
            ):
                self._restore_foreground(original_foreground_hwnd)
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
            if not self.hwnd:
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
        self.logger.info(
            f"开始等待模板 | 列表: {templates} | 超时: {timeout}s | 检查间隔: {interval}s | "
            f"ROI: {roi} | 截图模式: {self._screenshot_mode} | 点击模式: {self._click_mode}"
        )

        while time.time() - start_time < timeout:
            # 检查停止信号
            if self.stop_event.is_set():
                self._record_error("wait", "模板等待被停止信号中断")
                self.logger.info(self.last_error)
                return None

            # 简化处理：不再检查窗口置顶状态，由控制层处理无限等待逻辑

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

            # 简化：仅检查窗口激活状态，不再检查置顶状态
            is_foreground = win32gui.GetForegroundWindow() == self.hwnd
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

    @property
    def screenshot_mode(self) -> Optional[str]:
        """
        获取当前截图模式（foreground/background），用于UI展示。

        Returns:
            Optional[str]: 当前截图模式
        """
        return self._screenshot_mode

    @property
    def click_mode(self) -> Optional[str]:
        """
        获取当前点击模式（foreground/background），用于UI展示。

        Returns:
            Optional[str]: 当前点击模式
        """
        return self._click_mode

    @click_mode.setter
    def click_mode(self, mode: str) -> None:
        """
        设置点击模式，并根据模式联动调整截图模式。

        Args:
            mode: 点击模式，如foreground/background
        """
        self._click_mode = mode
        # 前台点击模式下，确保截图模式不是printwindow
        if mode == "foreground" and self._screenshot_mode == "printwindow":
            # 切换到合适的前台截图方法
            for method in ["bitblt", "dxcam", "temp_foreground"]:
                if method in self._available_screenshot_methods:
                    self.logger.info(f"点击模式切换为foreground，截图模式从printwindow自动切换到{method}")
                    self._screenshot_mode = method
                    self._best_screenshot_strategy = method
                    break
            else:
                # 兜底使用temp_foreground
                self.logger.info(f"点击模式切换为foreground，截图模式从printwindow自动切换到temp_foreground")
                self._screenshot_mode = "temp_foreground"
                self._best_screenshot_strategy = "temp_foreground"

    @screenshot_mode.setter
    def screenshot_mode(self, mode: str) -> None:
        """
        设置截图模式，并根据点击模式联动调整。

        Args:
            mode: 截图模式，如printwindow/bitblt/dxcam/temp_foreground
        """
        # 前台点击模式下，禁止使用printwindow
        if self._click_mode == "foreground" and mode == "printwindow":
            # 切换到合适的前台截图方法
            for method in ["bitblt", "dxcam", "temp_foreground"]:
                if method in self._available_screenshot_methods:
                    self.logger.info(f"点击模式为foreground，禁止使用printwindow，自动切换到{method}")
                    self._screenshot_mode = method
                    self._best_screenshot_strategy = method
                    return
            else:
                # 兜底使用temp_foreground
                self.logger.info(f"点击模式为foreground，禁止使用printwindow，自动切换到temp_foreground")
                self._screenshot_mode = "temp_foreground"
                self._best_screenshot_strategy = "temp_foreground"
                return

        # 正常设置截图模式
        self._screenshot_mode = mode
        # 更新最佳截图策略
        self._best_screenshot_strategy = mode

    @property
    def device_mode(self) -> Optional[str]:
        """
        获取当前设备模式（foreground/background），用于UI展示。
        兼容旧版本，返回截图模式。

        Returns:
            Optional[str]: 当前设备模式
        """
        return self._screenshot_mode
