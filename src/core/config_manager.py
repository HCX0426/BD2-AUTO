import json
import os

from .path_manager import path_manager


class ConfigLoader:
    def __init__(self):
        # 1. 加载后台默认配置（settings.json）：项目核心参数，不暴露给用户
        self.backend_settings = self._load_config(path_manager.get("backend_settings"), default={})

        # 2. 加载UI用户配置（app_settings.json）：用户通过UI修改的配置
        self.ui_app_settings = self._load_config(path_manager.get("ui_app_settings"), default={})

        # 3. 加载任务配置（task_configs.json）：任务相关配置
        self.task_configs = self._load_config(path_manager.get("task_configs"), default={})

        # 4. 合并最终配置：UI用户配置覆盖后台默认配置
        self.final_settings = self._merge_configs(self.backend_settings, self.ui_app_settings)

    def _load_config(self, config_path: str, default: dict) -> dict:
        """通用加载配置文件（不存在则返回默认值，格式错误提示）"""
        if not os.path.exists(config_path):
            # UI配置文件不存在时，创建空文件（方便用户修改）
            if "app_settings" in config_path:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump({}, f, indent=2)
                print(f"[ConfigLoader] 已创建UI用户配置文件: {config_path}")
            else:
                print(f"[ConfigLoader] 警告：配置文件不存在 {config_path}，使用默认值")
            return default
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"[ConfigLoader] 错误：配置文件 {config_path} 格式错误，使用默认值")
            return default

    def _merge_configs(self, base: dict, override: dict) -> dict:
        """递归合并配置：override（UI配置）覆盖base（后台配置）"""
        merged = base.copy()
        for key, value in override.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                merged[key] = self._merge_configs(merged[key], value)
            else:
                merged[key] = value
        return merged

    def get(self, key_path: str, default=None):
        """获取最终生效的配置（UI配置优先）"""
        return self._get_nested_value(self.final_settings, key_path, default)

    def get_backend(self, key_path: str, default=None):
        """仅获取后台默认配置（不包含UI覆盖）"""
        return self._get_nested_value(self.backend_settings, key_path, default)

    def get_ui(self, key_path: str, default=None):
        """仅获取UI用户配置"""
        return self._get_nested_value(self.ui_app_settings, key_path, default)

    def get_task(self, key_path: str, default=None):
        """获取任务配置"""
        return self._get_nested_value(self.task_configs, key_path, default)

    def save_ui_config(self, ui_config: dict):
        """保存UI用户配置（用户修改后持久化到app_settings.json）"""
        try:
            with open(path_manager.get("ui_app_settings"), "w", encoding="utf-8") as f:
                json.dump(ui_config, f, indent=2, ensure_ascii=False)
            # 保存后更新内存中的配置
            self.ui_app_settings = ui_config
            self.final_settings = self._merge_configs(self.backend_settings, self.ui_app_settings)
            print(f"[ConfigLoader] 已保存UI配置到: {path_manager.get('ui_app_settings')}")
            return True
        except Exception as e:
            print(f"[ConfigLoader] 保存UI配置失败: {str(e)}")
            return False

    def _get_nested_value(self, data: dict, key_path: str, default):
        """
        从嵌套字典按路径获取值
        
        :param data: 要查找的嵌套字典
        :param key_path: 点分隔的路径字符串，如 "device.windows_app_title"
        :param default: 如果路径不存在时返回的默认值
        :return: 找到的值或默认值
        """
        keys = key_path.split(".")
        value = data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value


# 全局配置单例（全项目统一调用）
config = ConfigLoader()
