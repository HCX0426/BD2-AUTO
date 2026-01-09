from PyQt6.QtCore import QThread


class AutoInitThread(QThread):
    """
    Auto实例后台初始化线程，避免阻塞UI启动
    使用信号总线与UI通信
    """

    def __init__(self, device_type="windows", device_uri=None, ocr_engine="easyocr", settings_manager=None):
        """
        初始化Auto实例后台初始化线程

        Args:
            device_type: 设备类型，支持"windows"或"adb"，默认"windows"
            device_uri: 设备URI，None则根据设备类型自动生成
            ocr_engine: OCR识别引擎类型，默认"easyocr"
            settings_manager: 设置管理器实例，用于获取永久置顶等设置
        """
        super().__init__()
        self.device_type = device_type
        self.device_uri = device_uri
        self.ocr_engine = ocr_engine
        self.settings_manager = settings_manager

    def run(self):
        """
        执行Auto实例初始化
        """
        try:
            # 不使用signal_bus发送日志，避免在QApplication创建前使用Qt信号机制
            from src.auto_control.core.auto import Auto

            auto_instance = Auto(ocr_engine=self.ocr_engine, device_type=self.device_type, device_uri=self.device_uri, settings_manager=self.settings_manager)
            # 延迟导入signal_bus，确保它已经被初始化
            from src.ui.core.signals import get_signal_bus
            signal_bus = get_signal_bus()

            # 只发送初始化完成信号，日志由主线程处理
            signal_bus.emit_init_completed(auto_instance)
        except Exception as e:
            error_msg = f"自动化核心初始化失败: {str(e)}"
            # 延迟导入signal_bus，确保它已经被初始化
            from src.ui.core.signals import get_signal_bus
            signal_bus = get_signal_bus()

            # 只发送初始化失败信号，日志由主线程处理
            signal_bus.emit_init_failed(error_msg)
