import json
import os
import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QPushButton, QGroupBox, QFormLayout, QLineEdit,
    QCheckBox, QLabel, QMessageBox, QListWidgetItem
)

from auto_control.auto import Auto

# 任务配置文件路径
CONFIG_FILE = 'task_config.json'


class TaskManager:
    def __init__(self):
        self.tasks = {
            'daily_missions': {'name': '每日任务', 'function': 'daily_missions', 'params': {'timeout': 60}},
            'get_guild': {'name': '公会领取', 'function': 'get_guild', 'params': {'timeout': 60}},
            'get_pvp': {'name': 'PVP奖励', 'function': 'get_pvp', 'params': {'timeout': 600}},
            'pass_activity': {'name': '活动扫荡', 'function': 'pass_activity', 'params': {'timeout': 600}},
            'sweep_daily': {'name': '每日扫荡', 'function': 'sweep_daily', 'params': {
                'timeout': 600, 'onigiri': '第九关', 'torch': '火之洞穴'
            }},
            'login': {'name': '登录', 'function': 'login', 'params': {'timeout': 300}},
            'get_email': {'name': '邮件领取', 'function': 'get_email', 'params': {'timeout': 600}},
            'get_restaurant': {'name': '餐厅领取', 'function': 'get_restaurant', 'params': {'timeout': 600}},
            'intensive_decomposition': {'name': '装备分解', 'function': 'intensive_decomposition', 'params': {'timeout': 600}},
            'lucky_draw': {'name': '幸运抽奖', 'function': 'lucky_draw', 'params': {'timeout': 600}},
            'map_collection': {'name': '地图收集', 'function': 'map_collection', 'params': {'timeout': 600}},
            'pass_rewards': {'name': '通行证奖励', 'function': 'pass_rewards', 'params': {'timeout': 600}}
        }
        self.load_config()

    def load_config(self):
        """从配置文件加载任务参数"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    saved_config = json.load(f)
                    for task_id, config in saved_config.items():
                        if task_id in self.tasks:
                            self.tasks[task_id]['params'].update(config)
            except Exception as e:
                print(f"加载配置文件失败: {e}")

    def save_config(self):
        """保存任务参数到配置文件"""
        try:
            config_to_save = {}
            for task_id, task_info in self.tasks.items():
                config_to_save[task_id] = task_info['params']

            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"保存配置文件失败: {e}")
            return False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.task_manager = TaskManager()
        self.current_task = None
        self.task_running = False
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('任务管理器')
        self.setGeometry(100, 100, 800, 600)

        # 创建主布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 左侧任务列表
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        self.task_list = QListWidget()
        self.task_list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection)
        self.task_list.itemClicked.connect(self.on_task_selected)

        # 加载任务到列表
        for task_id, task_info in self.task_manager.tasks.items():
            item = QListWidgetItem(task_info['name'])
            item.setData(Qt.ItemDataRole.UserRole, task_id)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.task_list.addItem(item)

        left_layout.addWidget(QLabel('任务列表:'))
        left_layout.addWidget(self.task_list)

        # 右侧参数配置
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.config_group = QGroupBox('任务参数配置')
        self.config_layout = QFormLayout()
        self.config_group.setLayout(self.config_layout)

        self.save_btn = QPushButton('保存配置')
        self.save_btn.clicked.connect(self.save_current_config)
        self.save_btn.setEnabled(False)

        self.right_layout.addWidget(self.config_group)
        self.right_layout.addWidget(self.save_btn)
        self.right_layout.addStretch()

        # 底部控制按钮
        self.control_btn = QPushButton('开始任务')
        self.control_btn.clicked.connect(self.toggle_task)

        # 添加到主布局
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(self.right_panel, 2)
        main_layout.addWidget(
            self.control_btn, alignment=Qt.AlignmentFlag.AlignBottom)

    def on_task_selected(self, item):
        """选择任务时显示其参数配置"""
        # 清空现有配置项
        while self.config_layout.rowCount() > 0:
            self.config_layout.removeRow(0)

        task_id = item.data(Qt.ItemDataRole.UserRole)
        task_info = self.task_manager.tasks.get(task_id)
        if not task_info:
            return

        # 创建参数输入框
        self.param_inputs = {}
        for param_name, param_value in task_info['params'].items():
            input_widget = QLineEdit(str(param_value))
            self.param_inputs[param_name] = input_widget
            self.config_layout.addRow(f'{param_name}:', input_widget)

        self.save_btn.setEnabled(True)
        self.current_task = task_id

    def save_current_config(self):
        """保存当前选中任务的配置"""
        if not self.current_task or not self.param_inputs:
            return

        # 更新参数值
        for param_name, input_widget in self.param_inputs.items():
            value = input_widget.text()
            # 尝试转换为数值类型
            try:
                if '.' in value:
                    value = float(value)
                else:
                    value = int(value)
            except ValueError:
                pass  # 保持字符串类型

            self.task_manager.tasks[self.current_task]['params'][param_name] = value

        # 保存到文件
        if self.task_manager.save_config():
            QMessageBox.information(self, '成功', '配置已保存')
        else:
            QMessageBox.critical(self, '失败', '配置保存失败')

    def toggle_task(self):
        """开始/停止任务"""
        if self.task_running:
            self.stop_task()
        else:
            self.start_task()

    def start_task(self):
        """开始执行选中的任务"""
        # 获取选中的任务
        selected_tasks = []
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected_tasks.append(item.data(Qt.ItemDataRole.UserRole))

        if not selected_tasks:
            QMessageBox.warning(self, '警告', '请至少选择一个任务')
            return

        self.task_running = True
        self.control_btn.setText('停止任务')
        self.task_list.setEnabled(False)
        self.save_btn.setEnabled(False)

        # 逐个执行任务
        try:
            # 导入run.py中的任务函数
            from run import (daily_missions, get_email, get_guild, get_pvp,
                             get_restaurant, intensive_decomposition, login,
                             lucky_draw, map_collection, pass_activity,
                             pass_rewards, sweep_daily)

            auto_instance = Auto()  # 假设Auto类可以直接实例化
            auto_instance.add_device()
            auto_instance.start()

            # 添加线程管理以确保任务完成
            import threading
            task_threads = []

            for task_id in selected_tasks:
                if not self.task_running:  # 检查是否已停止
                    break

                task_info = self.task_manager.tasks.get(task_id)
                if not task_info:
                    continue

                # 获取任务函数
                task_func = globals().get(task_info['function'])
                if not task_func:
                    continue

                # 执行任务 - 使用线程并收集
                params = task_info['params'].copy()
                thread = threading.Thread(target=task_func, args=(auto_instance,), kwargs=params)
                thread.start()
                task_threads.append(thread)

            # 等待所有任务线程完成
            for thread in task_threads:
                thread.join()
        except Exception as e:
            QMessageBox.critical(self, '错误', f'任务执行失败: {str(e)}')
        finally:
            if 'auto_instance' in locals():
                auto_instance.stop()
            self.stop_task()

    def stop_task(self):
        """停止当前任务"""
        self.task_running = False
        self.control_btn.setText('开始任务')
        self.task_list.setEnabled(True)
        if self.current_task:
            self.save_btn.setEnabled(True)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
