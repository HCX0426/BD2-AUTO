from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Optional, Tuple, Callable, Union, List
from threading import Lock
from functools import wraps
from typing import Callable, Any


class DeviceState(Enum):
    """设备状态枚举，覆盖全生命周期的互斥状态"""
    DISCONNECTED = auto()  # 设备已断开
    CONNECTING = auto()    # 连接中
    CONNECTED = auto()     # 设备已连接（基础状态）
    BUSY = auto()          # 设备忙（执行操作中）
    IDLE = auto()          # 设备空闲（已连接且可操作）
    ERROR = auto()         # 设备错误


class BaseDevice(ABC):
    """
    设备控制抽象基类，带严格的状态管理：
    - 状态转换校验（防止不合理状态覆盖）
    - 线程安全（状态更新加锁）
    - 状态变化回调（支持上层监听）
    """
    # 合法状态转换表：key为当前状态，value为允许转换到的状态列表
    _VALID_TRANSITIONS = {
        DeviceState.DISCONNECTED: [DeviceState.CONNECTING, DeviceState.ERROR],
        DeviceState.CONNECTING: [DeviceState.CONNECTED, DeviceState.DISCONNECTED, DeviceState.ERROR],
        DeviceState.CONNECTED: [DeviceState.IDLE, DeviceState.DISCONNECTED, DeviceState.ERROR],
        DeviceState.IDLE: [DeviceState.BUSY, DeviceState.DISCONNECTED, DeviceState.ERROR],
        DeviceState.BUSY: [DeviceState.IDLE, DeviceState.DISCONNECTED, DeviceState.ERROR],
        DeviceState.ERROR: [DeviceState.DISCONNECTED, DeviceState.CONNECTING]
    }

    def __init__(self, device_uri: str):
        self.device_uri = device_uri
        self.resolution: Tuple[int, int] = (0, 0)  # 设备分辨率
        self.minimized = False  # 是否最小化
        self.state = DeviceState.DISCONNECTED  # 初始状态
        self.last_error: Optional[str] = None  # 最后一次错误信息
        self._state_lock = Lock()  # 状态更新锁（保证线程安全）
        self._state_listeners = []  # 状态变化监听器

    @property
    def is_connected(self) -> bool:
        """从状态推导是否已连接（替代原self.connected）"""
        return self.state in [DeviceState.CONNECTED, DeviceState.IDLE, DeviceState.BUSY]

    @property
    def is_operable(self) -> bool:
        """判断设备是否可执行操作（已连接且非忙碌/错误）"""
        return self.state in [DeviceState.CONNECTED, DeviceState.IDLE]

    def _update_device_state(self, new_state: DeviceState) -> bool:
        """
        线程安全的状态更新，仅允许合法状态转换
        :return: 状态是否更新成功
        """
        with self._state_lock:  # 加锁保证原子操作
            
            current_state = self.state
            if new_state == current_state:
                return True  # 相同状态不触发转换
            
            # 校验转换状态转换转换合法性
            if new_state not in self._VALID_TRANSITIONS.get(current_state, []):
                print(f"状态转换错误: 不允许从 {current_state.name} 转换到 {new_state.name}")
                return False
            
            # 执行状态更新
            old_state = current_state
            self.state = new_state
            self._trigger_state_listeners(old_state, new_state)
            return True

    def add_state_listener(self, callback: Callable[[DeviceState, DeviceState], None]) -> None:
        """
        添加状态变化监听器
        :param callback: 回调函数，参数为 (旧状态, 新状态)
        """
        if callback not in self._state_listeners:
            self._state_listeners.append(callback)

    def remove_state_listener(self, callback: Callable[[DeviceState, DeviceState], None]) -> None:
        """移除状态变化监听器"""
        if callback in self._state_listeners:
            self._state_listeners.remove(callback)

    def _trigger_state_listeners(self, old_state: DeviceState, new_state: DeviceState) -> None:
        """触发所有状态监听器
        :param old_state: 旧状态
        :param new_state: 新状态
        """
        for callback in self._state_listeners:
            try:
                callback(old_state, new_state)
            except Exception as e:
                print(f"状态监听器执行失败: {str(e)}")

    @classmethod
    def require_operable(cls, func):
        """
        类方法装饰器：校验设备是否可操作，并尝试切换为BUSY状态
        """
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # 1. 校验设备是否可操作（CONNECTED/IDLE）
            if not self.is_operable:
                error_msg = f"无法执行 {func.__name__}：设备状态为 {self.state.name}"
                print(error_msg)
                self.last_error = error_msg
                return False

            # 2. 尝试切换为BUSY状态
            if not self._update_device_state(DeviceState.BUSY):
                error_msg = f"无法执行 {func.__name__}：当前状态不允许切换为BUSY"
                print(error_msg)
                self.last_error = error_msg
                return False

            # 3. 执行原方法
            try:
                result = func(self, *args, **kwargs)
                # 操作成功，恢复为IDLE状态
                self._update_device_state(DeviceState.IDLE)
                return result
            except Exception as e:
                # 若原方法抛出异常，自动记录错误并恢复状态
                error_msg = f"{func.__name__} 执行异常: {str(e)}"
                print(error_msg)
                self.last_error = error_msg
                
                # 根据错误类型决定是否转为ERROR状态
                if hasattr(self, '_should_change_to_error_state') and \
                self._should_change_to_error_state(error_msg):
                    self._update_device_state(DeviceState.ERROR)
                else:
                    self._update_device_state(DeviceState.IDLE)
                return False

        return wrapper

    # 以下为设备操作抽象方法（子类必须实现）
    @abstractmethod
    def connect(self, timeout: float = 10.0) -> bool:
        """连接设备"""
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        """断开连接并清理资源"""
        pass

    @abstractmethod
    def capture_screen(self) -> Optional[bytes]:
        """捕获屏幕截图"""
        pass

    @abstractmethod
    def click(self, pos: Union[Tuple[int, int], str, List[str]],
              click_time: int = 1,
              duration: float = 0.1,
              right_click: bool = False,
              is_base_coord: bool = False,
              roi: Optional[Tuple[int, int, int, int]] = None,
              is_physical_coord: bool = False) -> bool:
        """点击指定位置或模板"""
        pass

    @abstractmethod
    def key_press(self, key: str, duration: float = 0.1) -> bool:
        """按键操作"""
        pass

    @abstractmethod
    def text_input(self, text: str, interval: float = 0.05) -> bool:
        """文本输入"""
        pass

    @abstractmethod
    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, 
              duration: float = 0.5) -> bool:
        """滑动操作"""
        pass

    @abstractmethod
    def wait(self, template, timeout: float = 10.0) -> bool:
        """等待元素出现"""
        pass

    @abstractmethod
    def exists(self, template) -> bool:
        """检查元素是否存在"""
        pass

    @abstractmethod
    def sleep(self, secs: float) -> bool:
        """设备睡眠"""
        pass

    def set_foreground(self) -> bool:
        """将窗口置前"""
        pass

    def get_resolution(self) -> Tuple[int, int]:
        """获取设备分辨率"""
        return self.resolution

    def is_minimized(self) -> bool:
        """检查是否最小化"""
        return self.minimized

    def get_state(self) -> DeviceState:
        """获取设备当前状态"""
        return self.state
    