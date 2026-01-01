import json
import os

from src.core.path_manager import path_manager


class AppSettingsManager:
    """管理应用设置"""

    def __init__(self, settings_file=path_manager.get("app_settings")):
        self.settings_file = settings_file
        self.settings = self.load_settings()

    def load_settings(self):
        default_settings = {
            "sidebar_width": 60,
            "sidebar_visible": True,
            "window_size": [1280, 720],
            "theme": "light",
            "remember_window_pos": True,
            "window_pos": None,
            "device_type": "windows",
        }
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    return {**default_settings, **json.load(f)}
        except Exception as e:
            print(f"加载应用设置失败: {str(e)}")
        return default_settings

    def save_settings(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
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
