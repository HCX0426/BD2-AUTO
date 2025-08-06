import sys
import threading
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
                            QLabel, QTextEdit, QMessageBox, QGroupBox, QProgressBar,
                            QSplitter)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QTextCursor

# 导入任务和核心类
from auto_control.auto import Auto
from auto_tasks.pc.login import login
# 导入所有任务
from auto_tasks.pc.daily_missions import daily_missions
from auto_tasks.pc.get_email import get_email
from auto_tasks.pc.get_guild import get_guild
from auto_tasks.pc.get_pvp import get_pvp
from auto_tasks.pc.get_restaurant import get_restaurant
from auto_tasks.pc.intensive_decomposition import intensive_decomposition
from auto_tasks.pc.lucky_draw import lucky_draw
from auto_tasks.pc.map_collection import map_collection
from auto_tasks.pc.pass_activity import pass_activity
from auto_tasks.pc.pass_rewards import pass_rewards
from auto_tasks.pc.sweep_daily import sweep_daily

# 任务映射表 - 与控制台模式保持一致
TASK_MAPPING = {
    "login": {"name": "登录游戏", "function": login},
    "get_guild": {"name": "获取公会奖励", "function": get_guild},
    "get_pvp": {"name": "PVP任务", "function": get_pvp},
    "get_restaurant": {"name": "餐厅任务", "function": get_restaurant},
    "intensive_decomposition": {"name": "强化分解", "function": intensive_decomposition},
    "lucky_draw": {"name": "幸运抽奖", "function": lucky_draw},
    "map_collection": {"name": "地图收集", "function": map_collection},
    "pass_activity": {"name": "活动通关", "function": pass_activity},
    "sweep_daily": {"name": "每日扫荡", "function": sweep_daily},
    "pass_rewards": {"name": "通关奖励", "function": pass_rewards},
    "get_email": {"name": "领取邮件", "function": get_email},
    "daily": {"name": "每日任务", "function": daily_missions},
}

# 日志信号类 - 用于线程安全的日志更新
class LogSignal(QObject):
    log_updated = pyqtSignal(str)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.auto_instance = None  # 全局唯一的Auto实例
        self.task_thread = None    # 任务执行线程
        self.task_running = False  # 任务运行状态
        self.log_signal = LogSignal()  # 日志信号
        self.log_signal.log_updated.connect(self.update_log)  # 连接日志更新信号
        
        self.init_ui()
        
    def init_ui(self):
        """初始化UI界面"""
        # 设置窗口基本属性
        self.setWindowTitle("自动任务控制系统")
        self.setGeometry(100, 100, 1000, 700)
        self.setMinimumSize(800, 600)
        
        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # 创建顶部信息栏
        top_info = QLabel("任务控制系统 - 就绪状态")
        top_info.setStyleSheet("background-color: #f0f0f0; padding: 8px; font-weight: bold;")
        main_layout.addWidget(top_info)
        
        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 左侧任务列表区域
        task_group = QGroupBox("可选任务 (勾选要执行的任务)")
        task_layout = QVBoxLayout()
        
        self.task_list = QListWidget()
        self.task_list.setAlternatingRowColors(True)
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
        
        # 右侧日志区域
        log_group = QGroupBox("执行日志")
        log_layout = QVBoxLayout()
        
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("SimHei", 9))  # 设置中文字体
        log_layout.addWidget(self.log_display)
        log_group.setLayout(log_layout)
        
        # 添加到分割器
        splitter.addWidget(task_group)
        splitter.addWidget(log_group)
        splitter.setSizes([300, 400])  # 设置初始大小比例
        main_layout.addWidget(splitter)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)
        
        # 底部控制按钮
        control_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("开始任务")
        self.stop_btn = QPushButton("停止任务")
        self.stop_btn.setEnabled(False)  # 初始禁用
        self.clear_log_btn = QPushButton("清空日志")
        
        # 绑定按钮事件
        self.start_btn.clicked.connect(self.start_task)
        self.stop_btn.clicked.connect(self.stop_task)
        self.clear_log_btn.clicked.connect(self.clear_log)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.clear_log_btn)
        main_layout.addLayout(control_layout)
        
    def populate_task_list(self):
        """填充任务列表"""
        for task_id, task_info in TASK_MAPPING.items():
            item = QListWidgetItem(task_info["name"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, task_id)  # 存储任务ID
            self.task_list.addItem(item)
    
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
        self.task_thread = threading.Thread(
            target=self.execute_tasks,
            args=(selected_tasks,),
            daemon=True
        )
        self.task_thread.start()
    
    def execute_tasks(self, selected_tasks):
        """在后台线程执行任务"""
        try:
            # 登录游戏（如果未包含在选中任务中，则自动执行）
            if "login" not in selected_tasks:
                self.log_signal.log_updated.emit("执行登录流程...")
                if not login(self.auto_instance):
                    self.log_signal.log_updated.emit("登录失败，终止任务执行")
                    self.reset_task_state()
                    return
            
            total_tasks = len(selected_tasks)
            for index, task_id in enumerate(selected_tasks):
                # 检查是否需要停止
                if self.auto_instance.check_should_stop():
                    self.log_signal.log_updated.emit("任务被用户中断")
                    break
                
                # 更新进度
                progress = int((index / total_tasks) * 100)
                self.progress_bar.setValue(progress)
                
                # 执行任务
                task_info = TASK_MAPPING.get(task_id)
                if not task_info:
                    self.log_signal.log_updated.emit(f"未知任务: {task_id}")
                    continue
                
                self.log_signal.log_updated.emit(f"===== 开始执行: {task_info['name']} =====")
                try:
                    task_func = task_info["function"]
                    success = task_func(self.auto_instance)
                    result = "成功" if success else "失败"
                    self.log_signal.log_updated.emit(f"{task_info['name']} 执行{result}")
                except Exception as e:
                    self.log_signal.log_updated.emit(f"{task_info['name']} 执行出错: {str(e)}")
            
            self.log_signal.log_updated.emit("所有任务执行完毕")
            self.progress_bar.setValue(100)
            
        except Exception as e:
            self.log_signal.log_updated.emit(f"任务执行框架错误: {str(e)}")
        finally:
            # 确保资源释放
            if self.auto_instance:
                self.auto_instance.stop()
            self.reset_task_state()
    
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
        # 在主线程中更新UI
        self.task_running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.task_list.setEnabled(True)
        self.select_all_btn.setEnabled(True)
        self.deselect_all_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log("任务执行已停止")
    
    def log(self, message):
        """添加日志信息"""
        self.log_display.append(message)
        # 滚动到最新日志
        self.log_display.moveCursor(QTextCursor.MoveOperation.End)
    
    def update_log(self, message):
        """通过信号槽更新日志（线程安全）"""
        self.log(message)
    
    def clear_log(self):
        """清空日志显示"""
        self.log_display.clear()

if __name__ == "__main__":
    # 确保中文显示正常
    app = QApplication(sys.argv)
    font = QFont("SimHei")
    app.setFont(font)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
    