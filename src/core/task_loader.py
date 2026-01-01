import inspect
import os
import sys

from .path_manager import path_manager


def load_task_modules():
    """动态加载任务模块（适配开发/打包环境）"""
    task_mapping = {}
    task_dir = path_manager.get("task_path")

    # 新增：检查任务目录是否存在
    if not os.path.exists(task_dir):
        print(f"任务目录不存在: {task_dir}")
        return task_mapping  # 返回空字典而非报错

    # 将任务目录添加到sys.path，让__import__能找到模块
    if task_dir not in sys.path:
        sys.path.insert(0, task_dir)

    for filename in os.listdir(task_dir):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]
            try:
                module = __import__(module_name)

                # 验证模块是否包含对应任务函数
                if hasattr(module, module_name):
                    task_func = getattr(module, module_name)
                    doc = inspect.getdoc(task_func) or ""
                    sig = inspect.signature(task_func)
                    params = []
                    for param_name, param in sig.parameters.items():
                        if param_name != "auto":
                            default = param.default if param.default != inspect.Parameter.empty else None
                            annotation = param.annotation if param.annotation != inspect.Parameter.empty else ""
                            params.append(
                                {
                                    "name": param_name,
                                    "default": default,
                                    "annotation": str(annotation),
                                    "type": type(default).__name__ if default is not None else "str",
                                }
                            )
                    task_mapping[module_name] = {
                        "name": module_name.replace("_", " ").title(),
                        "function": task_func,
                        "description": doc,
                        "parameters": params,
                    }
            except Exception as e:
                print(f"加载任务模块 {module_name} 失败: {str(e)}")  # 调试用
    return task_mapping
