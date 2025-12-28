import time

from PyQt6.QtCore import QEvent, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QFont, QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.auto_control.core.auto import Auto


class LogSignal(QWidget):
    log_updated = pyqtSignal(str)

    def __init__(self):
        super().__init__()


class TaskWorker(QThread):
    """任务工作线程，实现优雅退出机制"""

    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, auto_instance, task_ids, config_manager, task_mapping):
        super().__init__()
        self.auto_instance = auto_instance
        self.task_ids = task_ids
        self.config_manager = config_manager
        self.task_mapping = task_mapping
        self.is_running = False
        self.should_stop = False

    def run(self):
        """执行任务主逻辑，包含可中断点"""
        self.is_running = True
        # 不重置 should_stop 标志，保留之前可能设置的停止信号
        total_tasks = len(self.task_ids)

        try:
            for i, task_id in enumerate(self.task_ids):
                # 检查是否需要停止（使用正确的check_should_stop方法）
                if self.should_stop or self.auto_instance.check_should_stop():
                    self.log_signal.emit(f"任务执行已被中断，已完成 {i}/{total_tasks} 个任务")
                    break

                task_info = self.task_mapping.get(task_id)
                if not task_info:
                    self.log_signal.emit(f"警告：任务 {task_id} 不存在，已跳过")
                    continue

                # 更新进度
                progress = int((i / total_tasks) * 100)
                self.progress_signal.emit(progress)
                self.log_signal.emit(f"开始执行任务：{task_info['name']}")

                # 获取任务参数
                task_params = self.config_manager.get_task_config(task_id) or {}

                # 执行任务（移除多余的stop_checker参数）
                task_func = task_info.get("function")
                if task_func:
                    try:
                        # 只传递函数定义中声明的参数（auto和task_params）
                        task_func(self.auto_instance, **task_params)
                        self.log_signal.emit(f"任务 {task_info['name']} 执行完成")
                    except Exception as e:
                        self.log_signal.emit(f"任务 {task_info['name']} 执行出错: {str(e)}")
                        if self.check_stop():  # 如果是因为停止指令导致的错误，直接退出
                            break
                else:
                    self.log_signal.emit(f"警告：任务 {task_info['name']} 没有执行函数，已跳过")

                # 再次检查是否需要停止
                if self.check_stop():
                    self.log_signal.emit(f"任务执行已被中断，已完成 {i+1}/{total_tasks} 个任务")
                    break

            # 全部完成或中途停止，更新进度为100%
            self.progress_signal.emit(100)

        except Exception as e:
            self.log_signal.emit(f"任务线程发生未捕获异常: {str(e)}")
        finally:
            self.is_running = False
            self.finished.emit()

    def check_stop(self):
        """检查是否需要停止任务"""
        return self.should_stop or self.auto_instance.check_should_stop()

    def stop(self):
        """请求任务停止"""
        self.should_stop = True
        # 移除阻塞的 wait 调用，改为非阻塞方式
        self.log_signal.emit("已发送任务停止请求")


