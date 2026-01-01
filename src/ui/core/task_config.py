import json
import os

from src.core.path_manager import path_manager


class TaskConfigManager:
    """管理任务配置"""

    def __init__(self, config_file=path_manager.get("task_configs")):
        self.config_file = config_file
        self.configs = self.load_configs()

    def load_configs(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载配置文件失败: {str(e)}")
        return {"task_order": [], "task_states": {}, "task_configs": {}}

    def save_configs(self):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
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
