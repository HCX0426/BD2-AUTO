# task_list.py
from PyQt6.QtWidgets import (QWidget, QListWidgetItem, QMessageBox, QPushButton)
from PyQt6.QtCore import pyqtSignal, Qt
from ui.utils.widget_builder import WidgetBuilder
from ui.controllers.resource_manager import ResourceManager
import os

class TaskListView(QWidget):
    task_selected = pyqtSignal(str)
    task_started = pyqtSignal(str)
    all_tasks_started = pyqtSignal(list)

    def __init__(self, resource_manager: ResourceManager):
        super().__init__()
        self.resource_manager = resource_manager
        self.task_list = WidgetBuilder.create_list_widget()
        self.current_tasks = {}
        self.init_ui()
        self.bind_events()

    def init_ui(self):
        """初始化UI"""
        main_layout = WidgetBuilder.create_vbox_layout()
        main_layout.addWidget(WidgetBuilder.create_label("任务列表", bold=True))
        main_layout.addWidget(self.task_list, stretch=1)

        btn_layout = WidgetBuilder.create_hbox_layout()
        self.exec_selected_btn = WidgetBuilder.create_button("执行选中任务", "执行当前选中的单个任务")
        self.exec_all_btn = WidgetBuilder.create_button("执行所有任务", "执行当前资源下的所有任务")
        self.exec_selected_btn.setEnabled(False)
        self.exec_all_btn.setEnabled(False)

        btn_layout.addWidget(self.exec_selected_btn)
        btn_layout.addWidget(self.exec_all_btn)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)

    def bind_events(self):
        """绑定交互事件"""
        self.task_list.itemClicked.connect(self.on_task_item_clicked)
        self.exec_selected_btn.clicked.connect(self.on_exec_selected_click)
        self.exec_all_btn.clicked.connect(self.on_exec_all_click)

    def on_task_item_clicked(self, item: QListWidgetItem):
        """任务项点击：获取任务ID并发射选中信号"""
        task_id = item.text()
        self.task_selected.emit(task_id)
        self.exec_selected_btn.setEnabled(True)

    def on_exec_selected_click(self):
        """执行选中任务"""
        selected_item = self.task_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "警告", "请先选中一个任务")
            return
        task_id = selected_item.text()
        self.task_started.emit(task_id)

    def on_exec_all_click(self):
        """执行所有任务"""
        all_task_ids = list(self.current_tasks.keys())
        if not all_task_ids:
            QMessageBox.warning(self, "警告", "当前资源下无可用任务")
            return
        self.all_tasks_started.emit(all_task_ids)

    def update_task_list(self, task_mapping: dict):
        """更新任务列表（修复：使用标准任务结构）"""
        self.task_list.clear()
        self.current_tasks = task_mapping.copy()  # 使用任务加载器返回的映射
        self.exec_selected_btn.setEnabled(False)
        
        if not task_mapping:
            self.task_list.addItem("未找到任务")
            self.exec_all_btn.setEnabled(False)
            return

        for task_id, task_info in task_mapping.items():
            task_name = task_info.get('name', task_id)
            item = QListWidgetItem(task_name)
            item.setData(Qt.ItemDataRole.UserRole, task_id)
            self.task_list.addItem(item)

        self.exec_all_btn.setEnabled(True)