class MainWindow(QMainWindow):
    # 构造函数接收外部传递的实例
    def __init__(self, auto_instance, settings_manager, config_manager, task_mapping, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.settings_manager = settings_manager
        self.task_mapping = task_mapping
        self.auto_instance: Auto = auto_instance  # 核心控制实例

        # UI状态变量
        self.task_thread = None
        self.task_worker = None
        self.task_running = False
        self.current_task_id = None
        self.param_widgets = {}
        self.sidebar_hidden = False
        self.sidebar_dragging = False
        self.sidebar_hovered = False
        self.stop_timer = None
        self.stop_attempts = 0  # 记录停止尝试次数
        self.max_stop_attempts = 20  # 最大停止尝试次数(约10秒)

        # 初始化UI
        self.init_ui()
        self.load_settings()

        # 日志信号
        self.log_signal = LogSignal()
        self.log_signal.log_updated.connect(self.update_log)

    def init_ui(self):
        """初始化主窗口UI"""
        self.setWindowTitle("自动任务控制系统")
        self.resize(*self.settings_manager.get_setting("window_size", [1280, 720]))
        self.setMinimumSize(1024, 600)

        # 主窗口布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 侧边栏
        self.init_sidebar()
        main_layout.addWidget(self.sidebar)

        # 主内容区域
        self.stacked_widget = QStackedWidget()
        self.init_main_interface()
        self.init_settings_interface()
        main_layout.addWidget(self.stacked_widget, 1)

        # 根据设置初始化侧边栏状态
        sidebar_visible = self.settings_manager.get_setting("sidebar_visible", True)
        if not sidebar_visible:
            self.collapse_sidebar()
        else:
            self.sidebar_hidden = False

    def init_sidebar(self):
        """初始化侧边栏"""
        self.sidebar = QFrame()
        self.sidebar.setFrameShape(QFrame.Shape.StyledPanel)
        self.sidebar.setMinimumWidth(50)
        self.sidebar.setMaximumWidth(300)
        self.sidebar.setFixedWidth(self.settings_manager.get_setting("sidebar_width", 200))

        # 启用鼠标跟踪
        self.sidebar.setMouseTracking(True)
        self.sidebar.installEventFilter(self)

        # 侧边栏布局 - 使用垂直布局
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(5, 5, 5, 5)
        sidebar_layout.setSpacing(5)

        # 1. 主界面按钮 (放在顶部)
        self.main_btn = QPushButton()
        self.main_btn.setCheckable(True)
        self.main_btn.setChecked(True)
        self.main_btn.setIcon(QIcon.fromTheme("go-home"))
        self.main_btn.setToolTip("主界面")
        self.main_btn.setStyleSheet("padding: 8px;")

        # 2. 添加弹性空间 (将设置按钮推到最下面)
        sidebar_layout.addWidget(self.main_btn)
        sidebar_layout.addStretch(1)

        # 3. 设置按钮 (放在最底部)
        self.settings_btn = QPushButton()
        self.settings_btn.setCheckable(True)

        # 使用齿轮符号作为备选
        if QIcon.hasThemeIcon("preferences-system"):
            self.settings_btn.setIcon(QIcon.fromTheme("preferences-system"))
        else:
            self.settings_btn.setText("⚙")

        self.settings_btn.setToolTip("设置")
        self.settings_btn.setStyleSheet("padding: 8px;")

        # 按钮组
        self.button_group = QButtonGroup()
        self.button_group.addButton(self.main_btn, 0)
        self.button_group.addButton(self.settings_btn, 1)
        self.button_group.buttonClicked.connect(self.on_sidebar_button_clicked)

        sidebar_layout.addWidget(self.settings_btn)

    def eventFilter(self, obj, event):
        """处理侧边栏的事件"""
        if obj == self.sidebar:
            if event.type() == QEvent.Type.Enter:
                self.sidebar_hovered = True
                if self.sidebar.width() <= 50:
                    self.expand_sidebar()
                return True
            elif event.type() == QEvent.Type.Leave:
                self.sidebar_hovered = False
                if not self.sidebar_dragging and self.stacked_widget.currentIndex() == 0:
                    self.collapse_sidebar()
                return True
            elif event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.sidebar_dragging = True
                return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.sidebar_dragging = False
                    if not self.sidebar_hovered and self.stacked_widget.currentIndex() == 0:
                        self.collapse_sidebar()
                return True
            elif event.type() == QEvent.Type.MouseMove and self.sidebar_dragging:
                # 处理拖动调整宽度
                pos = event.pos()
                new_width = pos.x()
                if new_width >= 50 and new_width <= 300:
                    self.sidebar.setFixedWidth(new_width)
                    self.settings_manager.set_setting("sidebar_width", new_width)
                return True
        return super().eventFilter(obj, event)

    def expand_sidebar(self):
        """展开侧边栏"""
        width = self.settings_manager.get_setting("sidebar_width", 200)
        self.sidebar.setFixedWidth(width)
        self.main_btn.setText("主界面")
        self.settings_btn.setText("设置")
        self.sidebar_hidden = False

    def collapse_sidebar(self):
        """收缩侧边栏"""
        if self.sidebar.width() > 50:
            self.settings_manager.set_setting("sidebar_width", self.sidebar.width())
        self.sidebar.setFixedWidth(50)
        self.main_btn.setText("")
        self.settings_btn.setText("")
        self.sidebar_hidden = True

    def on_sidebar_button_clicked(self, button):
        """侧边栏按钮点击事件"""
        if button == self.main_btn:
            self.stacked_widget.setCurrentIndex(0)
            if not self.sidebar_hovered:
                self.collapse_sidebar()
        elif button == self.settings_btn:
            self.stacked_widget.setCurrentIndex(1)
            self.expand_sidebar()

    def init_main_interface(self):
        """初始化主界面"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # 顶部信息栏
        top_info = QLabel("任务控制系统 - 就绪状态")
        top_info.setStyleSheet(
            """
            background-color: #f0f0f0; 
            padding: 4px 8px; 
            font-weight: bold;
            border: 1px solid #ddd;
        """
        )
        top_info.setMaximumHeight(28)
        layout.addWidget(top_info)

        # 主内容区域 (任务列表、参数配置、日志)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧 - 任务列表
        task_group = QGroupBox("可选任务 (勾选要执行的任务，可拖动排序)")
        task_layout = QVBoxLayout()

        self.task_list = QListWidget()
        self.task_list.setAlternatingRowColors(True)
        self.task_list.itemClicked.connect(self.on_task_item_clicked)
        self.task_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.task_list.itemChanged.connect(self.on_task_state_changed)
        self.populate_task_list()

        # 全选/取消全选按钮
        select_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("全选")
        self.deselect_all_btn = QPushButton("取消全选")
        self.select_all_btn.clicked.connect(self.select_all_tasks)
        self.deselect_all_btn.clicked.connect(self.deselect_all_tasks)

        select_layout.addWidget(self.select_all_btn)
        select_layout.addWidget(self.deselect_all_btn)

        task_layout.addLayout(select_layout)
        task_layout.addWidget(self.task_list)
        task_group.setLayout(task_layout)

        # 中间 - 参数配置
        self.param_group = QGroupBox("任务参数配置")
        self.param_layout = QVBoxLayout()

        self.param_form = QFormLayout()
        self.param_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.param_form.setSpacing(10)

        self.param_desc = QLabel("请选择一个任务查看参数配置")
        self.param_desc.setWordWrap(True)
        self.param_desc.setStyleSheet("color: #666; font-style: italic; padding: 5px 0;")

        self.save_param_btn = QPushButton("保存参数")
        self.save_param_btn.clicked.connect(self.save_task_parameters)
        self.save_param_btn.setEnabled(False)

        self.param_layout.addWidget(self.param_desc)
        self.param_layout.addLayout(self.param_form)
        self.param_layout.addSpacing(10)
        self.param_layout.addWidget(self.save_param_btn)
        self.param_layout.addStretch(1)
        self.param_group.setLayout(self.param_layout)

        # 右侧 - 日志区域
        log_group = QGroupBox("执行日志")
        log_layout = QVBoxLayout()

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("SimHei", 9))
        log_layout.addWidget(self.log_display)
        log_group.setLayout(log_layout)

        # 添加三栏到分割器
        splitter.addWidget(task_group)
        splitter.addWidget(self.param_group)
        splitter.addWidget(log_group)
        splitter.setSizes([417, 417, 417])

        layout.addWidget(splitter, 1)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(25)
        layout.addWidget(self.progress_bar)

        # 底部控制按钮
        control_layout = QHBoxLayout()
        control_layout.setSpacing(10)

        self.start_stop_btn = QPushButton("开始任务")
        self.clear_log_btn = QPushButton("清空日志")
        self.launch_game_btn = QPushButton("启动游戏")

        # 设置按钮大小
        for btn in [self.start_stop_btn, self.clear_log_btn, self.launch_game_btn]:
            btn.setMinimumHeight(30)
            btn.setMinimumWidth(90)

        # 连接信号
        self.start_stop_btn.clicked.connect(self.toggle_task)
        self.clear_log_btn.clicked.connect(self.clear_log)
        self.launch_game_btn.clicked.connect(self.launch_game)

        control_layout.addWidget(self.start_stop_btn)
        control_layout.addWidget(self.clear_log_btn)
        control_layout.addWidget(self.launch_game_btn)
        layout.addLayout(control_layout)

        # 添加到堆叠窗口
        self.stacked_widget.addWidget(widget)

    def launch_game(self):
        """启动游戏"""
        pc_game_path = self.settings_manager.get_setting("pc_game_path", "")
        if not pc_game_path:
            QMessageBox.warning(self, "警告", "请先在设置中配置PC游戏路径")
            return

        try:
            import os
            import subprocess

            # 检查路径是否存在
            if not os.path.exists(pc_game_path):
                QMessageBox.critical(self, "错误", f"游戏路径不存在: {pc_game_path}")
                return

            # 启动游戏
            subprocess.Popen(pc_game_path)
            self.log(f"已启动游戏: {pc_game_path}")

        except Exception as e:
            self.log(f"启动游戏失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"启动游戏失败: {str(e)}")

    def init_settings_interface(self):
        """初始化设置界面 实时生效"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 设置标题
        title = QLabel("应用设置")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        # 主题设置
        theme_group = QGroupBox("主题设置")
        theme_layout = QVBoxLayout()

        self.theme_light = QRadioButton("浅色主题")
        self.theme_dark = QRadioButton("深色主题")

        theme = self.settings_manager.get_setting("theme", "light")
        if theme == "dark":
            self.theme_dark.setChecked(True)
        else:
            self.theme_light.setChecked(True)

        # 连接信号，实时生效
        self.theme_light.toggled.connect(self.on_theme_changed)
        self.theme_dark.toggled.connect(self.on_theme_changed)

        theme_layout.addWidget(self.theme_light)
        theme_layout.addWidget(self.theme_dark)
        theme_group.setLayout(theme_layout)

        # 侧边栏设置
        sidebar_group = QGroupBox("侧边栏设置")
        sidebar_layout = QFormLayout()

        self.sidebar_width_slider = QSlider(Qt.Orientation.Horizontal)
        self.sidebar_width_slider.setMinimum(100)
        self.sidebar_width_slider.setMaximum(300)
        self.sidebar_width_slider.setValue(self.settings_manager.get_setting("sidebar_width", 200))
        self.sidebar_width_slider.valueChanged.connect(self.on_sidebar_width_changed)

        sidebar_layout.addRow("侧边栏宽度:", self.sidebar_width_slider)
        sidebar_group.setLayout(sidebar_layout)

        # 游戏启动配置
        game_group = QGroupBox("游戏启动配置")
        game_layout = QFormLayout()

        # PC游戏路径设置
        self.pc_game_path_edit = QLineEdit()
        self.pc_game_path_edit.setText(self.settings_manager.get_setting("pc_game_path", ""))
        self.pc_game_path_edit.textChanged.connect(
            lambda: self.settings_manager.set_setting("pc_game_path", self.pc_game_path_edit.text())
        )

        pc_game_path_btn = QPushButton("浏览...")
        pc_game_path_btn.clicked.connect(self.browse_pc_game_path)

        pc_path_layout = QHBoxLayout()
        pc_path_layout.addWidget(self.pc_game_path_edit)
        pc_path_layout.addWidget(pc_game_path_btn)
        game_layout.addRow("PC游戏路径:", pc_path_layout)

        # 模拟器路径设置
        self.emulator_path_edit = QLineEdit()
        self.emulator_path_edit.setText(self.settings_manager.get_setting("emulator_path", ""))
        self.emulator_path_edit.textChanged.connect(
            lambda: self.settings_manager.set_setting("emulator_path", self.emulator_path_edit.text())
        )

        emulator_path_btn = QPushButton("浏览...")
        emulator_path_btn.clicked.connect(self.browse_emulator_path)

        emulator_path_layout = QHBoxLayout()
        emulator_path_layout.addWidget(self.emulator_path_edit)
        emulator_path_layout.addWidget(emulator_path_btn)
        game_layout.addRow("模拟器路径:", emulator_path_layout)

        game_group.setLayout(game_layout)

        # 添加到主布局
        layout.addWidget(theme_group)
        layout.addWidget(sidebar_group)
        layout.addWidget(game_group)
        layout.addStretch(1)

        # 添加到堆叠窗口
        self.stacked_widget.addWidget(widget)

    def browse_pc_game_path(self):
        """浏览选择PC游戏路径"""
        path, _ = QFileDialog.getOpenFileName(self, "选择PC游戏可执行文件", "", "可执行文件 (*.exe);;所有文件 (*)")
        if path:
            self.pc_game_path_edit.setText(path)

    def browse_emulator_path(self):
        """浏览选择模拟器路径"""
        path, _ = QFileDialog.getOpenFileName(self, "选择模拟器可执行文件", "", "可执行文件 (*.exe);;所有文件 (*)")
        if path:
            self.emulator_path_edit.setText(path)

    def on_theme_changed(self):
        """主题变更实时处理"""
        theme = "dark" if self.theme_dark.isChecked() else "light"
        self.settings_manager.set_setting("theme", theme)
        self.apply_theme(theme)

    def on_sidebar_width_changed(self, width):
        """侧边栏宽度变更实时处理"""
        if not self.sidebar_hidden:
            self.sidebar.setFixedWidth(width)
        self.settings_manager.set_setting("sidebar_width", width)

    def update_sidebar_width(self, width):
        """更新侧边栏宽度"""
        if not self.sidebar_hidden:
            self.sidebar.setFixedWidth(width)
        self.settings_manager.set_setting("sidebar_width", width)

    def on_task_item_clicked(self, item):
        """处理任务项点击事件"""
        task_id = item.data(Qt.ItemDataRole.UserRole)
        self.current_task_id = task_id
        self.load_task_parameters(task_id)

    def on_task_state_changed(self, item):
        """当任务勾选状态变化时，自动保存状态"""
        task_ids, task_states = self.get_current_task_order_and_states()
        self.config_manager.save_task_order_and_states(task_ids, task_states)

    def populate_task_list(self):
        """填充任务列表"""
        task_order = self.config_manager.get_task_order() or list(self.task_mapping.keys())
        task_states = self.config_manager.get_task_states() or {task_id: False for task_id in self.task_mapping}

        all_task_ids = set(self.task_mapping.keys())
        ordered_tasks = [tid for tid in task_order if tid in all_task_ids]
        ordered_tasks += [tid for tid in all_task_ids - set(ordered_tasks)]

        self.task_list.clear()
        for task_id in ordered_tasks:
            task_info = self.task_mapping.get(task_id)
            if task_info:
                item = QListWidgetItem(task_info["name"])
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsDragEnabled
                )
                checked_state = Qt.CheckState.Checked if task_states.get(task_id, False) else Qt.CheckState.Unchecked
                item.setCheckState(checked_state)
                item.setData(Qt.ItemDataRole.UserRole, task_id)
                self.task_list.addItem(item)

    def load_task_parameters(self, task_id):
        """加载任务参数到表单"""
        self.clear_param_form()
        task_info = self.task_mapping.get(task_id)
        if not task_info or not task_info.get("parameters"):
            self.param_desc.setText("该任务没有可配置的参数")
            self.save_param_btn.setEnabled(False)
            return

        self.param_desc.setText(f"任务描述: {task_info.get('description', '无描述')}")
        saved_params = self.config_manager.get_task_config(task_id)
        self.param_widgets = {}

        for param in task_info["parameters"]:
            param_name = param["name"]
            param_type = param["type"]
            param_default = param["default"]

            label = QLabel(f"{param_name}:")
            label.setToolTip(param["annotation"])

            if param_type == "int":
                widget = QSpinBox()
                widget.setMinimum(-1000000)
                widget.setMaximum(1000000)
                widget.setValue(saved_params.get(param_name, param_default) if param_default is not None else 0)
            elif param_type == "float":
                widget = QDoubleSpinBox()
                widget.setMinimum(-1000000.0)
                widget.setMaximum(1000000.0)
                widget.setDecimals(2)
                widget.setValue(saved_params.get(param_name, param_default) if param_default is not None else 0.0)
            elif param_type == "bool":
                widget = QCheckBox()
                widget.setChecked(saved_params.get(param_name, param_default) if param_default is not None else False)
            else:
                widget = QLineEdit()
                widget.setText(str(saved_params.get(param_name, param_default)) if param_default is not None else "")

            widget.setEnabled(not self.task_running)
            self.param_form.addRow(label, widget)
            self.param_widgets[param_name] = widget

        self.save_param_btn.setEnabled(True)

    def clear_param_form(self):
        """清空参数表单"""
        while self.param_form.rowCount() > 0:
            self.param_form.removeRow(0)
        self.param_widgets = {}

    def save_task_parameters(self):
        """保存任务参数配置"""
        if not self.current_task_id or not self.param_widgets:
            return

        task_info = self.task_mapping.get(self.current_task_id)
        if not task_info:
            return

        params = {}
        for param in task_info["parameters"]:
            param_name = param["name"]
            widget = self.param_widgets.get(param_name)

            if widget is None:
                continue

            if isinstance(widget, QSpinBox):
                params[param_name] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                params[param_name] = widget.value()
            elif isinstance(widget, QCheckBox):
                params[param_name] = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                params[param_name] = widget.text()

        if self.config_manager.save_task_config(self.current_task_id, params):
            self.log(f"任务 '{task_info['name']}' 的参数已保存")
        else:
            self.log(f"任务 '{task_info['name']}' 的参数保存失败")

    def get_current_task_order_and_states(self):
        """获取当前任务顺序和勾选状态"""
        task_ids = []
        task_states = {}

        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            task_id = item.data(Qt.ItemDataRole.UserRole)
            task_ids.append(task_id)
            task_states[task_id] = item.checkState() == Qt.CheckState.Checked

        return task_ids, task_states

    def select_all_tasks(self):
        """全选任务"""
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            item.setCheckState(Qt.CheckState.Checked)

    def deselect_all_tasks(self):
        """取消全选任务"""
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)

    def toggle_task(self):
        """切换开始/停止任务状态"""
        if self.task_running:
            self.stop_task()
        else:
            self.start_task()

    def start_task(self):
        """开始执行选中的任务，添加前置状态校验"""
        # 前置校验：确保任务未在运行、线程已释放
        if self.task_running:
            self.log("无法启动任务：已有任务正在运行")
            QMessageBox.information(self, "提示", '已有任务正在运行，请等待其终止或点击"停止任务"')
            return

        if self.task_worker and self.task_worker.isRunning():
            self.log("检测到未释放的任务线程，正在强制清理...")
            self.reset_task_state(force=True)
            QMessageBox.information(self, "提示", "检测到未释放的任务资源，已自动清理，请重试")
            return

        try:
            selected_tasks = []
            for i in range(self.task_list.count()):
                item = self.task_list.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    selected_tasks.append(item.data(Qt.ItemDataRole.UserRole))

            if not selected_tasks:
                QMessageBox.warning(self, "警告", "请至少选择一个任务")
                return

            # 启动任务前，强制重置所有停止标志
            self.auto_instance.set_should_stop(False)  # 重置Auto实例的停止标志
            if self.task_worker:
                self.task_worker.should_stop = False  # 重置worker的停止标志
                self.auto_instance.device_manager.remove_device(self.auto_instance.default_device_uri)

            self.set_task_running_state(True)
            self.log(f"开始执行任务，共 {len(selected_tasks)} 个任务")

            if not self.auto_instance.add_device():
                raise Exception(f"设备添加失败: {getattr(self.auto_instance, 'last_error', '未知错误')}")

            self.auto_instance.start()
            self.log("设备连接成功，准备执行任务")

            # 创建并启动任务线程
            self.task_worker = TaskWorker(self.auto_instance, selected_tasks, self.config_manager, self.task_mapping)

            # 连接信号槽
            self.task_worker.log_signal.connect(self.log)
            self.task_worker.progress_signal.connect(self.update_progress)
            self.task_worker.finished.connect(self.on_task_finished)

            # 启动线程
            self.task_worker.start()

        except Exception as e:
            self.log(f"启动任务时发生错误: {str(e)}")
            self.reset_task_state(force=True)
            QMessageBox.critical(self, "错误", f"启动任务时发生错误: {str(e)}")

    def stop_task(self):
        """停止当前任务，优化终止流程"""
        if not self.task_running:
            return

        # 使用QTimer确保在主线程中执行UI操作
        QTimer.singleShot(0, lambda: self.log("收到停止指令，正在终止任务..."))
        QTimer.singleShot(0, lambda: self.start_stop_btn.setEnabled(False))

        self.stop_attempts = 0  # 重置尝试次数

        # 通知任务停止
        if self.auto_instance:
            self.auto_instance.set_should_stop(True)

        # 通知worker停止
        if self.task_worker and self.task_worker.isRunning():
            self.task_worker.stop()

        # 启动定时器，轮询检查任务是否已终止
        if self.stop_timer and self.stop_timer.isActive():
            self.stop_timer.stop()

        # 创建新的定时器，确保在主线程中执行
        def start_check_timer():
            self.stop_timer = QTimer()
            self.stop_timer.setInterval(500)  # 每500ms检查一次
            self.stop_timer.timeout.connect(self.check_task_stopped)
            self.stop_timer.start()

        QTimer.singleShot(0, start_check_timer)

    def check_task_stopped(self):
        """轮询检查任务是否已停止，避免重复清理"""
        self.stop_attempts += 1

        # 检查条件：worker已停止
        worker_stopped = not (self.task_worker and self.task_worker.isRunning())

        if worker_stopped:
            self.stop_timer.stop()
            # 只有在任务仍在运行状态时才进行清理，避免重复
            if self.task_running:
                self.reset_task_state()
                # 使用QTimer确保在主线程中执行UI操作
                QTimer.singleShot(0, lambda: self.log("任务已完全终止"))
            QTimer.singleShot(0, lambda: self.start_stop_btn.setEnabled(True))
        else:
            # 显示剩余等待时间，让用户了解进度
            remaining_seconds = (self.max_stop_attempts - self.stop_attempts) * 0.5
            QTimer.singleShot(0, lambda: self.log(f"等待任务终止中... (剩余约 {remaining_seconds:.1f} 秒)"))

            # 达到最大尝试次数，强制终止
            if self.stop_attempts >= self.max_stop_attempts:
                QTimer.singleShot(0, lambda: self.log(f"超过最大等待次数 ({self.max_stop_attempts}次)，将强制终止任务"))
                self.stop_timer.stop()

                # 显示确认对话框必须在主线程中执行
                def show_confirm_dialog():
                    reply = QMessageBox.warning(
                        self,
                        "任务终止超时",
                        "任务无法正常终止，是否强制结束？这可能导致数据不一致。",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )

                    if reply == QMessageBox.StandardButton.Yes:
                        self.reset_task_state(force=True)
                        QTimer.singleShot(0, lambda: self.log("已强制终止任务"))
                    else:
                        QTimer.singleShot(0, lambda: self.log("用户取消强制终止，任务可能仍在运行"))
                        self.set_task_running_state(False)  # 至少更新UI状态

                    self.start_stop_btn.setEnabled(True)

                QTimer.singleShot(0, show_confirm_dialog)

    @pyqtSlot()
    def on_task_finished(self):
        """任务完成后的处理，避免与定时器重复清理"""
        # 只有在任务仍在运行状态时才进行清理
        if self.task_running:
            # 使用QTimer.singleShot确保在主线程中执行reset_task_state
            QTimer.singleShot(0, lambda: self.reset_task_state())
            QTimer.singleShot(0, lambda: self.log("所有任务执行完毕"))

    def reset_task_state(self, force=False):
        """重置任务状态和UI，增加状态检查避免重复清理"""
        # 如果已经不在运行状态，直接返回避免重复清理
        if not self.task_running and not force:
            return

        # 确保在主线程中更新UI
        if not self.thread().isRunning() or self.thread() != QThread.currentThread():
            # 如果不在主线程，使用QTimer.singleShot在主线程中执行
            QTimer.singleShot(0, lambda: self.reset_task_state(force))
            return

        # 首先更新状态标志
        QTimer.singleShot(0, lambda: self.set_task_running_state(False))
        QTimer.singleShot(0, lambda: self.progress_bar.setValue(0))

        # 清理worker并断开信号连接
        if self.task_worker:
            try:
                # 断开所有信号连接
                try:
                    self.task_worker.log_signal.disconnect(self.log)
                    self.task_worker.progress_signal.disconnect(self.update_progress)
                    self.task_worker.finished.disconnect(self.on_task_finished)
                except:
                    pass  # 忽略已经断开的连接

                # 如果仍在运行，尝试停止
                if self.task_worker.isRunning():
                    QTimer.singleShot(0, lambda: self.log("任务worker仍在运行，尝试停止..."))
                    self.task_worker.stop()
                    if force and self.task_worker.isRunning():
                        QTimer.singleShot(0, lambda: self.log("强制终止worker线程"))
                        self.task_worker.terminate()

                        # 避免使用阻塞的 wait 调用，改为异步等待
                        def check_terminated():
                            if not self.task_worker.isRunning():
                                QTimer.singleShot(0, lambda: self.log("worker线程已强制终止"))
                            else:
                                QTimer.singleShot(0, lambda: self.log("警告：worker线程未能在预期时间内终止"))

                        QTimer.singleShot(1000, check_terminated)
            except Exception as e:
                self.log(f"清理worker时出错: {str(e)}")
            finally:
                self.task_worker = None

        # 清理auto实例（只在force模式下或正常模式下第一次清理）
        if self.auto_instance:
            try:
                # 只有在force模式下才真正停止auto实例
                # 正常模式下保持auto实例运行以便后续使用
                if force:
                    self.auto_instance.stop()
                    self.auto_instance.set_should_stop(False)
            except Exception as e:
                # 忽略已经关闭的错误
                if "shutdown" not in str(e).lower():
                    self.log(f"清理auto实例时出错: {str(e)}")

        QTimer.singleShot(0, lambda: self.start_stop_btn.setEnabled(True))
        QTimer.singleShot(0, lambda: self.log("任务状态已重置"))

    def set_task_running_state(self, running):
        """设置任务运行状态"""
        self.task_running = running
        self.start_stop_btn.setText("停止任务" if running else "开始任务")
        self.task_list.setEnabled(not running)
        self.select_all_btn.setEnabled(not running)
        self.deselect_all_btn.setEnabled(not running)
        self.save_param_btn.setEnabled(not running and self.current_task_id is not None)
        self.launch_game_btn.setEnabled(not running)

        for widget in self.param_widgets.values():
            widget.setEnabled(not running)

    def apply_theme(self, theme):
        """应用主题"""
        if theme == "dark":
            dark_style = """
                QWidget {
                    background-color: #333;
                    color: #EEE;
                }
                QGroupBox {
                    border: 1px solid #555;
                    border-radius: 5px;
                    margin-top: 10px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px;
                }
                QPushButton {
                    background-color: #555;
                    border: 1px solid #666;
                    padding: 5px;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #666;
                }
                QPushButton:pressed {
                    background-color: #777;
                }
                QListWidget {
                    background-color: #444;
                    border: 1px solid #555;
                }
                QTextEdit {
                    background-color: #444;
                    border: 1px solid #555;
                }
            """
            self.setStyleSheet(dark_style)
        else:
            self.setStyleSheet("")

    def load_settings(self):
        """加载设置并应用"""
        theme = self.settings_manager.get_setting("theme", "light")
        self.apply_theme(theme)

    def log(self, message):
        """添加日志信息"""
        self.log_display.append(message)
        self.log_display.moveCursor(QTextCursor.MoveOperation.End)

    def update_log(self, message):
        """通过信号槽更新日志"""
        self.log(message)

    def clear_log(self):
        """清空日志显示"""
        self.log_display.clear()

    def update_progress(self, value):
        """更新进度条"""
        self.progress_bar.setValue(value)

    def closeEvent(self, event):
        """窗口关闭事件，确保任务完全终止后再关闭，优化避免主线程阻塞"""
        # 保存窗口大小
        self.settings_manager.set_setting("window_size", [self.width(), self.height()])

        # 停止正在运行的任务
        if self.task_running:
            self.log("检测到正在运行的任务，尝试终止后再关闭窗口...")
            self.stop_task()

            # 不阻塞主线程，改为使用定时器检查任务是否已终止
            self.close_event = event
            self.close_timer = QTimer()
            self.close_timer.setInterval(200)  # 每200ms检查一次
            self.close_timer.timeout.connect(self.check_task_stopped_before_close)
            self.close_timer.start()
            self.close_wait_time = 0
            event.ignore()  # 先忽略关闭事件，等待任务终止
            return

        # 任务未运行，直接关闭
        self.perform_close()

    def check_task_stopped_before_close(self):
        """检查任务是否已停止，用于窗口关闭前的异步等待"""
        self.close_wait_time += 1

        if not self.task_running:
            # 任务已终止，执行关闭
            self.close_timer.stop()
            self.perform_close()
        elif self.close_wait_time > 25:  # 5秒超时 (25 * 200ms)
            # 超时，询问用户是否强制关闭
            self.close_timer.stop()

            # 确保在主线程中显示对话框
            def show_close_confirm():
                reply = QMessageBox.warning(
                    self,
                    "任务仍在运行",
                    "任务仍在运行中，强制关闭可能导致问题，是否继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )

                if reply == QMessageBox.StandardButton.Yes:
                    # 强制清理并关闭
                    self.reset_task_state(force=True)
                    self.perform_close()

            QTimer.singleShot(0, show_close_confirm)

    def perform_close(self):
        """执行实际的关闭操作"""
        # 确保在主线程中执行关闭操作
        if self.thread() != QThread.currentThread():
            QTimer.singleShot(0, self.perform_close)
            return

        # 确保auto_instance被正确清理
        if self.auto_instance:
            try:
                # 异步清理auto_instance，避免阻塞
                self.auto_instance.set_should_stop(True)

                # 使用QTimer避免可能的阻塞操作
                def cleanup_auto_instance():
                    try:
                        self.auto_instance.stop()
                        self.auto_instance = None
                    except Exception as e:
                        self.log(f"关闭auto_instance时出错: {str(e)}")
                        self.auto_instance = None

                QTimer.singleShot(0, cleanup_auto_instance)
            except Exception as e:
                self.log(f"准备关闭auto_instance时出错: {str(e)}")
                self.auto_instance = None

        # 保存其他设置
        try:
            self.settings_manager.save_settings()
        except Exception as e:
            self.log(f"保存设置时出错: {str(e)}")

        # 直接接受关闭事件，避免递归调用
        if hasattr(self, "close_event") and self.close_event:
            self.close_event.accept()
        else:
            # 如果没有保存的close_event，调用父类的close方法
            super().close()

        # 确保应用程序完全退出
        QApplication.quit()
