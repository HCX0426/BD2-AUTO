import os
import json
import inspect
from PyQt6.QtCore import QThread, pyqtSignal
from auto_control.auto import Auto
from auto_control.config.auto_config import PROJECT_ROOT
from auto_control.config.st_config import generate_report

# 任务模块路径
TASKS_DIR = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc')
# 配置文件路径
CONFIG_FILE = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc', 'task_configs.json')
# 应用设置文件路径
SETTINGS_FILE = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc', 'app_settings.json')

def load_task_modules():
    """动态加载任务模块"""
    task_mapping = {}
    for filename in os.listdir(TASKS_DIR):
        if filename.endswith('.py') and not filename.startswith('__'):
            module_name = filename[:-3]
            try:
                module = __import__(f'auto_tasks.pc.{module_name}', fromlist=[module_name])
                if hasattr(module, module_name):
                    task_func = getattr(module, module_name)
                    doc = inspect.getdoc(task_func) or ""
                    sig = inspect.signature(task_func)
                    params = []
                    for param_name, param in sig.parameters.items():
                        if param_name != 'auto':
                            default = param.default if param.default != inspect.Parameter.empty else None
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

class AppSettingsManager:
    """管理应用设置"""
    def __init__(self, settings_file=SETTINGS_FILE):
        self.settings_file = settings_file
        self.settings = self.load_settings()
    
    def load_settings(self):
        default_settings = {
            "sidebar_width": 200,
            "sidebar_visible": True,
            "window_size": [1280, 720],
            "theme": "light"
        }
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    return {**default_settings, **json.load(f)}
        except Exception as e:
            print(f"加载应用设置失败: {str(e)}")
        return default_settings
    
    def save_settings(self):
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"保存应用设置失败: {str(e)}")
            return False
    
    def get_setting(self, key, default=None):
        return self.settings.get(key, default)
    
    def set_setting(self, key, value):
        self.settings[key] = value
        return self.save_settings()

class TaskConfigManager:
    """管理任务配置"""
    def __init__(self, config_file=CONFIG_FILE):
        self.config_file = config_file
        self.configs = self.load_configs()
        
    def load_configs(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载配置文件失败: {str(e)}")
        return {
            "task_order": [],
            "task_states": {},
            "task_configs": {}
        }
    
    def save_configs(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.configs, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"保存配置文件失败: {str(e)}")
            return False
    
    def get_task_config(self, task_id):
        return self.configs.get("task_configs", {}).get(task_id, {})
    
    def save_task_config(self, task_id, config):
        if "task_configs" not in self.configs:
            self.configs["task_configs"] = {}
        self.configs["task_configs"][task_id] = config
        return self.save_configs()
    
    def save_task_order_and_states(self, task_ids, task_states):
        self.configs["task_order"] = task_ids
        self.configs["task_states"] = task_states
        return self.save_configs()
    
    def get_task_order(self):
        return self.configs.get("task_order", [])
    
    def get_task_states(self):
        return self.configs.get("task_states", {})

class TaskWorker(QThread):
    """任务执行线程"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished = pyqtSignal()
    
    def __init__(self, auto_instance, selected_tasks, config_manager, task_mapping):
        super().__init__()
        self.auto_instance = auto_instance
        self.selected_tasks = selected_tasks
        self.config_manager = config_manager
        self.task_mapping = task_mapping
        self.should_stop = False
    
    def run(self):
        try:
            # if "login" not in self.selected_tasks:
            #     self.log_signal.emit("执行登录流程...")
            #     from auto_tasks.pc.login import login
            #     if not login(self.auto_instance):
            #         self.log_signal.emit("登录失败，终止任务执行")
            #         self.finished.emit()
            #         return
            
            total_tasks = len(self.selected_tasks)
            for index, task_id in enumerate(self.selected_tasks):
                if self.auto_instance.check_should_stop():
                    self.log_signal.emit("任务被用户中断")
                    break
                
                self.progress_signal.emit(int((index / total_tasks) * 100))
                task_info = self.task_mapping.get(task_id)
                if not task_info:
                    self.log_signal.emit(f"未知任务: {task_id}")
                    continue
                
                self.log_signal.emit(f"===== 开始执行: {task_info['name']} =====")
                try:
                    task_func = task_info["function"]
                    task_params = self.config_manager.get_task_config(task_id)
                    success = task_func(self.auto_instance, **task_params)
                    result = "成功" if success else "失败"
                    self.log_signal.emit(f"{task_info['name']} 执行{result}")
                except Exception as e:
                    self.log_signal.emit(f"{task_info['name']} 执行出错: {str(e)}")
            
            self.progress_signal.emit(100)
            self.log_signal.emit("所有任务执行完毕")
            
        except Exception as e:
            self.log_signal.emit(f"任务执行框架错误: {str(e)}")
        finally:
            generate_report(__file__)
            self.finished.emit()