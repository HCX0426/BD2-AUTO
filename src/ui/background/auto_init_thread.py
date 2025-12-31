from PyQt6.QtCore import QThread


class AutoInitThread(QThread):
    """
    Auto实例后台初始化线程，避免阻塞UI启动
    使用信号总线与UI通信
    """

    def __init__(self):
        """
        初始化Auto实例后台初始化线程
        """
        super().__init__()

    def run(self):
        """
        执行Auto实例初始化
        """
        try:
            # 不使用signal_bus发送日志，避免在QApplication创建前使用Qt信号机制
            from src.auto_control.core.auto import Auto

            auto_instance = Auto()
            # 延迟导入signal_bus，确保它已经被初始化
            from src.ui.core.signals import signal_bus

            # 只发送初始化完成信号，日志由主线程处理
            signal_bus.emit_init_completed(auto_instance)
        except Exception as e:
            error_msg = f"自动化核心初始化失败: {str(e)}"
            # 延迟导入signal_bus，确保它已经被初始化
            from src.ui.core.signals import signal_bus

            # 只发送初始化失败信号，日志由主线程处理
            signal_bus.emit_init_failed(error_msg)
