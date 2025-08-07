import sys
import os
import json
import inspect
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QSplitter, QGroupBox, QListWidget, QListWidgetItem, 
                            QPushButton, QTextEdit, QProgressBar, QMessageBox, QFormLayout,
                            QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMetaObject, pyqtSlot
from PyQt6.QtGui import QFont, QTextCursor

# 假设其他必要的导入保持不变
from auto_control.auto import Auto
from auto_control.config.st_config import generate_report
from auto_control.logger import Logger
from auto_control.config.log_config import LOG_CONFIG

# 任务模块路径
TASKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auto_tasks', 'pc')
# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'task_configs.json')

# 动态导入任务模块并构建任务映射
def load_task_modules():
    task_mapping = {}
    # 遍历任务目录
    for filename in os.listdir(TASKS_DIR):
        if filename.endswith('.py') and not filename.startswith('__'):
            module_name = filename[:-3]
            try:
                # 动态导入模块
                module = __import__(f'auto_tasks.pc.{module_name}', fromlist=[module_name])
                # 查找主任务函数（假设每个模块有一个与模块名相同的函数）
                if hasattr(module, module_name):
                    task_func = getattr(module, module_name)
                    # 获取函数文档字符串作为描述
                    doc = inspect.getdoc(task_func) or ""
                    # 获取函数参数
                    sig = inspect.signature(task_func)
                    params = []
                    for param_name, param in sig.parameters.items():
                        if param_name != 'auto':  # 排除auto参数
                            # 获取参数默认值
                            default = param.default if param.default != inspect.Parameter.empty else None
                            # 获取参数注释
                            annotation = param.annotation if param.annotation != inspect.Parameter.empty else ""
                            params.append({
                                'name': param_name,
                                'default': default,
                                'annotation': str(annotation),
                                'type': type(default).__name__ if default is not None else 'str'
                            })
                    task_mapping[module_name] = {
                        'name': module_name.replace('_', ' ').title(),
                        'function': task_func,
                        'description': doc,
                        'parameters': params
                    }
            except Exception as e:
                print(f"加载任务模块 {module_name} 失败: {str(e)}")
    return task_mapping

# 加载任务映射
TASK_MAPPING = load_task_modules()

# 日志信号类
class LogSignal(QWidget):
    log_updated = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()

