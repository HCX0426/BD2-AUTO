"""工具模块：包含日志格式化、延迟处理、锁管理等通用工具函数"""
import time
import threading
from typing import Optional, Tuple, Union, List
from .auto_base import AutoConfig, AutoResult, AutoBaseError


class LogFormatter:
    """日志格式化工具类（统一日志输出格式）"""
    @staticmethod
    def format_roi(roi: Optional[Tuple[int, int, int, int]]) -> str:
        """格式化ROI日志信息"""
        return f"，ROI: {roi}" if roi else ""

    @staticmethod
    def format_template(template: Union[str, List[str]]) -> str:
        """格式化模板日志信息"""
        templates = [template] if isinstance(template, str) else template
        if len(templates) > 1:
            return f"{templates[0]}等{len(templates)}个模板"
        return str(templates[0])

    @staticmethod
    def format_coord_type(coord_type: str) -> str:
        """格式化坐标类型名称"""
        type_map = {
            "LOGICAL": "客户区逻辑坐标",
            "PHYSICAL": "客户区物理坐标",
            "BASE": "基准坐标"
        }
        return type_map.get(coord_type.upper(), f"未知坐标类型({coord_type})")

    @staticmethod
    def format_elapsed_time(elapsed: float) -> str:
        """格式化耗时（分/秒）"""
        minutes = int(elapsed // 60)
        seconds = round(elapsed % 60, 2)
        if minutes > 0:
            return f"{minutes}分{seconds}秒"
        return f"{seconds}秒"


class DelayManager:
    """延迟管理工具类（带中断检查的延迟）"""
    @staticmethod
    def apply_delay(secs: float, stop_event: threading.Event) -> AutoResult:
        """执行延迟，支持中断检查"""
        if secs <= 0:
            return AutoResult.success_result()
        
        start_time = time.time()
        if stop_event.wait(timeout=secs):
            return AutoResult.fail_result(
                error_msg=f"延迟{secs}秒被中断",
                elapsed_time=time.time() - start_time,
                is_interrupted=True
            )
        return AutoResult.success_result(elapsed_time=time.time() - start_time)


class LockManager:
    """锁管理工具类（线程安全）"""
    def __init__(self):
        self._lock = threading.RLock()  # 可重入锁

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        """获取锁"""
        return self._lock.acquire(blocking=blocking, timeout=timeout)

    def release(self) -> None:
        """释放锁"""
        try:
            self._lock.release()
        except RuntimeError:
            pass  # 避免重复释放

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()