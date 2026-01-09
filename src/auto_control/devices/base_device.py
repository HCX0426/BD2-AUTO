from abc import ABC, abstractmethod
from enum import Enum, auto
from functools import wraps
from threading import Lock
from typing import Callable, List, Optional, Tuple, Union


class DeviceState(Enum):
    DISCONNECTED = auto()
    CONNECTED = auto()
    BUSY = auto()
    ERROR = auto()


class BaseDevice(ABC):
    """
    设备控制抽象基类，定义所有设备控制器的核心接口与通用能力。

    核心能力：
    1. 线程安全的设备状态管理（DISCONNECTED/CONNECTED/BUSY/ERROR）
    2. 标准化的错误记录与清空机制
    3. 操作前置校验装饰器（确保设备可操作状态）
    4. 设备控制核心接口的抽象定义
    """

    def __init__(self, device_uri: str, logger=None):
        self.device_uri = device_uri
        self.last_error: Optional[str] = None
        self._state = DeviceState.DISCONNECTED
        self._state_lock = Lock()

        # 日志实例
        self.logger = logger

        # 截图和点击模式（新增）
        self._screenshot_mode: Optional[str] = None  # 截图模式：printwindow/bitblt/dxcam/temp_foreground
        self._click_mode: Optional[str] = None  # 点击模式：foreground/background
        self._available_screenshot_methods: List[str] = []  # 可用截图方法列表

    @property
    def state(self) -> DeviceState:
        """
        线程安全获取设备当前状态。

        Returns:
            DeviceState: 设备当前状态枚举值
        """
        with self._state_lock:
            return self._state

    @state.setter
    def state(self, value: DeviceState):
        """
        禁止直接修改状态，强制通过 _update_state 方法更新以保证线程安全。

        Raises:
            RuntimeError: 直接赋值时触发异常
        """
        raise RuntimeError("禁止直接修改状态，请调用 _update_state 方法")

    def _update_state(self, new_state: DeviceState) -> bool:
        """
        线程安全更新设备状态，仅当新状态与当前状态不同时执行更新。

        Args:
            new_state: 待更新的设备状态

        Returns:
            bool: 状态是否成功变更（相同状态返回False，不同返回True）
        """
        with self._state_lock:
            if self._state == new_state:
                return False
            self._state = new_state
            return True

    @property
    def is_connected(self) -> bool:
        """
        判断设备是否处于已连接状态。

        Returns:
            bool: 已连接返回True，否则返回False
        """
        return self.state == DeviceState.CONNECTED

    @property
    def is_operable(self) -> bool:
        """
        判断设备是否处于可执行操作的状态（仅CONNECTED状态可操作）。

        Returns:
            bool: 可操作返回True，否则返回False
        """
        return self.state in [DeviceState.CONNECTED]

    def clear_last_error(self) -> None:
        """清空最后一次记录的错误信息，建议在每次操作执行前调用。"""
        self.last_error = None

    def _record_error(self, method_name: str, error_msg: str) -> None:
        """
        标准化记录错误信息，格式为 [方法名] 错误描述。

        Args:
            method_name: 发生错误的方法名称
            error_msg: 具体的错误描述信息
        """
        self.last_error = f"[{method_name}] {error_msg}"

    @classmethod
    def require_operable(cls, func: Callable) -> Callable:
        """
        装饰器：为设备操作方法添加前置校验与状态管理。
        执行流程：
        1. 清空历史错误信息
        2. 校验设备是否处于可操作状态
        3. 将设备状态切换为BUSY
        4. 执行目标操作（捕获所有异常）
        5. 操作成功恢复CONNECTED状态，异常则切换为ERROR状态

        Args:
            func: 需要装饰的设备操作方法

        Returns:
            Callable: 装饰后的方法
        """

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            self.clear_last_error()

            if not self.is_operable:
                error_msg = f"设备状态异常（当前：{self.state.name}），无法执行操作"
                self._record_error(func.__name__, error_msg)
                if self.logger:
                    self.logger.error(self.last_error)
                return False

            if not self._update_state(DeviceState.BUSY):
                error_msg = "状态切换为BUSY失败"
                self._record_error(func.__name__, error_msg)
                if self.logger:
                    self.logger.error(self.last_error)
                return False

            try:
                result = func(self, *args, **kwargs)
                self._update_state(DeviceState.CONNECTED)
                return result
            except Exception as e:
                error_msg = f"执行异常：{str(e)}"
                self._record_error(func.__name__, error_msg)
                if self.logger:
                    self.logger.error(self.last_error, exc_info=True)
                self._update_state(DeviceState.ERROR)
                return False

        return wrapper

    @abstractmethod
    def connect(self, timeout: float = 10.0) -> bool:
        """
        连接设备，超时未连接则返回失败。

        Args:
            timeout: 连接超时时间（秒），默认10.0秒

        Returns:
            bool: 连接成功返回True，失败返回False
        """
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        """
        断开设备连接，清理设备相关资源。

        Returns:
            bool: 断开成功返回True，失败返回False
        """
        pass

    @abstractmethod
    def capture_screen(self, roi: Optional[Tuple[int, int, int, int]] = None) -> Optional[any]:
        """
        捕获设备屏幕图像，支持指定ROI区域裁剪。

        Args:
            roi: 感兴趣区域，格式为 (x, y, width, height)，None表示全屏

        Returns:
            Optional[any]: 截图图像对象（格式由子类实现定义），失败返回None
        """
        pass

    @abstractmethod
    def click(
        self,
        pos: Union[Tuple[int, int], str, list],
        click_time: int = 1,
        duration: float = 0.1,
        right_click: bool = False,
        coord_type: any = None,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> bool:
        """
        执行鼠标点击操作，支持坐标点击或模板匹配点击。

        Args:
            pos: 点击位置，支持三种格式：
                 - (x, y)：直接坐标
                 - str：模板名称（模板匹配点击）
                 - list：模板名称列表（多模板匹配，匹配到任一即点击）
            click_time: 点击次数，默认1次
            duration: 单次点击按住时长（秒），默认0.1秒
            right_click: 是否右键点击，默认False（左键）
            coord_type: 坐标类型（由子类定义具体枚举）
            roi: 模板匹配时的ROI区域，None表示全图

        Returns:
            bool: 点击成功返回True，失败返回False
        """
        pass

    @abstractmethod
    def key_press(self, key: str, duration: float = 0.1) -> bool:
        """
        执行按键操作，按下并释放指定按键。

        Args:
            key: 按键名称（如"enter"、"space"，具体由子类定义）
            duration: 按键按住时长（秒），默认0.1秒

        Returns:
            bool: 按键成功返回True，失败返回False
        """
        pass

    @abstractmethod
    def text_input(self, text: str, interval: float = 0.05) -> bool:
        """
        输入指定文本内容，支持逐字符输入或批量粘贴（子类实现）。

        Args:
            text: 待输入的文本内容
            interval: 逐字符输入时的间隔时间（秒），默认0.05秒

        Returns:
            bool: 输入成功返回True，失败返回False
        """
        pass

    @abstractmethod
    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.3,
        steps: int = 10,
        coord_type: any = None,
    ) -> bool:
        """
        执行滑动操作，从起始坐标滑动到结束坐标。

        Args:
            start_x: 滑动起始点X坐标
            start_y: 滑动起始点Y坐标
            end_x: 滑动结束点X坐标
            end_y: 滑动结束点Y坐标
            duration: 滑动总时长（秒），默认0.3秒
            steps: 滑动步数（越大越平滑），默认10步
            coord_type: 坐标类型（由子类定义具体枚举）

        Returns:
            bool: 滑动成功返回True，失败返回False
        """
        pass

    @abstractmethod
    def exists(
        self,
        template_name: Union[str, list],
        threshold: float = 0.8,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[Tuple[int, int]]:
        """
        检查指定模板元素是否存在，返回匹配到的中心点坐标。

        Args:
            template_name: 模板名称（str）或模板列表（list）
            threshold: 模板匹配阈值（0-1），默认0.8
            roi: 模板匹配的ROI区域，None表示全图

        Returns:
            Optional[Tuple[int, int]]: 匹配到的模板中心点坐标，未匹配返回None
        """
        pass

    def sleep(self, secs: float, stop_event: Optional[any] = None) -> bool:
        """
        设备休眠指定时长，支持通过停止事件中断休眠。

        Args:
            secs: 休眠时长（秒），必须大于0
            stop_event: 停止事件对象（需实现wait方法），None表示不支持中断

        Returns:
            bool: 休眠完成返回True，被中断/异常返回False

        Raises:
            Exception: 休眠过程中出现的异常（已捕获并记录）
        """
        import time

        if secs <= 0:
            self._record_error("sleep", "睡眠时间必须大于0")
            if self.logger:
                self.logger.warning(self.last_error)
            return False
        try:
            if stop_event and stop_event.wait(timeout=secs):
                self._record_error("sleep", "睡眠被停止信号中断")
                return False
            time.sleep(secs)
            return True
        except Exception as e:
            self._record_error("sleep", f"睡眠异常：{str(e)}")
            if self.logger:
                self.logger.error(self.last_error, exc_info=True)
            return False

    def set_foreground(self) -> bool:
        """
        将设备窗口置为前台（激活窗口），子类需重写实现具体逻辑。

        Returns:
            bool: 置前成功返回True，失败返回False
        """
        return False

    def is_minimized(self) -> bool:
        """
        检查设备窗口是否处于最小化状态，子类需重写实现具体逻辑。

        Returns:
            bool: 最小化返回True，否则返回False
        """
        return False

    @property
    def screenshot_mode(self) -> Optional[str]:
        """
        获取截图模式

        Returns:
            Optional[str]: 截图模式，如printwindow/bitblt/dxcam/temp_foreground
        """
        return self._screenshot_mode

    @screenshot_mode.setter
    def screenshot_mode(self, mode: str) -> None:
        """
        设置截图模式

        Args:
            mode: 截图模式，如printwindow/bitblt/dxcam/temp_foreground
        """
        self._screenshot_mode = mode

    @property
    def click_mode(self) -> Optional[str]:
        """
        获取点击模式

        Returns:
            Optional[str]: 点击模式，如foreground/background
        """
        return self._click_mode

    @click_mode.setter
    def click_mode(self, mode: str) -> None:
        """
        设置点击模式

        Args:
            mode: 点击模式，如foreground/background
        """
        self._click_mode = mode

    @property
    def available_screenshot_methods(self) -> List[str]:
        """
        获取可用截图方法列表

        Returns:
            List[str]: 可用截图方法列表
        """
        return self._available_screenshot_methods