# 任务配置管理类
class TaskConfigManager:
    def __init__(self, config_file=CONFIG_FILE):
        self.config_file = config_file
        self.configs = self.load_configs()
        
    def load_configs(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    
                    # 兼容旧配置文件格式
                    if "task_order" in config_data and "task_states" in config_data:
                        return config_data
                    else:
                        # 旧配置文件格式，转换为新格式
                        return {
                            "task_order": list(TASK_MAPPING.keys()),
                            "task_states": {task_id: False for task_id in TASK_MAPPING},
                            "task_configs": config_data
                        }
        except Exception as e:
            print(f"加载配置文件失败: {str(e)}")
        # 默认配置
        return {
            "task_order": list(TASK_MAPPING.keys()),
            "task_states": {task_id: False for task_id in TASK_MAPPING},
            "task_configs": {}
        }
    
    def save_configs(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.configs, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"保存配置文件失败: {str(e)}")
            return False
    
    def get_task_config(self, task_id):
        """获取任务配置"""
        return self.configs.get("task_configs", {}).get(task_id, {})
    
    def save_task_config(self, task_id, config):
        """保存任务配置"""
        if "task_configs" not in self.configs:
            self.configs["task_configs"] = {}
        self.configs["task_configs"][task_id] = config
        return self.save_configs()
    
    def save_task_order_and_states(self, task_ids, task_states):
        """保存任务顺序和状态"""
        self.configs["task_order"] = task_ids
        self.configs["task_states"] = task_states
        return self.save_configs()
    
    def get_task_order(self):
        """获取任务顺序"""
        return self.configs.get("task_order", list(TASK_MAPPING.keys()))
    
    def get_task_states(self):
        """获取任务状态（勾选状态）"""
        return self.configs.get("task_states", {task_id: False for task_id in TASK_MAPPING})

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.auto_instance = None  # 全局唯一的Auto实例
        self.task_thread = None    # 任务执行线程
        self.task_running = False  # 任务运行状态
        self.log_signal = LogSignal()  # 日志信号
        self.log_signal.log_updated.connect(self.update_log)  # 连接日志更新信号
        self.config_manager = TaskConfigManager()  # 配置管理器
        self.current_task_id = None  # 当前选中的任务ID
        
        self.init_ui()
        
    def init_ui(self):
        """初始化UI界面"""
        # 设置窗口基本属性 - 调整为1280*720
        self.setWindowTitle("自动任务控制系统")
        self.setGeometry(100, 100, 1280, 720)
        self.setMinimumSize(1024, 600)  # 保持合理的最小尺寸
        
        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # 创建顶部信息栏 - 保持紧凑
        top_info = QLabel("任务控制系统 - 就绪状态")
        top_info.setStyleSheet("""
            background-color: #f0f0f0; 
            padding: 4px 8px; 
            font-weight: bold;
            border: 1px solid #ddd;
        """)
        top_info.setMaximumHeight(28)  # 进一步压缩高度
        main_layout.addWidget(top_info)
        
        # 创建水平分割器 - 主要内容区域
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧任务列表区域
        task_group = QGroupBox("可选任务 (勾选要执行的任务，可拖动排序)")
        task_layout = QVBoxLayout()
        
        self.task_list = QListWidget()
        self.task_list.setAlternatingRowColors(True)
        self.task_list.itemClicked.connect(self.on_task_item_clicked)  # 任务点击事件
        self.task_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)  # 允许内部拖动排序
        self.task_list.itemChanged.connect(self.on_task_state_changed)  # 勾选状态变化
        self.populate_task_list()  # 填充任务列表
        
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
        
        # 中间参数配置区域
        self.param_group = QGroupBox("任务参数配置")
        self.param_layout = QVBoxLayout()
        
        # 参数表单区域
        self.param_form = QFormLayout()
        self.param_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.param_form.setSpacing(10)
        
        # 参数描述
        self.param_desc = QLabel("请选择一个任务查看参数配置")
        self.param_desc.setWordWrap(True)
        self.param_desc.setStyleSheet("color: #666; font-style: italic; padding: 5px 0;")
        
        # 保存按钮
        self.save_param_btn = QPushButton("保存参数")
        self.save_param_btn.clicked.connect(self.save_task_parameters)
        self.save_param_btn.setEnabled(False)
        
        # 添加到参数布局
        self.param_layout.addWidget(self.param_desc)
        self.param_layout.addLayout(self.param_form)
        self.param_layout.addSpacing(10)
        self.param_layout.addWidget(self.save_param_btn)
        self.param_layout.addStretch(1)
        self.param_group.setLayout(self.param_layout)
        
        # 右侧日志区域
        log_group = QGroupBox("执行日志")
        log_layout = QVBoxLayout()
        
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("SimHei", 9))  # 设置中文字体
        log_layout.addWidget(self.log_display)
        log_group.setLayout(log_layout)
        
        # 添加到分割器 - 三栏1:1:1比例
        splitter.addWidget(task_group)
        splitter.addWidget(self.param_group)
        splitter.addWidget(log_group)
        # 计算1:1:1的宽度分配 (1280减去边距约1280-30=1250，每栏约417)
        splitter.setSizes([417, 417, 417])
        
        main_layout.addWidget(splitter, 1)  # 让中间区域占主要空间
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(25)
        main_layout.addWidget(self.progress_bar)
        
        # 底部控制按钮
        control_layout = QHBoxLayout()
        control_layout.setSpacing(10)
        
        self.start_btn = QPushButton("开始任务")
        self.stop_btn = QPushButton("停止任务")
        self.stop_btn.setEnabled(False)  # 初始禁用
        self.clear_log_btn = QPushButton("清空日志")
        
        # 保存顺序按钮
        self.save_order_btn = QPushButton("保存任务顺序")
        self.save_order_btn.clicked.connect(self.save_task_order)
        self.save_order_btn.setMinimumHeight(30)
        self.save_order_btn.setMinimumWidth(120)
        
        # 设置按钮大小
        for btn in [self.start_btn, self.stop_btn, self.clear_log_btn]:
            btn.setMinimumHeight(30)
            btn.setMinimumWidth(90)
        
        # 绑定按钮事件
        self.start_btn.clicked.connect(self.start_task)
        self.stop_btn.clicked.connect(self.stop_task)
        self.clear_log_btn.clicked.connect(self.clear_log)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.clear_log_btn)
        control_layout.addWidget(self.save_order_btn)  # 添加保存顺序按钮
        main_layout.addLayout(control_layout)
    
    def populate_task_list(self):
        """填充任务列表，按照上次保存的顺序和勾选状态"""
        # 获取保存的任务顺序和状态
        task_order = self.config_manager.get_task_order()
        task_states = self.config_manager.get_task_states()
        
        # 确保所有任务都在列表中
        all_task_ids = set(TASK_MAPPING.keys())
        ordered_tasks = [tid for tid in task_order if tid in all_task_ids]
        # 添加不在顺序列表中的新任务
        for task_id in all_task_ids - set(ordered_tasks):
            ordered_tasks.append(task_id)
        
        for task_id in ordered_tasks:
            task_info = TASK_MAPPING.get(task_id)
            if task_info:
                item = QListWidgetItem(task_info["name"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDragEnabled)
                # 设置上次保存的勾选状态
                checked_state = Qt.CheckState.Checked if task_states.get(task_id, False) else Qt.CheckState.Unchecked
                item.setCheckState(checked_state)
                item.setData(Qt.ItemDataRole.UserRole, task_id)  # 存储任务ID
                self.task_list.addItem(item)
    
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
    
    def save_task_order(self):
        """保存任务顺序和勾选状态到配置文件"""
        task_ids, task_states = self.get_current_task_order_and_states()
        if self.config_manager.save_task_order_and_states(task_ids, task_states):
            self.log("任务顺序和状态已保存")
        else:
            self.log("保存任务顺序和状态失败")
    
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
    
    def on_task_item_clicked(self, item):
        """处理任务项点击事件，显示参数配置"""
        task_id = item.data(Qt.ItemDataRole.UserRole)
        self.current_task_id = task_id
        self.load_task_parameters(task_id)
    
    def on_task_state_changed(self, item):
        """当任务勾选状态变化时，保存状态"""
        # 只在有任务ID时保存
        if self.current_task_id:
            self.save_task_order()
    
    def clear_param_form(self):
        """清空参数表单"""
        while self.param_form.rowCount() > 0:
            self.param_form.removeRow(0)
        self.param_widgets = {}  # 存储参数控件
    
    def load_task_parameters(self, task_id):
        """加载任务参数到表单"""
        self.clear_param_form()
        
        task_info = TASK_MAPPING.get(task_id)
        if not task_info or not task_info.get('parameters'):
            self.param_desc.setText("该任务没有可配置的参数")
            self.save_param_btn.setEnabled(False)
            return
        
        # 显示任务描述
        self.param_desc.setText(f"任务描述: {task_info.get('description', '无描述')}")
        
        # 获取保存的参数配置
        saved_params = self.config_manager.get_task_config(task_id)
        
        self.param_widgets = {}
        
        # 添加参数控件
        for param in task_info['parameters']:
            param_name = param['name']
            param_type = param['type']
            param_default = param['default']
            param_annotation = param['annotation']
            
            # 创建对应的输入控件
            label = QLabel(f"{param_name}:")
            label.setToolTip(param_annotation)
            
            # 根据参数类型创建不同的控件
            if param_type == 'int':
                widget = QSpinBox()
                if param_default is not None:
                    widget.setMinimum(-1000000)
                    widget.setMaximum(1000000)
                    widget.setValue(saved_params.get(param_name, param_default))
            elif param_type == 'float':
                widget = QDoubleSpinBox()
                if param_default is not None:
                    widget.setMinimum(-1000000.0)
                    widget.setMaximum(1000000.0)
                    widget.setDecimals(2)
                    widget.setValue(saved_params.get(param_name, param_default))
            elif param_type == 'bool':
                widget = QCheckBox()
                widget.setChecked(saved_params.get(param_name, param_default))
            else:  # 默认为字符串
                widget = QLineEdit()
                if param_default is not None:
                    widget.setText(str(saved_params.get(param_name, param_default)))
            
            # 根据任务运行状态设置是否可编辑
            widget.setEnabled(not self.task_running)
            
            self.param_form.addRow(label, widget)
            self.param_widgets[param_name] = widget
        
        self.save_param_btn.setEnabled(True)
    
    def save_task_parameters(self):
        """保存任务参数配置"""
        if not self.current_task_id or not self.param_widgets:
            return
        
        task_info = TASK_MAPPING.get(self.current_task_id)
        if not task_info:
            return
        
        # 收集参数值
        params = {}
        for param in task_info['parameters']:
            param_name = param['name']
            param_type = param['type']
            widget = self.param_widgets.get(param_name)
            
            if widget is None:
                continue
                
            # 根据控件类型获取值
            if isinstance(widget, QSpinBox):
                params[param_name] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                params[param_name] = widget.value()
            elif isinstance(widget, QCheckBox):
                params[param_name] = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                params[param_name] = widget.text()
        
        # 保存参数
        if self.config_manager.save_task_config(self.current_task_id, params):
            self.log(f"任务 '{task_info['name']}' 的参数已保存")
        else:
            self.log(f"任务 '{task_info['name']}' 的参数保存失败")
    
    def start_task(self):
        """开始执行选中的任务"""
        # 获取选中的任务
        selected_tasks = []
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected_tasks.append(item.data(Qt.ItemDataRole.UserRole))
        
        if not selected_tasks:
            QMessageBox.warning(self, "警告", "请至少选择一个任务")
            return
        
        # 更新UI状态
        self.task_running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.task_list.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self.deselect_all_btn.setEnabled(False)
        self.save_param_btn.setEnabled(False)
        self.save_order_btn.setEnabled(False)  # 禁用保存顺序按钮
        
        # 禁用所有参数控件
        for widget in self.param_widgets.values():
            widget.setEnabled(False)
        
        self.log(f"开始执行任务，共 {len(selected_tasks)} 个任务")
        
        # 创建全局Auto实例
        self.auto_instance = Auto()
        if not self.auto_instance.add_device():
            error_msg = f"设备添加失败: {self.auto_instance.last_error}"
            self.log(error_msg)
            QMessageBox.critical(self, "设备错误", error_msg)
            self.reset_task_state()
            return
        
        self.auto_instance.start()
        self.log("设备连接成功，准备执行任务")
        
        # 启动任务线程
        self.task_thread = QThread()
        self.task_worker = TaskWorker(self.auto_instance, selected_tasks, self.config_manager)
        self.task_worker.moveToThread(self.task_thread)
        self.task_worker.log_signal.connect(self.log)
        self.task_worker.progress_signal.connect(self.update_progress)
        self.task_worker.finished.connect(self.reset_task_state)
        self.task_thread.started.connect(self.task_worker.run)
        self.task_thread.start()
    
    def stop_task(self):
        """停止当前任务"""
        if not self.task_running:
            return
            
        self.log("收到停止指令，正在终止任务...")
        if self.auto_instance:
            self.auto_instance.set_should_stop(True)
        
        # 禁用停止按钮防止重复点击
        self.stop_btn.setEnabled(False)
    
    def reset_task_state(self):
        """重置任务状态和UI"""
        self.task_running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.task_list.setEnabled(True)
        self.select_all_btn.setEnabled(True)
        self.deselect_all_btn.setEnabled(True)
        self.save_order_btn.setEnabled(True)  # 启用保存顺序按钮
        self.progress_bar.setValue(0)
        
        # 启用参数保存按钮和控件
        self.save_param_btn.setEnabled(self.current_task_id is not None)
        for widget in self.param_widgets.values():
            widget.setEnabled(True)
        
        self.log("任务执行已停止")
        
        # 清理线程
        if self.task_thread and self.task_thread.isRunning():
            self.task_thread.quit()
            self.task_thread.wait()
    
    def log(self, message):
        """添加日志信息"""
        self.log_display.append(message)
        # 滚动到最新日志
        self.log_display.moveCursor(QTextCursor.MoveOperation.End)
    
    def update_log(self, message):
        """通过信号槽更新日志（线程安全）"""
        self.log(message)
    
    def update_progress(self, value):
        """更新进度条"""
        self.progress_bar.setValue(value)
    
    def clear_log(self):
        """清空日志显示"""
        self.log_display.clear()

class TaskWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished = pyqtSignal()
    
    def __init__(self, auto_instance, selected_tasks, config_manager):
        super().__init__()
        self.auto_instance = auto_instance
        self.selected_tasks = selected_tasks
        self.config_manager = config_manager
        self.should_stop = False
    
    def run(self):
        try:
            # 登录游戏（如果未包含在选中任务中，则自动执行）
            if "login" not in self.selected_tasks:
                self.log_signal.emit("执行登录流程...")
                from auto_tasks.pc.login import login
                if not login(self.auto_instance):
                    self.log_signal.emit("登录失败，终止任务执行")
                    self.finished.emit()
                    return
            
            total_tasks = len(self.selected_tasks)
            for index, task_id in enumerate(self.selected_tasks):
                # 检查是否需要停止
                if self.auto_instance.check_should_stop():
                    self.log_signal.emit("任务被用户中断")
                    break
                
                # 更新进度
                progress = int((index / total_tasks) * 100)
                self.progress_signal.emit(progress)
                
                # 执行任务
                task_info = TASK_MAPPING.get(task_id)
                if not task_info:
                    self.log_signal.emit(f"未知任务: {task_id}")
                    continue
                
                self.log_signal.emit(f"===== 开始执行: {task_info['name']} =====")
                try:
                    task_func = task_info["function"]
                    # 获取任务参数
                    task_params = self.config_manager.get_task_config(task_id)
                    # 执行任务，传入参数
                    success = task_func(self.auto_instance, **task_params)
                    result = "成功" if success else "失败"
                    self.log_signal.emit(f"{task_info['name']} 执行{result}")
                except Exception as e:
                    self.log_signal.emit(f"{task_info['name']} 执行出错: {str(e)}")
            
            self.log_signal.emit("所有任务执行完毕")
            self.progress_signal.emit(100)
            
        except Exception as e:
            self.log_signal.emit(f"任务执行框架错误: {str(e)}")
        finally:
            # 确保资源释放
            generate_report(__file__)
            if self.auto_instance:
                self.auto_instance.stop()
            self.finished.emit()
            
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())