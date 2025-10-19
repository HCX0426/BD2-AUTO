# execution_plan.py
from PyQt6.QtWidgets import (QWidget, QTableWidget, QTableWidgetItem, QProgressBar,
                             QPushButton, QTextEdit, QMessageBox, QSplitter)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QColor
from ui.utils.widget_builder import WidgetBuilder
from datetime import datetime

class ExecutionPlanView(QWidget):
    """任务执行计划视图，展示执行历史和实时状态"""
    start_execution = pyqtSignal(str)  # 开始执行信号（传递资源ID或"all"）
    stop_execution = pyqtSignal()      # 停止执行信号
    
    def __init__(self, resource_manager):
        super().__init__()
        self.resource_manager = resource_manager
        self.is_executing = False
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        main_layout = WidgetBuilder.create_vbox_layout()
        
        # 标题和操作按钮
        top_layout = WidgetBuilder.create_hbox_layout()
        top_layout.addWidget(WidgetBuilder.create_label("执行计划", bold=True))
        top_layout.addStretch()
        
        self.run_current_btn = WidgetBuilder.create_button("执行当前资源", "执行当前选中资源的所有任务")
        self.run_all_btn = WidgetBuilder.create_button("执行所有资源", "按顺序执行所有启用资源的任务")
        self.stop_btn = WidgetBuilder.create_button("停止执行", "终止当前正在执行的任务")
        self.clear_log_btn = WidgetBuilder.create_button("清空日志", "清除当前日志内容")
        
        self.run_current_btn.clicked.connect(self.on_run_current)
        self.run_all_btn.clicked.connect(self.on_run_all)
        self.stop_btn.clicked.connect(self.on_stop)
        self.clear_log_btn.clicked.connect(self.clear_log)
        
        # 初始禁用停止按钮
        self.stop_btn.setEnabled(False)
        
        top_layout.addWidget(self.run_current_btn)
        top_layout.addWidget(self.run_all_btn)
        top_layout.addWidget(self.stop_btn)
        top_layout.addWidget(self.clear_log_btn)
        
        main_layout.addLayout(top_layout)
        
        # 分割器（上：执行历史，下：实时日志）
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 执行历史表格
        self.history_table = self.create_history_table()
        splitter.addWidget(self.history_table)
        
        # 实时日志
        self.log_group, log_layout = WidgetBuilder.create_group_box("执行日志")
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        splitter.addWidget(self.log_group)
        
        # 设置分割器比例
        splitter.setSizes([300, 200])
        
        main_layout.addWidget(splitter, 1)
        
        self.setLayout(main_layout)
        
    def create_history_table(self) -> QTableWidget:
        """创建执行历史表格"""
        headers = ["资源名称", "任务ID", "状态", "开始时间", "结束时间", "耗时(秒)"]
        table = WidgetBuilder.create_table_widget(0, len(headers), headers)
        table.setColumnWidth(0, 150)
        table.setColumnWidth(1, 120)
        table.setColumnWidth(2, 80)
        return table
        
    def add_execution_record(self, resource_name: str, task_id: str, status: str, 
                            start_time: str, end_time: str, duration: float):
        """添加执行记录到表格"""
        row = self.history_table.rowCount()
        self.history_table.insertRow(row)
        
        # 设置单元格内容
        self.history_table.setItem(row, 0, QTableWidgetItem(resource_name))
        self.history_table.setItem(row, 1, QTableWidgetItem(task_id))
        
        # 状态单元格（设置颜色）
        status_item = QTableWidgetItem(status)
        if status == "成功":
            status_item.setBackground(QColor(220, 255, 220))
        elif status == "失败":
            status_item.setBackground(QColor(255, 220, 220))
        elif status == "执行中":
            status_item.setBackground(QColor(255, 255, 220))
        self.history_table.setItem(row, 2, status_item)
        
        self.history_table.setItem(row, 3, QTableWidgetItem(start_time))
        self.history_table.setItem(row, 4, QTableWidgetItem(end_time))
        self.history_table.setItem(row, 5, QTableWidgetItem(f"{duration:.2f}"))
        
    def log(self, message: str, is_error: bool = False):
        """添加日志信息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_text = f"[{timestamp}] {message}\n"
        if is_error:
            self.log_text.insertHtml(f"<span style='color: #ff0000;'>{log_text}</span>")
        else:
            self.log_text.insertPlainText(log_text)
        # 滚动到底部
        self.log_text.moveCursor(self.log_text.textCursor().End)
        
    def clear_log(self):
        """清空日志"""
        self.log_text.clear()
        
    def update_execution_status(self, is_executing: bool):
        """更新执行状态"""
        self.is_executing = is_executing
        self.run_current_btn.setEnabled(not is_executing)
        self.run_all_btn.setEnabled(not is_executing)
        self.stop_btn.setEnabled(is_executing)
        
    def on_run_current(self):
        """执行当前资源"""
        current_path = self.resource_manager.get_current_resource_path()
        if not current_path:
            QMessageBox.warning(self, "警告", "请先在资源管理中选择一个有效资源")
            return
            
        self.update_execution_status(True)
        self.log(f"开始执行当前资源: {current_path}")
        self.start_execution.emit("current")
        
    def on_run_all(self):
        """执行所有资源"""
        enabled_resources = self.resource_manager.get_enabled_resources()
        if not enabled_resources:
            QMessageBox.warning(self, "警告", "没有启用的资源可执行")
            return
            
        self.update_execution_status(True)
        self.log(f"开始执行所有启用资源，共 {len(enabled_resources)} 个")
        self.start_execution.emit("all")
        
    def on_stop(self):
        """停止执行"""
        if QMessageBox.question(self, "确认", "确定要停止当前执行吗？", 
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.stop_execution.emit()
            self.log("正在停止执行...")

    # 新增槽函数：适配任务调度器的信号
    @pyqtSlot(str, str, bool, float)
    def on_task_completed(self, resource_name: str, task_id: str, success: bool, duration: float):
        """任务完成时添加执行记录（适配任务调度器的信号）"""
        start_time = datetime.now().strftime("%H:%M:%S")
        end_time = datetime.now().strftime("%H:%M:%S")
        status = "成功" if success else "失败"
        self.add_execution_record(resource_name, task_id, status, start_time, end_time, duration)