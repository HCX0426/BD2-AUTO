import os
import sys
import importlib
import importlib.util
from PyQt6.QtCore import QObject, pyqtSignal
from typing import Dict, Any

class TaskLoader(QObject):
    """任务加载器，负责从指定资源路径加载任务模块"""
    task_loaded = pyqtSignal(str, dict)  # 任务加载完成信号 (资源路径, 任务映射)
    load_failed = pyqtSignal(str, str)   # 加载失败信号 (资源路径, 错误信息)
    
    def __init__(self):
        super().__init__()
        
    def load_tasks_from_path(self, resource_path: str) -> Dict[str, Any]:
        """
        从指定资源路径加载所有任务模块
        
        Args:
            resource_path: 资源路径
            
        Returns:
            任务映射字典 {任务ID: 任务信息}
        """
        if not os.path.exists(resource_path):
            self.load_failed.emit(resource_path, f"路径不存在: {resource_path}")
            return {}
            
        # 确保资源路径在Python路径中
        if resource_path not in sys.path:
            sys.path.append(resource_path)
            
        task_mapping = {}
        
        try:
            # 遍历路径下的所有Python文件
            for filename in os.listdir(resource_path):
                if filename.endswith('.py') and not filename.startswith('__'):
                    module_name = filename[:-3]
                    task_id = module_name  # 以模块名为任务ID
                    
                    try:
                        # 动态导入模块
                        spec = importlib.util.spec_from_file_location(
                            module_name, 
                            os.path.join(resource_path, filename)
                        )
                        if spec and spec.loader:
                            module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(module)
                            
                            # 解析任务信息（假设模块中定义了TASK_INFO字典）
                            if hasattr(module, 'TASK_INFO'):
                                task_info = module.TASK_INFO.copy()
                                # 添加执行函数引用
                                if hasattr(module, 'run_task'):
                                    task_info['run_func'] = module.run_task
                                else:
                                    task_info['run_func'] = None
                                    
                                task_mapping[task_id] = task_info
                                self.task_loaded.emit(resource_path, {task_id: task_info})
                            else:
                                self.load_failed.emit(
                                    resource_path, 
                                    f"模块 {module_name} 缺少TASK_INFO定义"
                                )
                                
                    except Exception as e:
                        self.load_failed.emit(
                            resource_path, 
                            f"加载模块 {module_name} 失败: {str(e)}"
                        )
                        
        except Exception as e:
            self.load_failed.emit(resource_path, f"遍历资源路径失败: {str(e)}")
            
        return task_mapping