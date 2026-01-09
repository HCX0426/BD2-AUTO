import sys

from PyQt6.QtCore import QObject, pyqtSignal


class SignalBus(QObject):
    """信号总线类，实现线程与UI的解耦，简单实现"""

    # 日志更新信号
    log_updated = pyqtSignal(str)
    # 进度更新信号
    progress_updated = pyqtSignal(int)
    # 任务完成信号
    task_finished = pyqtSignal()
    # 初始化完成信号
    init_completed = pyqtSignal(object)
    # 初始化失败信号
    init_failed = pyqtSignal(str)
    # 主题变更信号
    theme_changed = pyqtSignal(str)
    # 侧边栏宽度变更信号
    sidebar_width_changed = pyqtSignal(int)
    # 窗口大小变更信号
    window_size_changed = pyqtSignal(list)
    # 任务状态更新信号
    task_status_updated = pyqtSignal(str, bool)
    # 设备状态更新信号
    device_status_updated = pyqtSignal(str, bool)

    def __init__(self):
        """初始化信号总线"""
        super().__init__()

    # 便捷方法
    def emit_log(self, message):
        """发送日志信息"""
        self.log_updated.emit(message)

    def emit_progress(self, progress):
        """发送进度更新"""
        self.progress_updated.emit(progress)

    def emit_task_finished(self):
        """发送任务完成信号"""
        self.task_finished.emit()

    def emit_init_completed(self, auto_instance):
        """发送初始化完成信号"""
        self.init_completed.emit(auto_instance)

    def emit_init_failed(self, error_msg):
        """发送初始化失败信号"""
        self.init_failed.emit(error_msg)

    def emit_task_status_updated(self, task_type, is_running):
        """发送任务状态更新信号"""
        self.task_status_updated.emit(task_type, is_running)

    def emit_device_status_updated(self, action, is_running):
        """发送设备状态更新信号"""
        self.device_status_updated.emit(action, is_running)

    def emit_sidebar_width_changed(self, width):
        """发送侧边栏宽度变更信号"""
        self.sidebar_width_changed.emit(width)

    def emit_window_size_changed(self, size):
        """发送窗口大小变更信号"""
        self.window_size_changed.emit(size)


# 创建信号总线实例（在QApplication创建后使用）
class SignalBusHolder:
    def __init__(self):
        self._signal_bus = None

    def get(self):
        """获取信号总线实例"""
        if self._signal_bus is None:
            self._signal_bus = SignalBus()
        return self._signal_bus


# 创建全局的信号总线持有者
_bus_holder = SignalBusHolder()


def get_signal_bus():
    """获取信号总线实例，确保在QApplication创建后调用"""
    return _bus_holder.get()


def init_signal_bus():
    """初始化信号总线，需要在QApplication创建后调用"""
    return get_signal_bus()
