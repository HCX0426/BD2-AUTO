from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.ui.core.signals import signal_bus


class SettingsInterface(QWidget):
    """
    设置界面组件，提供应用程序的各种设置选项
    """

    def __init__(self, settings_manager, parent=None):
        """
        初始化设置界面

        Args:
            settings_manager: 设置管理器实例
            parent: 父窗口
        """
        super().__init__(parent)
        self.settings_manager = settings_manager

        # 初始化UI
        self.init_ui()

        # 加载当前设置
        self.load_settings()

        # 连接信号
        self.connect_signals()

    def init_ui(self):
        """
        初始化设置界面UI
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 应用程序设置组
        app_group = QGroupBox("应用程序设置")
        app_layout = QFormLayout()

        # 侧边栏宽度设置
        self.sidebar_width_spin = QSpinBox()
        self.sidebar_width_spin.setRange(50, 300)
        app_layout.addRow("侧边栏宽度:", self.sidebar_width_spin)

        # 自动保存设置
        self.auto_save_check = QCheckBox()
        app_layout.addRow("自动保存设置:", self.auto_save_check)

        # 日志自动清理
        self.auto_clear_log_check = QCheckBox()
        app_layout.addRow("自动清理日志:", self.auto_clear_log_check)

        # 记住界面位置和大小
        self.remember_window_pos_check = QCheckBox()
        app_layout.addRow("记住界面位置和大小:", self.remember_window_pos_check)

        app_group.setLayout(app_layout)
        layout.addWidget(app_group)

        # 设备设置组
        device_group = QGroupBox("设备设置")
        device_layout = QFormLayout()

        # 设备连接超时
        self.device_timeout_spin = QSpinBox()
        self.device_timeout_spin.setRange(5, 60)
        self.device_timeout_spin.setSuffix("秒")
        device_layout.addRow("设备连接超时:", self.device_timeout_spin)

        # 设备路径设置
        self.device_path_edit = QLineEdit()
        self.browse_path_btn = QPushButton("浏览...")
        self.browse_path_btn.setStyleSheet("padding: 8px;")
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.device_path_edit)
        path_layout.addWidget(self.browse_path_btn)
        device_layout.addRow("设备路径:", path_layout)

        device_group.setLayout(device_layout)
        layout.addWidget(device_group)

        # 任务设置组
        task_group = QGroupBox("任务设置")
        task_layout = QFormLayout()

        # 任务执行超时
        self.task_timeout_spin = QSpinBox()
        self.task_timeout_spin.setRange(10, 300)
        self.task_timeout_spin.setSuffix("秒")
        task_layout.addRow("任务执行超时:", self.task_timeout_spin)

        # 自动重试次数
        self.retry_count_spin = QSpinBox()
        self.retry_count_spin.setRange(0, 5)
        task_layout.addRow("自动重试次数:", self.retry_count_spin)

        task_group.setLayout(task_layout)
        layout.addWidget(task_group)

        # 按钮组
        button_layout = QHBoxLayout()

        self.save_btn = QPushButton("保存设置")
        self.save_btn.setStyleSheet("padding: 8px;")
        self.reset_btn = QPushButton("重置设置")
        self.reset_btn.setStyleSheet("padding: 8px;")

        button_layout.addStretch(1)
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.reset_btn)

        layout.addLayout(button_layout)

    def connect_signals(self):
        """
        连接信号
        """
        self.save_btn.clicked.connect(self.save_settings)
        self.reset_btn.clicked.connect(self.reset_settings)
        self.browse_path_btn.clicked.connect(self.browse_device_path)

    def load_settings(self):
        """
        加载当前设置
        """
        # 加载侧边栏宽度
        self.sidebar_width_spin.setValue(self.settings_manager.get_setting("sidebar_width", 200))

        # 加载自动保存设置
        self.auto_save_check.setChecked(self.settings_manager.get_setting("auto_save_settings", True))

        # 加载日志自动清理设置
        self.auto_clear_log_check.setChecked(self.settings_manager.get_setting("auto_clear_log", False))

        # 加载记住界面位置和大小设置
        self.remember_window_pos_check.setChecked(self.settings_manager.get_setting("remember_window_pos", True))

        # 加载设备连接超时
        self.device_timeout_spin.setValue(self.settings_manager.get_setting("device_timeout", 10))

        # 加载设备路径
        self.device_path_edit.setText(self.settings_manager.get_setting("device_path", ""))

        # 加载任务执行超时
        self.task_timeout_spin.setValue(self.settings_manager.get_setting("task_timeout", 60))

        # 加载自动重试次数
        self.retry_count_spin.setValue(self.settings_manager.get_setting("retry_count", 0))

    def save_settings(self):
        """
        保存设置
        """
        # 获取信号总线实例
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        # 保存侧边栏宽度
        self.settings_manager.set_setting("sidebar_width", self.sidebar_width_spin.value())

        # 保存自动保存设置
        self.settings_manager.set_setting("auto_save_settings", self.auto_save_check.isChecked())

        # 保存日志自动清理设置
        self.settings_manager.set_setting("auto_clear_log", self.auto_clear_log_check.isChecked())

        # 保存记住界面位置和大小设置
        self.settings_manager.set_setting("remember_window_pos", self.remember_window_pos_check.isChecked())

        # 保存设备连接超时
        self.settings_manager.set_setting("device_timeout", self.device_timeout_spin.value())

        # 保存设备路径
        self.settings_manager.set_setting("device_path", self.device_path_edit.text())

        # 保存任务执行超时
        self.settings_manager.set_setting("task_timeout", self.task_timeout_spin.value())

        # 保存自动重试次数
        self.settings_manager.set_setting("retry_count", self.retry_count_spin.value())

        # 保存到文件
        self.settings_manager.save_settings()

        # 发送侧边栏宽度变更信号
        signal_bus.emit_sidebar_width_changed(self.sidebar_width_spin.value())

        signal_bus.emit_log("设置已保存")

    def reset_settings(self):
        """
        重置设置为默认值
        """
        # 获取信号总线实例
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        # 设置默认值
        self.sidebar_width_spin.setValue(60)
        self.auto_save_check.setChecked(True)
        self.auto_clear_log_check.setChecked(False)
        self.remember_window_pos_check.setChecked(True)
        self.device_timeout_spin.setValue(10)
        self.device_path_edit.setText("")
        self.task_timeout_spin.setValue(60)
        self.retry_count_spin.setValue(0)

        # 发送侧边栏宽度变更信号
        signal_bus.emit_sidebar_width_changed(60)

        signal_bus.emit_log("设置已重置为默认值")

    def browse_device_path(self):
        """
        浏览设备路径
        """
        dir_path = QFileDialog.getExistingDirectory(self, "选择设备路径")
        if dir_path:
            self.device_path_edit.setText(dir_path)
