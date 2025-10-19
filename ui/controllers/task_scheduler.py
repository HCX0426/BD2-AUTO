import time
from datetime import datetime
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from typing import List, Dict, Callable, Optional
from ui.controllers.resource_manager import ResourceManager
from ui.controllers.task_loader import TaskLoader

class TaskScheduler(QThread):
    """任务调度器，负责执行任务并管理执行流程（完善版）"""
    # 执行状态信号（原有不变）
    execution_started = pyqtSignal(str)
    task_started = pyqtSignal(str, str)
    task_completed = pyqtSignal(str, str, bool, float)
    execution_completed = pyqtSignal(bool)
    log_message = pyqtSignal(str, bool)
    progress_updated = pyqtSignal(int)
    
    def __init__(self, 
                 resource_manager: ResourceManager,
                 task_loader: TaskLoader,
                 settings_manager):
        super().__init__()
        self.resource_manager = resource_manager
        self.task_loader = task_loader
        self.settings_manager = settings_manager
        self.run_mode = "current"
        self.should_stop = False
        self.current_params = {}
        self.single_task_info = None
        self.total_tasks = 0
        self.completed_tasks = 0
        self.task_mapping_cache = {}  # 新增：缓存资源的任务映射，避免重复加载
        
    def set_run_mode(self, mode: str):
        """设置运行模式"""
        valid_modes = ["current", "all", "single"]
        self.run_mode = mode if mode in valid_modes else "current"
        
    def set_task_params(self, task_id: str, params: dict):
        """设置任务参数"""
        self.current_params[task_id] = params.copy()
        
    def set_single_task(self, resource_name: str, task_id: str):
        """设置单个任务信息（配合single模式使用）"""
        self.single_task_info = (resource_name, task_id)
        
    def stop_execution(self):
        """停止执行（线程安全）"""
        self.should_stop = True
        
    def run(self):
        """执行任务主流程（新增：清空缓存）"""
        self.should_stop = False
        self.total_tasks = 0
        self.completed_tasks = 0
        self.task_mapping_cache.clear()  # 清空上一轮缓存
        all_success = True
        
        try:
            if self.run_mode == "single":
                success = self._execute_single_task()
                all_success = success
            elif self.run_mode == "current":
                all_success = self._execute_current_resource()
            else:  # all
                all_success = self._execute_all_resources()
                
        except Exception as e:
            self.log_message.emit(f"调度器执行错误: {str(e)}", True)
            all_success = False
        finally:
            self.progress_updated.emit(100 if all_success else 0)
            self.execution_completed.emit(all_success)
            self.single_task_info = None
            self.total_tasks = 0
            self.completed_tasks = 0
            self.task_mapping_cache.clear()  # 执行后清空缓存
            
    def _execute_single_task(self) -> bool:
        """执行单个指定任务"""
        if not self.single_task_info:
            self.log_message.emit("未指定单个任务信息", True)
            return False
            
        resource_name, task_id = self.single_task_info
        current_resource = self.resource_manager.get_current_resource()
        if not current_resource:
            self.log_message.emit("当前资源无效", True)
            return False
            
        resource_path = current_resource["path"]
        self.execution_started.emit(resource_name)
        self.log_message.emit(f"开始执行单个任务: {task_id} (资源: {resource_name})", False)
        
        # 加载该资源下的任务
        task_mapping = self.task_loader.load_tasks_from_path(resource_path)
        if not task_mapping or task_id not in task_mapping:
            self.log_message.emit(f"任务 {task_id} 不存在或加载失败", True)
            return False
            
        # 执行单个任务
        self.total_tasks = 1
        self.progress_updated.emit(0)
        success = self._execute_single_task_instance(
            resource_name, task_id, task_mapping[task_id]
        )
        self.progress_updated.emit(100 if success else 0)
        
        return success
        
    def _execute_current_resource(self) -> bool:
        """执行当前资源下的所有任务"""
        current_index = self.resource_manager.current_index
        resources = [self.resource_manager.resources[current_index]] if 0 <= current_index < len(self.resource_manager.resources) else []
        return self._execute_resources_list(resources)
        
    def _execute_all_resources(self) -> bool:
        """执行所有启用资源下的任务"""
        resources = self.resource_manager.get_enabled_resources()
        return self._execute_resources_list(resources)
        
    def _execute_resources_list(self, resources: List[dict]) -> bool:
        """执行资源列表中的所有任务（修复：使用缓存避免重复加载）"""
        if not resources:
            self.log_message.emit("没有可执行的资源", True)
            return False
            
        # 修复：先缓存所有资源的任务映射，再计算总任务数
        for res in resources:
            if self.should_stop:
                break
            resource_path = res['path']
            if resource_path not in self.task_mapping_cache:
                # 仅首次加载时缓存
                self.task_mapping_cache[resource_path] = self.task_loader.load_tasks_from_path(resource_path)
        
        # 计算总任务数（使用缓存）
        self.total_tasks = sum(len(self.task_mapping_cache[res['path']]) for res in resources if res['path'] in self.task_mapping_cache)
        self.completed_tasks = 0
        self.progress_updated.emit(0)
        
        all_success = True
        for res in resources:
            if self.should_stop:
                self.log_message.emit("执行已被用户终止", False)
                all_success = False
                break
                
            resource_name = res['name']
            resource_path = res['path']
            self.execution_started.emit(resource_name)
            self.log_message.emit(f"开始处理资源: {resource_name} ({resource_path})", False)
            
            # 修复：从缓存获取任务映射，避免重复加载
            task_mapping = self.task_mapping_cache.get(resource_path, {})
            if not task_mapping:
                self.log_message.emit(f"资源 {resource_name} 中未找到可用任务", True)
                all_success = False
                continue
                
            # 执行资源内所有任务
            resource_success = self.execute_resource_tasks(resource_name, task_mapping)
            if not resource_success:
                all_success = False
                
                # 根据设置判断是否继续执行下一个资源
                auto_continue = self.settings_manager.get_setting("execution.auto_continue", False)
                if not auto_continue:
                    self.log_message.emit("根据设置，一个资源执行失败后停止后续执行", False)
                    break
                    
        return all_success
        
    def _calculate_total_tasks(self, resources: List[dict]) -> int:
        """计算总任务数（用于进度条）"""
        total = 0
        for res in resources:
            if res.get('enabled', True):
                resource_path = res['path']
                task_mapping = self.task_loader.load_tasks_from_path(resource_path)
                total += len(task_mapping)
        return total
        
    def execute_resource_tasks(self, resource_name: str, task_mapping: Dict[str, dict]) -> bool:
        """执行单个资源下的所有任务"""
        task_ids = list(task_mapping.keys())
        self.log_message.emit(f"找到 {len(task_ids)} 个任务，开始执行...", False)
        all_success = True
        
        for task_id in task_ids:
            if self.should_stop:
                return False
                
            # 执行单个任务实例
            task_success = self._execute_single_task_instance(
                resource_name, task_id, task_mapping[task_id]
            )
            
            if not task_success:
                all_success = False
                
                # 根据设置判断是否继续执行下一个任务
                auto_continue = self.settings_manager.get_setting("execution.auto_continue", False)
                if not auto_continue:
                    self.log_message.emit("根据设置，一个任务执行失败后停止后续任务", False)
                    break
                    
        return all_success
        
    def _execute_single_task_instance(self, resource_name: str, task_id: str, task_info: dict) -> bool:
        """执行单个任务实例（原子操作）"""
        task_name = task_info.get('name', task_id)
        self.task_started.emit(resource_name, task_id)
        self.log_message.emit(f"开始执行任务: {task_name}", False)
        
        start_time = time.time()
        success = False
        retry_count = self.settings_manager.get_setting("execution.retry_count", 1)
        current_retry = 0
        
        # 带重试机制执行任务
        while current_retry <= retry_count and not success and not self.should_stop:
            try:
                # 获取任务参数
                task_params = self.current_params.get(task_id, {})
                
                # 执行任务（调用任务模块中的run_task函数）
                run_func = task_info.get('run_func')
                if not run_func:
                    raise Exception("任务缺少执行函数 run_task")
                    
                # 执行任务（支持任务内检查停止信号）
                result = run_func(stop_checker=lambda: self.should_stop, **task_params)
                success = True if result is None else bool(result)
                
            except Exception as e:
                current_retry += 1
                self.log_message.emit(
                    f"任务 {task_name} 执行失败 (重试 {current_retry}/{retry_count}): {str(e)}", 
                    True
                )
                if current_retry > retry_count:
                    success = False
            finally:
                if self.should_stop:
                    break
        
        # 记录执行结果
        duration = time.time() - start_time
        self.task_completed.emit(resource_name, task_id, success, duration)
        self.log_message.emit(
            f"任务 {task_name} 执行{'成功' if success else '失败'}，耗时 {duration:.2f}秒", 
            not success
        )
        
        # 更新进度
        self.completed_tasks += 1
        if self.total_tasks > 0:
            progress = int((self.completed_tasks / self.total_tasks) * 100)
            self.progress_updated.emit(progress)
            
        return success
