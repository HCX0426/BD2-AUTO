# main_controller.py
import traceback
import os
from PyQt6.QtCore import QObject, pyqtSlot, QThread
from PyQt6.QtWidgets import QMessageBox
from ui.controllers.settings_manager import SettingsManager
from ui.controllers.resource_manager import ResourceManager
from ui.controllers.task_loader import TaskLoader
from ui.controllers.task_scheduler import TaskScheduler

class MainController(QObject):
    """主控制器，协调所有子控制器和视图的交互"""
    def __init__(self, views):
        try:
            super().__init__()
            self.views = views
            
            # 初始化子控制器
            self.resource_manager = ResourceManager()
            self.settings_manager = SettingsManager()
            self.task_loader = TaskLoader()
            self.task_scheduler = TaskScheduler(
                self.resource_manager,
                self.task_loader,
                self.settings_manager
            )

            # 关键：给资源管理视图注入资源管理器实例
            self.views["resource_manager_view"].resource_manager = self.resource_manager
            self.views["resource_manager_view"].refresh_resource_list()
            
            # 建立信号-槽连接
            self.setup_connections()

        except Exception as e:
            print(f"MainController 初始化失败: {str(e)}")
            traceback.print_exc()
            QMessageBox.critical(None, "初始化错误", f"主控制器初始化失败：{str(e)}")
        
    def setup_connections(self):
        """建立所有组件之间的信号-槽连接"""
        # 1. 侧边栏与视图切换
        self.views["sidebar"].item_clicked.connect(
            self.views["main_window"].switch_view
        )
        
        # 2. 资源管理相关（修复：正确的信号连接）
        self.views["resource_manager_view"].resource_changed.connect(
            self.on_resource_changed
        )
        self.resource_manager.resources_updated.connect(
            self.views["resource_manager_view"].refresh_resource_list
        )
        
        # 3. 任务列表相关
        self.views["task_list_view"].task_selected.connect(
            self.on_task_selected
        )
        self.views["task_list_view"].task_started.connect(
            self.on_single_task_started
        )
        self.views["task_list_view"].all_tasks_started.connect(
            self.on_all_tasks_started
        )
        
        # 4. 参数配置相关
        self.views["param_config_view"].params_saved.connect(
            self.on_params_saved
        )
        
        # 5. 执行计划相关
        self.views["execution_plan_view"].start_execution.connect(
            self.on_start_execution
        )
        self.views["execution_plan_view"].stop_execution.connect(
            self.task_scheduler.stop_execution
        )
        
        # 6. 任务调度器与执行计划视图（修复：参数匹配）
        self.task_scheduler.log_message.connect(
            self.views["execution_plan_view"].log
        )
        self.task_scheduler.execution_started.connect(
            self.on_execution_started
        )
        self.task_scheduler.execution_completed.connect(
            self.on_execution_completed
        )
        self.task_scheduler.task_started.connect(
            self.on_task_started
        )
        self.task_scheduler.task_completed.connect(
            self.on_task_completed
        )
        
        # 7. 设置面板相关
        self.views["settings_panel"].settings_saved.connect(
            self.settings_manager.save_settings
        )
        self.views["settings_panel"].theme_changed.connect(
            self.on_theme_changed
        )
        self.settings_manager.settings_updated.connect(
            self.on_settings_updated
        )
        
        # 8. 任务加载器相关
        self.task_loader.task_loaded.connect(
            self.on_task_loaded
        )
        self.task_loader.load_failed.connect(
            self.on_task_load_failed
        )
    
    @pyqtSlot(str)
    def on_resource_changed(self, resource_path: str):
        """资源变更时：通过任务加载器加载任务"""
        if not resource_path or not os.path.exists(resource_path):
            self.views["execution_plan_view"].log(f"无效的资源路径：{resource_path}", True)
            return
        
        # 通过任务加载器加载任务
        task_mapping = self.task_loader.load_tasks_from_path(resource_path)
        if task_mapping:
            # 更新任务列表视图
            self.views["task_list_view"].update_task_list(task_mapping)
            self.views["execution_plan_view"].log(f"从 {resource_path} 加载到 {len(task_mapping)} 个任务")
        else:
            self.views["execution_plan_view"].log(f"从 {resource_path} 未找到可执行任务", True)
    
    @pyqtSlot(str)
    def on_task_selected(self, task_id: str):
        """任务选中时加载其参数配置"""
        task_info = self.views["task_list_view"].current_tasks.get(task_id)
        if task_info:
            self.views["param_config_view"].load_task_params(task_id, task_info)
        else:
            self.views["execution_plan_view"].log(f"未找到任务 {task_id} 的配置信息", True)
    
    @pyqtSlot(str)
    def on_single_task_started(self, task_id: str):
        """执行单个任务"""
        if self.task_scheduler.isRunning():
            QMessageBox.warning(self.views["main_window"], "警告", "当前已有任务在执行中")
            return
            
        current_resource = self.resource_manager.get_current_resource()
        if not current_resource:
            self.views["execution_plan_view"].log("未选择有效资源，无法执行任务", True)
            return
            
        resource_name = current_resource["name"]
        self.views["execution_plan_view"].update_execution_status(True)
        
        self.task_scheduler.set_run_mode("single")
        self.task_scheduler.set_single_task(resource_name, task_id)
        self.task_scheduler.start()

    @pyqtSlot(list)
    def on_all_tasks_started(self, task_ids: list):
        """执行当前资源的所有任务"""
        if self.task_scheduler.isRunning():
            QMessageBox.warning(self.views["main_window"], "警告", "当前已有任务在执行中")
            return
            
        current_resource = self.resource_manager.get_current_resource()
        if not current_resource:
            self.views["execution_plan_view"].log("未选择有效资源，无法执行任务", True)
            return
            
        if not task_ids:
            self.views["execution_plan_view"].log("当前资源下无可用任务", True)
            return
            
        self.views["execution_plan_view"].update_execution_status(True)
        self.views["execution_plan_view"].log(f"开始执行当前资源的所有任务（共{len(task_ids)}个）")
        
        self.task_scheduler.set_run_mode("current")
        self.task_scheduler.start()
    
    @pyqtSlot(dict)
    def on_params_saved(self, params_data: dict):
        """保存任务参数"""
        task_id = params_data.get("task_id")
        if not task_id:
            self.views["execution_plan_view"].log("参数保存失败：未指定任务ID", True)
            return
            
        params = params_data.get("params", {})
        self.task_scheduler.set_task_params(task_id, params)
        self.views["execution_plan_view"].log(f"任务 {task_id} 参数已更新")
    
    @pyqtSlot(str)
    def on_start_execution(self, mode: str):
        """开始执行任务"""
        if self.task_scheduler.isRunning():
            QMessageBox.warning(self.views["main_window"], "警告", "当前已有任务在执行中")
            return
            
        if mode not in ["current", "all"]:
            self.views["execution_plan_view"].log(f"无效的执行模式：{mode}", True)
            return
            
        self.task_scheduler.set_run_mode(mode)
        self.task_scheduler.start()
    
    @pyqtSlot(str)
    def on_execution_started(self, resource_name: str):
        """执行开始时更新UI状态"""
        self.views["execution_plan_view"].update_execution_status(True)
        self.views["execution_plan_view"].log(f"开始执行资源 [{resource_name}] 的任务")
    
    @pyqtSlot(bool)
    def on_execution_completed(self, success: bool):
        """执行完成时更新UI状态"""
        self.views["execution_plan_view"].update_execution_status(False)
        status = "成功" if success else "失败"
        self.views["execution_plan_view"].log(f"所有任务执行{status}", not success)
    
    @pyqtSlot(str, str)
    def on_task_started(self, resource_name: str, task_id: str):
        """任务开始时记录日志"""
        self.views["execution_plan_view"].log(f"[{resource_name}] 任务 {task_id} 开始执行")
    
    @pyqtSlot(str, str, bool, float)
    def on_task_completed(self, resource_name: str, task_id: str, success: bool, duration: float):
        """任务完成时添加执行记录"""
        from datetime import datetime
        start_time = datetime.now().strftime("%H:%M:%S")
        end_time = datetime.now().strftime("%H:%M:%S")
        status = "成功" if success else "失败"
        
        self.views["execution_plan_view"].add_execution_record(
            resource_name, task_id, status, start_time, end_time, duration
        )
    
    @pyqtSlot(str, dict)
    def on_task_loaded(self, resource_path: str, task_data: dict):
        """任务加载完成时输出日志"""
        task_id = next(iter(task_data.keys()), "未知任务")
        self.views["execution_plan_view"].log(f"从 {resource_path} 成功加载任务: {task_id}")
    
    @pyqtSlot(str, str)
    def on_task_load_failed(self, resource_path: str, error: str):
        """任务加载失败时显示错误"""
        self.views["execution_plan_view"].log(f"从 {resource_path} 加载任务失败: {error}", True)
    
    @pyqtSlot(str)
    def on_theme_changed(self, theme: str):
        """主题变更时更新全局样式"""
        self.views["main_window"].load_styles()
        self.views["execution_plan_view"].log(f"主题已切换为: {theme}")
    
    @pyqtSlot(dict)
    def on_settings_updated(self, settings: dict):
        """设置更新时处理逻辑"""
        self.views["execution_plan_view"].log("应用设置已更新，部分设置需重启生效")