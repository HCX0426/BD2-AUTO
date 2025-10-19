# launcher.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QProgressBar, 
                             QMessageBox, QApplication)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QPixmap, QFont
from ui.utils.widget_builder import WidgetBuilder
from ui.utils.style_loader import StyleLoader
from ui.controllers.resource_manager import ResourceManager
from ui.controllers.settings_manager import SettingsManager
import os

class InitWorker(QThread):
    """后台初始化线程（避免启动界面卡顿）"""
    progress_updated = pyqtSignal(int, str)  # 进度值(0-100)、当前状态
    init_completed = pyqtSignal(bool, dict)  # 初始化结果、初始化完成的管理器实例
    init_failed = pyqtSignal(str)            # 初始化失败原因

    def __init__(self, project_root):
        super().__init__()
        self.project_root = project_root
        self.resource_manager = None
        self.settings_manager = None

    def run(self):
        try:
            # 步骤1：检查必要目录（20%进度）
            self.progress_updated.emit(20, "检查程序目录...")
            required_dirs = [
                os.path.join(self.project_root, "logs"),
                os.path.join(self.project_root, "cache"),
                os.path.join(self.project_root, "ui", "styles"),
                os.path.join(self.project_root, "ui", "configs")
            ]
            for dir_path in required_dirs:
                if not os.path.exists(dir_path):
                    os.makedirs(dir_path, exist_ok=True)

            # 步骤2：初始化设置管理器（40%进度）
            self.progress_updated.emit(40, "加载系统设置...")
            self.settings_manager = SettingsManager()

            # 步骤3：初始化资源管理器（60%进度）
            self.progress_updated.emit(60, "加载资源配置...")
            self.resource_manager = ResourceManager()

            # 步骤4：验证样式文件（80%进度）
            self.progress_updated.emit(80, "验证样式文件...")
            theme = self.settings_manager.get_setting("appearance.theme", "light")
            common_style = StyleLoader.get_common_style_path()
            theme_style = StyleLoader.get_theme_style_path(theme)
            if not (os.path.exists(common_style) and os.path.exists(theme_style)):
                raise FileNotFoundError(f"样式文件缺失：{common_style} 或 {theme_style}")

            # 步骤5：初始化完成（100%进度）
            self.progress_updated.emit(100, "初始化完成，即将启动主程序...")
            self.init_completed.emit(
                True,
                {
                    "resource_manager": self.resource_manager,
                    "settings_manager": self.settings_manager  # 确保传递设置管理器
                }
            )
        except Exception as e:
            self.init_failed.emit(f"初始化失败：{str(e)}")

class Launcher(QWidget):
    """程序启动界面"""
    launch_finished = pyqtSignal(dict)  # 启动完成，传递管理器实例

    def __init__(self, project_root):
        super().__init__()
        self.project_root = project_root
        self.init_worker = None
        self.init_ui()
        self.start_init()

    def init_ui(self):
        try:
            """构建启动界面UI"""
            self.setWindowTitle("游戏任务自动化工具 - 启动中")
            self.setFixedSize(400, 300)  # 固定启动界面大小
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint)  # 无边框（可选）

            # 主布局
            main_layout = WidgetBuilder.create_vbox_layout(margin=20, spacing=15)
            main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # 标题（可选：可替换为logo）
            title_label = WidgetBuilder.create_label("游戏任务自动化工具", bold=True)
            title_label.setFont(QFont("Microsoft YaHei", 14))
            main_layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)

            # 版本信息（可选）
            version_label = WidgetBuilder.create_label("v1.0.0", alignment=Qt.AlignmentFlag.AlignCenter)
            main_layout.addWidget(version_label)

            # 进度条
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            main_layout.addWidget(self.progress_bar)

            # 状态标签
            self.status_label = WidgetBuilder.create_label("准备初始化...", alignment=Qt.AlignmentFlag.AlignCenter)
            main_layout.addWidget(self.status_label)

            # 加载样式
            StyleLoader.load_common_styles(self, "light")

            self.setLayout(main_layout)
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"界面初始化失败：{str(e)}")
            QApplication.quit()  # 退出程序

    def start_init(self):
        """启动后台初始化线程"""
        self.init_worker = InitWorker(self.project_root)
        self.init_worker.progress_updated.connect(self.update_progress)
        self.init_worker.init_completed.connect(self.on_init_completed)
        self.init_worker.init_failed.connect(self.on_init_failed)
        self.init_worker.start()

    def update_progress(self, value, status):
        """更新进度条和状态"""
        self.progress_bar.setValue(value)
        self.status_label.setText(status)

    def on_init_completed(self, success, managers):
        """初始化完成，关闭启动界面并通知主程序"""
        if success:
            self.launch_finished.emit(managers)
            self.close()

    def on_init_failed(self, error_msg):
        """初始化失败，显示错误并退出"""
        QMessageBox.critical(self, "启动失败", error_msg)
        QApplication.quit()  # 退出程序

    def center(self):
        """窗口居中显示"""
        qr = self.frameGeometry()
        cp = QApplication.primaryScreen().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())