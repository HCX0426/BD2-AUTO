from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)




class MainInterface(QWidget):
    """
    主界面组件，包含任务列表、参数配置和日志显示
    """

    def __init__(self, config_manager, task_mapping, parent=None):
        """
        初始化主界面

        Args:
            config_manager: 配置管理器实例
            task_mapping: 任务映射字典
            parent: 父窗口
        """
        super().__init__(parent)
        self.config_manager = config_manager
        self.task_mapping = task_mapping

        # 当前选择的任务ID
        self.current_task_id = None

        # 参数控件映射
        self.param_widgets = {}

        # 初始化UI
        self.init_ui()

        # 连接信号
        self.connect_signals()

    def init_ui(self):
        """
        初始化主界面UI
        """
        layout = QVBoxLayout(self)
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
        self.task_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.populate_task_list()

        # 全选/取消全选按钮
        select_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setStyleSheet("padding: 8px;")
        self.deselect_all_btn = QPushButton("取消全选")
        self.deselect_all_btn.setStyleSheet("padding: 8px;")

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
        self.save_param_btn.setStyleSheet("padding: 8px;")

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
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # 控制按钮
        control_layout = QHBoxLayout()

        self.start_task_btn = QPushButton("开始任务")
        self.start_task_btn.setStyleSheet("padding: 8px;")
        self.stop_task_btn = QPushButton("停止任务")
        self.stop_task_btn.setStyleSheet("padding: 8px;")
        self.clear_log_btn = QPushButton("清空日志")
        self.clear_log_btn.setStyleSheet("padding: 8px;")
        self.launch_game_btn = QPushButton("启动游戏")
        self.launch_game_btn.setStyleSheet("padding: 8px;")

        # 禁用某些按钮
        self.stop_task_btn.setEnabled(False)

        control_layout.addWidget(self.start_task_btn)
        control_layout.addWidget(self.stop_task_btn)
        control_layout.addStretch(1)
        control_layout.addWidget(self.clear_log_btn)
        control_layout.addWidget(self.launch_game_btn)

        layout.addLayout(control_layout)

    def connect_signals(self):
        """
        连接组件内部信号和外部信号总线
        """
        # 内部信号连接
        self.task_list.itemClicked.connect(self.on_task_item_clicked)
        self.task_list.itemChanged.connect(self.on_task_state_changed)
        self.task_list.model().rowsMoved.connect(self.on_task_order_changed)
        self.select_all_btn.clicked.connect(self.select_all_tasks)
        self.deselect_all_btn.clicked.connect(self.deselect_all_tasks)
        self.save_param_btn.clicked.connect(self.save_task_parameters)
        self.start_task_btn.clicked.connect(self.on_start_task)
        self.stop_task_btn.clicked.connect(self.on_stop_task)
        self.clear_log_btn.clicked.connect(self.clear_log)
        self.launch_game_btn.clicked.connect(self.on_launch_game)

        # 信号总线连接
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()
        signal_bus.log_updated.connect(self.update_log)
        signal_bus.progress_updated.connect(self.update_progress)

    def populate_task_list(self):
        """
        填充任务列表，从配置管理器加载任务顺序和状态
        """
        # 获取保存的任务顺序和状态
        task_order = self.config_manager.get_task_order() or list(self.task_mapping.keys())
        task_states = self.config_manager.get_task_states() or {task_id: False for task_id in self.task_mapping}

        # 确保任务顺序包含所有任务ID
        all_task_ids = set(self.task_mapping.keys())
        ordered_tasks = [tid for tid in task_order if tid in all_task_ids]
        ordered_tasks += [tid for tid in all_task_ids - set(ordered_tasks)]

        self.task_list.clear()
        for task_id in ordered_tasks:
            task_info = self.task_mapping.get(task_id)
            if task_info:
                item = QListWidgetItem(task_info["name"])
                # 设置任务项标志
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsDragEnabled
                )
                # 设置检查状态
                checked_state = Qt.CheckState.Checked if task_states.get(task_id, False) else Qt.CheckState.Unchecked
                item.setCheckState(checked_state)
                item.setData(Qt.ItemDataRole.UserRole, task_id)
                self.task_list.addItem(item)

    def on_task_item_clicked(self, item):
        """
        任务项点击事件

        Args:
            item: 被点击的任务项
        """
        task_id = item.data(Qt.ItemDataRole.UserRole)
        self.current_task_id = task_id
        self.load_task_parameters(task_id)

    def on_task_state_changed(self, item):
        """
        任务项状态变化事件

        Args:
            item: 状态变化的任务项
        """
        task_id = item.data(Qt.ItemDataRole.UserRole)
        is_checked = item.checkState() == Qt.CheckState.Checked

        # 获取当前所有任务状态
        task_states = self.config_manager.get_task_states().copy()

        # 更新特定任务的状态
        task_states[task_id] = is_checked

        # 获取当前任务顺序
        task_order = self.config_manager.get_task_order()

        # 保存任务顺序和状态
        self.config_manager.save_task_order_and_states(task_order, task_states)

    def on_task_order_changed(self, source_parent, source_start, source_end, destination_parent, destination_row):
        """
        任务顺序变化事件
        """
        # 获取新的任务顺序
        new_order = []
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            task_id = item.data(Qt.ItemDataRole.UserRole)
            new_order.append(task_id)

        # 获取当前所有任务状态
        task_states = self.config_manager.get_task_states().copy()

        # 保存新的任务顺序和当前任务状态
        self.config_manager.save_task_order_and_states(new_order, task_states)

    def select_all_tasks(self):
        """
        全选所有任务
        """
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            item.setCheckState(Qt.CheckState.Checked)

        # 保存全选状态到配置管理器
        task_order = self.config_manager.get_task_order()
        task_states = {}
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            task_id = item.data(Qt.ItemDataRole.UserRole)
            task_states[task_id] = True
        self.config_manager.save_task_order_and_states(task_order, task_states)

    def deselect_all_tasks(self):
        """
        取消全选所有任务
        """
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)

        # 保存取消全选状态到配置管理器
        task_order = self.config_manager.get_task_order()
        task_states = {}
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            task_id = item.data(Qt.ItemDataRole.UserRole)
            task_states[task_id] = False
        self.config_manager.save_task_order_and_states(task_order, task_states)

    def load_task_parameters(self, task_id):
        """
        加载任务参数

        Args:
            task_id: 任务ID
        """
        # 清除之前的参数控件
        for i in reversed(range(self.param_form.rowCount())):
            self.param_form.removeRow(i)
        self.param_widgets.clear()

        # 获取任务信息
        task_info = self.task_mapping.get(task_id)
        if not task_info:
            self.param_desc.setText("任务不存在")
            self.save_param_btn.setEnabled(False)
            return

        # 更新参数描述
        self.param_desc.setText(f"任务: {task_info['name']}\n{task_info.get('description', '')}")

        # 获取任务参数配置
        param_config = task_info.get("parameters", [])
        saved_params = self.config_manager.get_task_config(task_id) or {}

        # 创建参数控件
        for param_info in param_config:
            # 从列表项中获取参数名
            param_name = param_info.get("name", "")
            if not param_name:
                continue

            param_type = param_info.get("type", "string")
            label = QLabel(f"{param_info.get('name', param_name)}:")
            label.setToolTip(param_info.get("description", ""))

            widget = None
            default_value = param_info.get("default", "")
            saved_value = saved_params.get(param_name, default_value)

            # 根据参数类型创建不同的控件
            if param_type == "boolean" or param_type == "bool":
                widget = QCheckBox()
                widget.setChecked(saved_value)
            elif param_type == "integer" or param_type == "int":
                widget = QSpinBox()
                widget.setRange(param_info.get("min", 0), param_info.get("max", 1000))
                widget.setValue(saved_value)
            elif param_type == "float":
                widget = QDoubleSpinBox()
                widget.setRange(param_info.get("min", 0.0), param_info.get("max", 1000.0))
                widget.setDecimals(param_info.get("decimals", 2))
                widget.setValue(saved_value)
            elif param_type == "string" or param_type == "str":
                widget = QLineEdit(str(saved_value))
            elif param_type == "radio":
                # 创建单选按钮组
                widget = QWidget()
                radio_layout = QVBoxLayout(widget)
                radio_layout.setContentsMargins(0, 0, 0, 0)
                radio_group = QButtonGroup()

                for option in param_info.get("options", []):
                    radio_btn = QRadioButton(option["name"])
                    radio_btn.setChecked(saved_value == option["value"])
                    radio_group.addButton(radio_btn, option["value"])
                    radio_layout.addWidget(radio_btn)

                self.param_widgets["_radio_group_" + param_name] = radio_group
            elif param_type == "slider":
                widget = QSlider(Qt.Orientation.Horizontal)
                widget.setRange(param_info.get("min", 0), param_info.get("max", 100))
                widget.setValue(saved_value)

            if widget:
                self.param_form.addRow(label, widget)
                self.param_widgets[param_name] = widget

        self.save_param_btn.setEnabled(True)

    def save_task_parameters(self):
        """
        保存任务参数
        """
        if not self.current_task_id:
            return

        params = {}
        for param_name, widget in self.param_widgets.items():
            if param_name.startswith("_radio_group_"):
                # 处理单选按钮组
                actual_param_name = param_name[14:]  # 移除"_radio_group_"前缀
                radio_group = widget
                params[actual_param_name] = radio_group.checkedId()
            else:
                # 处理其他控件类型
                if isinstance(widget, QCheckBox):
                    params[param_name] = widget.isChecked()
                elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                    params[param_name] = widget.value()
                elif isinstance(widget, QLineEdit):
                    params[param_name] = widget.text()
                elif isinstance(widget, QSlider):
                    params[param_name] = widget.value()

        # 保存参数
        self.config_manager.save_task_config(self.current_task_id, params)
        # 使用正确的信号总线实例
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()
        signal_bus.emit_log(f"已保存任务 '{self.task_mapping[self.current_task_id]['name']}' 的参数")

    def get_selected_tasks(self):
        """
        获取选中的任务列表

        Returns:
            list: 选中的任务ID列表
        """
        selected_tasks = []
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                task_id = item.data(Qt.ItemDataRole.UserRole)
                selected_tasks.append(task_id)
        return selected_tasks

    def update_log(self, message):
        """
        更新日志显示并保存到文件

        Args:
            message: 日志消息
        """
        import datetime
        import os

        from src.core.path_manager import path_manager

        # 添加时分秒时间戳，移除方括号
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"{timestamp} {message}"
        self.log_display.append(formatted_message)
        self.log_display.moveCursor(self.log_display.textCursor().MoveOperation.End)

        # 保存到日志文件
        try:
            # 使用path_manager获取gui_log路径
            log_dir = path_manager.get("gui_log")
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            log_file_path = os.path.join(log_dir, f"{today}.log")

            # 确保目录存在
            os.makedirs(log_dir, exist_ok=True)

            # 写入日志（使用完整时间戳）
            full_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(f"[{full_timestamp}] {message}\n")
        except Exception as e:
            # 记录日志保存失败的信息，但不影响程序运行
            from src.auto_control.utils.logger import Logger
            logger = Logger(name="MainInterface")
            logger.error(f"保存GUI日志失败: {str(e)}")

    def update_progress(self, value):
        """
        更新进度条

        Args:
            value: 进度值（0-100）
        """
        self.progress_bar.setValue(value)

    def clear_log(self):
        """
        清空日志
        """
        self.log_display.clear()

    def on_start_task(self):
        """
        开始任务按钮点击事件
        """
        # 获取信号总线实例
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        # 发送开始任务信号
        selected_tasks = self.get_selected_tasks()
        if not selected_tasks:
            signal_bus.emit_log("请先选择要执行的任务")
            return

        self.start_task_btn.setEnabled(False)
        self.stop_task_btn.setEnabled(True)

        # 发送任务开始信号（由主窗口处理）
        signal_bus.emit_task_status_updated("main", True)

    def on_stop_task(self):
        """
        停止任务按钮点击事件
        """
        # 获取信号总线实例
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        self.stop_task_btn.setEnabled(False)
        signal_bus.emit_log("正在停止任务...")

        # 发送任务停止信号（由主窗口处理）
        signal_bus.emit_task_status_updated("main", False)

    def on_launch_game(self):
        """
        启动游戏按钮点击事件
        """
        # 获取信号总线实例
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        signal_bus.emit_log("启动游戏")
        # 发送启动游戏信号（由主窗口处理）
        signal_bus.emit_device_status_updated("launch_game", True)

    def enable_task_controls(self, start_enabled=True, stop_enabled=False, start_text=None):
        """
        启用/禁用任务控制按钮

        Args:
            start_enabled: 是否启用开始按钮
            stop_enabled: 是否启用停止按钮
            start_text: 开始按钮的文本，默认为"开始任务"
        """
        self.start_task_btn.setEnabled(start_enabled)
        self.start_task_btn.setText(start_text or "开始任务")
        self.stop_task_btn.setEnabled(stop_enabled)
