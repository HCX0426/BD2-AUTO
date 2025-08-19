import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSplitter, QGroupBox, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QProgressBar, QMessageBox, QFormLayout,
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QFrame,
    QStackedWidget, QSizePolicy, QButtonGroup, QRadioButton, QSlider
)
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QThread
from PyQt6.QtGui import QFont, QTextCursor, QIcon
from auto_control.auto import Auto
from task_manager import AppSettingsManager, TaskConfigManager, load_task_modules

class LogSignal(QWidget):
    log_updated = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 初始化管理器
        self.config_manager = TaskConfigManager()
        self.settings_manager = AppSettingsManager()
        self.task_mapping = load_task_modules()
        
        # UI状态变量
        self.auto_instance = Auto()
        self.task_thread = None
        self.task_running = False
        self.current_task_id = None
        self.param_widgets = {}
        self.sidebar_hidden = False
        self.sidebar_dragging = False
        self.sidebar_hovered = False
        
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
        sidebar_layout.addStretch(1)  # 这是关键，把下面的内容推到最底

        # 3. 设置按钮 (放在最底部)
        self.settings_btn = QPushButton()
        self.settings_btn.setCheckable(True)
        
        # 确保使用齿轮图标（如果系统主题没有，使用内置图标）
        if QIcon.hasThemeIcon("preferences-system"):
            self.settings_btn.setIcon(QIcon.fromTheme("preferences-system"))  # 系统齿轮图标
        else:
            # 如果没有系统图标，可以使用内置资源或自定义图标
            self.settings_btn.setIcon(QIcon(":/icons/settings.png"))  # 需要提供资源文件
            # 或者使用文本替代
            # self.settings_btn.setText("⚙")  # 齿轮符号
        
        self.settings_btn.setToolTip("设置")
        self.settings_btn.setStyleSheet("padding: 8px;")

        # 按钮组
        self.button_group = QButtonGroup()
        self.button_group.addButton(self.main_btn, 0)
        self.button_group.addButton(self.settings_btn, 1)
        self.button_group.buttonClicked.connect(self.on_sidebar_button_clicked)

        # 添加到布局 (设置按钮已经在最下面)
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
        if self.sidebar.width() > 50:  # 只有当前是展开状态时才保存宽度
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
        top_info.setStyleSheet("""
            background-color: #f0f0f0; 
            padding: 4px 8px; 
            font-weight: bold;
            border: 1px solid #ddd;
        """)
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
            import subprocess
            import os
            
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

        # 新增游戏启动配置
        game_group = QGroupBox("游戏启动配置")
        game_layout = QFormLayout()
        
        # PC游戏路径设置
        self.pc_game_path_edit = QLineEdit()
        self.pc_game_path_edit.setText(self.settings_manager.get_setting("pc_game_path", ""))
        self.pc_game_path_edit.textChanged.connect(lambda: self.settings_manager.set_setting("pc_game_path", self.pc_game_path_edit.text()))
        
        pc_game_path_btn = QPushButton("浏览...")
        pc_game_path_btn.clicked.connect(self.browse_pc_game_path)
        
        pc_path_layout = QHBoxLayout()
        pc_path_layout.addWidget(self.pc_game_path_edit)
        pc_path_layout.addWidget(pc_game_path_btn)
        game_layout.addRow("PC游戏路径:", pc_path_layout)
        
        # 模拟器路径设置
        self.emulator_path_edit = QLineEdit()
        self.emulator_path_edit.setText(self.settings_manager.get_setting("emulator_path", ""))
        self.emulator_path_edit.textChanged.connect(lambda: self.settings_manager.set_setting("emulator_path", self.emulator_path_edit.text()))
        
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
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择PC游戏可执行文件",
            "",
            "可执行文件 (*.exe);;所有文件 (*)"
        )
        if path:
            self.pc_game_path_edit.setText(path)

    def browse_emulator_path(self):
        """浏览选择模拟器路径"""
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择模拟器可执行文件",
            "",
            "可执行文件 (*.exe);;所有文件 (*)"
        )
        if path:
            self.emulator_path_edit.setText(path)

    def on_theme_changed(self):
        """主题变更实时处理"""
        theme = "dark" if self.theme_dark.isChecked() else "light"
        self.settings_manager.set_setting("theme", theme)
        self.apply_theme(theme)

    def on_sidebar_width_changed(self, width):
        """侧边栏宽度变更实时处理"""
        if not self.sidebar_hidden:  # 只有在侧边栏展开时才更新宽度
            self.sidebar.setFixedWidth(width)
        self.settings_manager.set_setting("sidebar_width", width)

    def update_sidebar_width(self, width):
        """更新侧边栏宽度"""
        if not self.sidebar_hidden:  # 只有在侧边栏展开时才更新宽度
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
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDragEnabled)
                checked_state = Qt.CheckState.Checked if task_states.get(task_id, False) else Qt.CheckState.Unchecked
                item.setCheckState(checked_state)
                item.setData(Qt.ItemDataRole.UserRole, task_id)
                self.task_list.addItem(item)

    def load_task_parameters(self, task_id):
        """加载任务参数到表单"""
        self.clear_param_form()
        task_info = self.task_mapping.get(task_id)
        if not task_info or not task_info.get('parameters'):
            self.param_desc.setText("该任务没有可配置的参数")
            self.save_param_btn.setEnabled(False)
            return
        
        self.param_desc.setText(f"任务描述: {task_info.get('description', '无描述')}")
        saved_params = self.config_manager.get_task_config(task_id)
        self.param_widgets = {}
        
        for param in task_info['parameters']:
            param_name = param['name']
            param_type = param['type']
            param_default = param['default']
            
            label = QLabel(f"{param_name}:")
            label.setToolTip(param['annotation'])
            
            if param_type == 'int':
                widget = QSpinBox()
                widget.setMinimum(-1000000)
                widget.setMaximum(1000000)
                widget.setValue(saved_params.get(param_name, param_default) if param_default is not None else 0)
            elif param_type == 'float':
                widget = QDoubleSpinBox()
                widget.setMinimum(-1000000.0)
                widget.setMaximum(1000000.0)
                widget.setDecimals(2)
                widget.setValue(saved_params.get(param_name, param_default) if param_default is not None else 0.0)
            elif param_type == 'bool':
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
        for param in task_info['parameters']:
            param_name = param['name']
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
        """开始执行选中的任务"""
        try:
            selected_tasks = []
            for i in range(self.task_list.count()):
                item = self.task_list.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    selected_tasks.append(item.data(Qt.ItemDataRole.UserRole))
            
            if not selected_tasks:
                QMessageBox.warning(self, "警告", "请至少选择一个任务")
                return
            
            self.set_task_running_state(True)
            self.log(f"开始执行任务，共 {len(selected_tasks)} 个任务")
            
            if not self.auto_instance.add_device():
                raise Exception(f"设备添加失败: {self.auto_instance.last_error}")
            
            self.auto_instance.start()
            self.log("设备连接成功，准备执行任务")
            
            # 创建并启动任务线程
            from task_manager import TaskWorker
            self.task_thread = QThread()
            self.task_worker = TaskWorker(
                self.auto_instance, 
                selected_tasks, 
                self.config_manager,
                self.task_mapping
            )
            self.task_worker.moveToThread(self.task_thread)
            self.task_worker.log_signal.connect(self.log)
            self.task_worker.progress_signal.connect(self.update_progress)
            self.task_worker.finished.connect(self.on_task_finished)
            self.task_thread.started.connect(self.task_worker.run)
            self.task_thread.start()
            
        except Exception as e:
            self.log(f"启动任务时发生错误: {str(e)}")
            self.reset_task_state()
            QMessageBox.critical(self, "错误", f"启动任务时发生错误: {str(e)}")

    def stop_task(self):
        """停止当前任务"""
        if not self.task_running:
            return
            
        self.log("收到停止指令，正在终止任务...")
        self.start_stop_btn.setEnabled(False)
        if self.auto_instance:
            self.auto_instance.set_should_stop(True)

    def on_task_finished(self):
        """任务完成后的处理"""
        self.reset_task_state()
        self.log("所有任务执行完毕")

    def reset_task_state(self):
        """重置任务状态和UI"""
        self.set_task_running_state(False)
        self.progress_bar.setValue(0)
        
        if self.auto_instance:
            self.auto_instance.stop()
        
        if self.task_thread and self.task_thread.isRunning():
            self.task_thread.quit()
            self.task_thread.wait()
        
        self.start_stop_btn.setEnabled(True)

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
        """窗口关闭事件"""
        # 保存窗口大小
        self.settings_manager.set_setting("window_size", [self.width(), self.height()])
        
        # 停止正在运行的任务
        if self.task_running:
            self.stop_task()
        
        # 确保auto_instance被正确清理
        if self.auto_instance:
            self.auto_instance.stop()
            self.auto_instance = None
        
        # 保存其他设置
        self.settings_manager.save_settings()
        
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())