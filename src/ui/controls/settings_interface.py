from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
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

        # 设备类型选择
        self.device_type_combo = QComboBox()
        self.device_type_combo.addItems(["窗口设备", "ADB设备"])
        device_layout.addRow("设备类型:", self.device_type_combo)

        # 设备连接超时
        self.device_timeout_spin = QSpinBox()
        self.device_timeout_spin.setRange(5, 60)
        self.device_timeout_spin.setSuffix("秒")
        device_layout.addRow("设备连接超时:", self.device_timeout_spin)

        # 设备路径设置
        self.device_path_edit = QLineEdit()
        self.browse_path_btn = QPushButton("浏览...")
        self.browse_path_btn.setStyleSheet("padding: 8px;")
        self.test_connection_btn = QPushButton("测试连接")
        self.test_connection_btn.setStyleSheet("padding: 8px;")
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.device_path_edit)
        path_layout.addWidget(self.browse_path_btn)
        path_layout.addWidget(self.test_connection_btn)
        device_layout.addRow("设备路径:", path_layout)

        # 添加命令行参数输入框
        self.device_args_edit = QLineEdit()
        device_layout.addRow("启动参数:", self.device_args_edit)

        # 截图模式选择
        self.screenshot_mode_combo = QComboBox()
        self.screenshot_mode_combo.addItems(["自动选择", "PrintWindow", "BitBlt", "DXCam", "临时激活"])
        device_layout.addRow("截图模式:", self.screenshot_mode_combo)

        # 点击模式选择
        self.click_mode_combo = QComboBox()
        self.click_mode_combo.addItems(["前台点击", "后台点击"])
        device_layout.addRow("点击模式:", self.click_mode_combo)

        device_group.setLayout(device_layout)
        layout.addWidget(device_group)

        # 任务设置组
        task_group = QGroupBox("任务设置")
        task_layout = QFormLayout()

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
        self.test_connection_btn.clicked.connect(self.test_device_connection)
        # 点击模式变化时联动截图模式
        self.click_mode_combo.currentIndexChanged.connect(self._update_screenshot_mode_options)

        # 连接设置变化信号，实现自动保存
        self.auto_save_check.stateChanged.connect(self.on_setting_changed)
        self.auto_clear_log_check.stateChanged.connect(self.on_setting_changed)
        self.remember_window_pos_check.stateChanged.connect(self.on_setting_changed)
        self.sidebar_width_spin.valueChanged.connect(self.on_setting_changed)
        self.device_timeout_spin.valueChanged.connect(self.on_setting_changed)
        self.device_type_combo.currentIndexChanged.connect(self.on_setting_changed)
        self.device_path_edit.textChanged.connect(self.on_setting_changed)
        self.device_args_edit.textChanged.connect(self.on_setting_changed)
        self.screenshot_mode_combo.currentIndexChanged.connect(self.on_setting_changed)
        self.click_mode_combo.currentIndexChanged.connect(self.on_setting_changed)
        self.retry_count_spin.valueChanged.connect(self.on_setting_changed)

    def _update_screenshot_mode_options(self):
        """
        更新截图模式选项，根据点击模式联动禁用/启用PrintWindow
        """
        current_click_mode = self.click_mode_combo.currentText()

        # 前台点击模式下禁用PrintWindow选项
        if current_click_mode == "前台点击":
            # 禁用PrintWindow选项
            printwindow_index = self.screenshot_mode_combo.findText("PrintWindow")
            if printwindow_index != -1:
                # 如果当前选中的是PrintWindow，自动切换到BitBlt
                if self.screenshot_mode_combo.currentIndex() == printwindow_index:
                    self.screenshot_mode_combo.setCurrentText("BitBlt")

        # 重新启用所有选项，然后根据需要禁用
        for i in range(self.screenshot_mode_combo.count()):
            self.screenshot_mode_combo.model().item(i).setEnabled(True)

        # 再次检查并禁用PrintWindow（如果需要）
        if current_click_mode == "前台点击":
            printwindow_index = self.screenshot_mode_combo.findText("PrintWindow")
            if printwindow_index != -1:
                self.screenshot_mode_combo.model().item(printwindow_index).setEnabled(False)

    def on_setting_changed(self):
        """
        设置项变化时触发的槽函数，实现自动保存功能
        """
        # 检查是否启用了自动保存
        if self.auto_save_check.isChecked():
            # 调用保存设置方法
            self.save_settings()

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
        self.remember_window_pos_check.setChecked(self.settings_manager.get_setting("remember_window_pos", False))

        # 加载设备连接超时
        self.device_timeout_spin.setValue(self.settings_manager.get_setting("device_timeout", 10))

        # 加载设备类型
        device_type = self.settings_manager.get_setting("device_type", "windows")
        device_type_index = 0 if device_type == "windows" else 1
        self.device_type_combo.setCurrentIndex(device_type_index)

        # 加载设备路径
        self.device_path_edit.setText(self.settings_manager.get_setting("device_path", ""))

        # 加载设备启动参数
        self.device_args_edit.setText(self.settings_manager.get_setting("device_args", ""))

        # 加载截图模式
        screenshot_mode = self.settings_manager.get_setting("screenshot_mode", "自动选择")
        self.screenshot_mode_combo.setCurrentText(screenshot_mode)

        # 加载点击模式
        click_mode = self.settings_manager.get_setting("click_mode", "前台点击")
        self.click_mode_combo.setCurrentText(click_mode)

        # 加载自动重试次数
        self.retry_count_spin.setValue(self.settings_manager.get_setting("retry_count", 0))

        # 初始加载时更新截图模式选项可用性
        self._update_screenshot_mode_options()

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

        # 保存设备类型
        device_type = "windows" if self.device_type_combo.currentIndex() == 0 else "adb"
        self.settings_manager.set_setting("device_type", device_type)

        # 保存设备路径
        self.settings_manager.set_setting("device_path", self.device_path_edit.text())

        # 保存设备启动参数
        self.settings_manager.set_setting("device_args", self.device_args_edit.text())

        # 保存截图模式
        self.settings_manager.set_setting("screenshot_mode", self.screenshot_mode_combo.currentText())

        # 保存点击模式
        self.settings_manager.set_setting("click_mode", self.click_mode_combo.currentText())

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
        self.remember_window_pos_check.setChecked(False)
        self.device_timeout_spin.setValue(10)
        self.device_type_combo.setCurrentIndex(0)  # 默认窗口设备
        self.device_path_edit.setText("")
        self.device_args_edit.setText("")  # 重置命令行参数
        self.screenshot_mode_combo.setCurrentText("自动选择")  # 默认自动选择截图模式
        self.click_mode_combo.setCurrentText("前台点击")  # 默认前台点击模式
        self.retry_count_spin.setValue(0)

        # 发送侧边栏宽度变更信号
        signal_bus.emit_sidebar_width_changed(60)

        signal_bus.emit_log("设置已重置为默认值")

    def browse_device_path(self):
        """
        浏览设备路径
        """
        # 获取当前设备类型
        device_type_index = self.device_type_combo.currentIndex()
        device_type = "windows" if device_type_index == 0 else "adb"

        # 设置文件过滤器
        if device_type == "windows":
            # Windows设备允许选择EXE文件
            file_filter = "可执行文件 (*.exe);;所有文件 (*.*)"
        else:
            # ADB设备允许选择所有文件
            file_filter = "所有文件 (*.*)"

        # 打开文件选择对话框
        file_path, _ = QFileDialog.getOpenFileName(self, "选择设备路径", "", file_filter)
        if file_path:
            self.device_path_edit.setText(file_path)

    def test_device_connection(self):
        """
        测试设备连接 - 仅查找窗口句柄，不实例化设备
        """
        import os
        import re

        from PyQt6.QtWidgets import QMessageBox

        try:
            # 获取当前设备类型和路径
            device_type_index = self.device_type_combo.currentIndex()
            device_type = "windows" if device_type_index == 0 else "adb"
            device_path = self.device_path_edit.text().strip()

            if not device_path:
                QMessageBox.warning(self, "警告", "设备路径不能为空！")
                return

            if device_type == "windows":
                # 对于Windows设备，使用进程名查找窗口
                process_name = os.path.basename(device_path)

                # 导入必要的模块
                import win32gui
                import win32process

                try:
                    import psutil

                    # 1. 改进：查找所有匹配的进程，支持多进程应用（如VS Code）
                    matched_processes = []
                    for proc in psutil.process_iter(["name", "pid", "ppid"]):
                        if proc.info["name"] and proc.info["name"].lower() == process_name.lower():
                            matched_processes.append(proc)

                    if not matched_processes:
                        QMessageBox.warning(self, "警告", f"未找到进程：{process_name}")
                        return

                    # 2. 改进：查找所有匹配进程的窗口
                    all_windows = []

                    def match_all_pids_callback(hwnd, ctx):
                        _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                        # 检查窗口是否可见
                        if win32gui.IsWindowVisible(hwnd):
                            # 收集所有可见窗口，无论PID
                            ctx.append((window_pid, hwnd))

                    # 收集所有可见窗口
                    ctx = []
                    win32gui.EnumWindows(match_all_pids_callback, ctx)

                    # 3. 筛选出与目标进程相关的窗口
                    related_windows = []
                    process_pids = {proc.info["pid"] for proc in matched_processes}

                    for window_pid, hwnd in ctx:
                        if window_pid in process_pids:
                            window_title = win32gui.GetWindowText(hwnd)
                            window_class = win32gui.GetClassName(hwnd)
                            related_windows.append((window_pid, hwnd, window_title, window_class))

                    if related_windows:
                        # 显示所有找到的窗口
                        window_info = []
                        for i, (window_pid, hwnd, window_title, window_class) in enumerate(related_windows, 1):
                            window_info.append(
                                f"窗口 {i}:\n  进程PID: {window_pid}\n  句柄: {hwnd}\n  标题: {window_title}\n  类名: {window_class}"
                            )

                        QMessageBox.information(
                            self,
                            "成功",
                            f"设备连接测试成功！\n进程名: {process_name}\n\n找到 {len(matched_processes)} 个进程和 {len(related_windows)} 个窗口：\n\n"
                            + "\n\n".join(window_info),
                        )
                    else:
                        # 改进：显示更详细的信息，特别是针对多进程应用
                        # 显示所有进程信息
                        proc_info = []
                        for i, proc in enumerate(matched_processes, 1):
                            proc_info.append(f"进程 {i}: PID={proc.info['pid']}, 父PID={proc.info['ppid']}")

                        # 检查是否有任何可见窗口（调试用）
                        total_visible_windows = len(ctx)

                        QMessageBox.warning(
                            self,
                            "警告",
                            f"找到 {len(matched_processes)} 个进程但未找到关联窗口：{process_name}\n\n"
                            + "多进程应用说明：\n"
                            + "有些应用（如VS Code、Chrome、Edge等）会启动多个进程，\n"
                            + "其中只有部分进程有可见窗口，其他进程负责后台工作。\n\n"
                            + f"系统中总共有 {total_visible_windows} 个可见窗口。\n\n"
                            + "可能原因：\n"
                            + "1. 所有匹配进程都是后台辅助进程，没有可见窗口\n"
                            + "2. 窗口在其他虚拟桌面中\n"
                            + "3. 窗口被隐藏或最小化\n"
                            + "4. 权限不足，无法访问窗口\n\n"
                            + "找到的进程：\n"
                            + "\n".join(proc_info),
                        )
                except ImportError:
                    QMessageBox.warning(self, "警告", "psutil未安装，无法通过进程名查找窗口")
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"Windows设备测试失败：\n{str(e)}")
            else:
                # 对于ADB设备，简单检查路径是否存在
                if os.path.exists(device_path):
                    QMessageBox.information(self, "成功", f"ADB设备路径存在：{device_path}")
                else:
                    QMessageBox.warning(self, "警告", f"ADB设备路径不存在：{device_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"设备连接测试发生异常：\n{str(e)}")
