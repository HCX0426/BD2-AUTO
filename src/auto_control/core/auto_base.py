"""基础定义模块：包含返回值、配置、自定义异常等核心基础类"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

# 外部配置管理
from src.core.config_manager import config

# 类型别名（提升代码可读性）
StepFunc = TypeVar("StepFunc", bound=Callable[..., "AutoResult"])
VerifyFunc = TypeVar("VerifyFunc", bound=Callable[..., "AutoResult"])
DeviceURI = TypeVar("DeviceURI", str, None)
ROI = TypeVar("ROI", Tuple[int, int, int, int], None)


# ======================== 自定义异常类 ========================
class AutoBaseError(Exception):
    """Auto模块基础异常（所有自定义异常的父类）"""

    pass


class DeviceError(AutoBaseError):
    """设备相关异常（连接/操作失败等）"""

    pass


class VerifyError(AutoBaseError):
    """验证/等待相关异常（超时/未找到目标等）"""

    pass


class StepExecuteError(AutoBaseError):
    """链式步骤执行异常"""

    pass


class CoordinateError(AutoBaseError):
    """坐标转换/操作异常"""

    pass


# ======================== 配置类（统一管理默认值） ========================
@dataclass(frozen=True)  # 不可变配置，避免运行时篡改
class AutoConfig:
    """自动化系统配置类（所有默认值统一管理）"""

    # 延迟配置（秒）
    CLICK_DELAY: float = field(default_factory=lambda: config.get("framework.default_click_delay", 0.2))
    AFTER_CLICK_DELAY: float = field(default_factory=lambda: config.get("framework.default_after_click_delay", 0.5))
    CHECK_ELEMENT_DELAY: float = field(default_factory=lambda: config.get("framework.default_check_element_delay", 0.5))
    KEY_DURATION: float = field(default_factory=lambda: config.get("framework.default_key_duration", 0.1))
    TEXT_INPUT_INTERVAL: float = 0.05

    # 超时配置（秒）
    DEFAULT_WAIT_TIMEOUT: int = field(default_factory=lambda: config.get("framework.default_wait_timeout", 20))
    DEFAULT_DEVICE_TIMEOUT: float = 10.0
    DEFAULT_TASK_TIMEOUT: int = field(default_factory=lambda: config.get("framework.default_task_timeout", 300))

    # 重试配置
    DEFAULT_STEP_RETRY: int = 1
    DEFAULT_VERIFY_RETRY: int = 3
    DEFAULT_OPERATION_RETRY: int = 0
    DEFAULT_BACK_RETRY: int = 1  # 回退到上一步的重试次数

    # 坐标/分辨率配置
    BASE_RESOLUTION: Tuple[int, int] = field(
        default_factory=lambda: config.get("framework.default_base_resolution", (1920, 1080))
    )
    DEFAULT_COORD_TYPE: str = "LOGICAL"

    # 设备配置
    DEFAULT_DEVICE_URI: str = field(
        default_factory=lambda: config.get("framework.default_device_uri", "windows://default")
    )
    DEFAULT_OCR_ENGINE: str = field(default_factory=lambda: config.get("framework.default_ocr_engine", "easyocr"))

    # 模板配置
    TEMPLATE_EXTENSIONS: Tuple[str, ...] = field(
        default_factory=lambda: tuple(config.get("framework.template_extensions", (".png", ".jpg", ".jpeg", ".bmp")))
    )

    # 滑动配置
    DEFAULT_SWIPE_DURATION: float = 3.0
    DEFAULT_SWIPE_STEPS: int = 10

    # 文本匹配配置
    DEFAULT_TEXT_FUZZY_MATCH: bool = field(
        default_factory=lambda: config.get("framework.default_text_fuzzy_match", True)
    )

    # 窗口操作配置
    DEFAULT_WINDOW_OPERATION_DELAY: float = field(
        default_factory=lambda: config.get("framework.default_window_operation_delay", 0.0)
    )

    # 截图配置
    DEFAULT_SCREENSHOT_DELAY: float = field(
        default_factory=lambda: config.get("framework.default_screenshot_delay", 0.0)
    )

    # 日志配置
    LOG_LEVEL: str = "INFO"


# ======================== 统一返回值类 ========================
@dataclass
class AutoResult:
    """自动化操作统一返回值类"""

    success: bool  # 核心状态：操作是否成功
    data: Optional[Any] = None  # 附加数据（坐标/文本/设备信息等）
    error_msg: Optional[str] = None  # 失败原因
    elapsed_time: float = 0.0  # 操作总耗时（秒）
    retry_count: int = 0  # 实际重试次数
    is_interrupted: bool = False  # 是否因中断导致失败

    # 兼容原有bool判断逻辑（平滑过渡）
    def __bool__(self) -> bool:
        return self.success

    # 友好的字符串表示（方便调试/日志）
    def __repr__(self) -> str:
        return (
            f"AutoResult(success={self.success}, data={self.data}, "
            f"error='{self.error_msg}', elapsed={self.elapsed_time:.2f}s, "
            f"retry={self.retry_count}, interrupted={self.is_interrupted})"
        )

    # 快捷方法：创建成功结果
    @classmethod
    def success_result(cls, data: Any = None, elapsed_time: float = 0.0, retry_count: int = 0) -> "AutoResult":
        return cls(success=True, data=data, elapsed_time=elapsed_time, retry_count=retry_count)

    # 快捷方法：创建失败结果
    @classmethod
    def fail_result(
        cls, error_msg: str, elapsed_time: float = 0.0, retry_count: int = 0, is_interrupted: bool = False
    ) -> "AutoResult":
        return cls(
            success=False,
            error_msg=error_msg,
            elapsed_time=elapsed_time,
            retry_count=retry_count,
            is_interrupted=is_interrupted,
        )
