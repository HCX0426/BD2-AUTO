import os
import json
from PyQt6.QtCore import QObject, pyqtSignal
from auto_control.config.auto_config import PROJECT_ROOT

# 设置文件路径
SETTINGS_FILE = os.path.join(PROJECT_ROOT, 'ui', 'configs', 'app_settings.json')

class SettingsManager(QObject):
    """应用程序设置管理器，负责加载、保存和管理全局设置"""
    settings_updated = pyqtSignal(dict)  # 设置更新信号
    
    def __init__(self):
        super().__init__()
        self.settings = self.load_settings()  # 存储所有设置
        
    def load_settings(self) -> dict:
        """从文件加载设置，不存在则返回默认设置"""
        default_settings = {
            "appearance": {
                "theme": "light",
                "font_size": 12,
                "compact_mode": False
            },
            "paths": {
                "log": os.path.join(PROJECT_ROOT, "logs"),
                "cache": os.path.join(PROJECT_ROOT, "cache")
            },
            "logging": {
                "level": "INFO",
                "save_days": 7,
                "save_to_file": True
            },
            "execution": {
                "auto_continue": False,  # 失败后是否自动继续
                "retry_count": 1         # 失败重试次数
            }
        }
        
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # 合并默认设置（确保新增配置项有默认值）
                    return self._merge_settings(default_settings, loaded)
        except Exception as e:
            print(f"加载设置失败: {str(e)}")
            
        return default_settings
    
    def _merge_settings(self, default: dict, custom: dict) -> dict:
        """合并默认设置和自定义设置（递归处理嵌套字典）"""
        merged = default.copy()
        for key, value in custom.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                merged[key] = self._merge_settings(merged[key], value)
            else:
                merged[key] = value
        return merged
    
    def save_settings(self, new_settings: dict) -> bool:
        """保存设置到文件"""
        try:
            # 确保配置目录存在
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            
            # 合并新设置
            self.settings = self._merge_settings(self.settings, new_settings)
            
            # 写入文件
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
                
            # 发送设置更新信号
            self.settings_updated.emit(self.settings)
            return True
        except Exception as e:
            print(f"保存设置失败: {str(e)}")
            return False
    
    def get_setting(self, path: str, default=None):
        """
        获取指定路径的设置值
        
        Args:
            path: 设置路径，如 "appearance.theme"
            default: 不存在时返回的默认值
        """
        parts = path.split('.')
        current = self.settings
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current
    
    def set_setting(self, path: str, value) -> bool:
        """
        设置指定路径的设置值
        
        Args:
            path: 设置路径，如 "execution.auto_continue"
            value: 要设置的值
        """
        parts = path.split('.')
        current = self.settings
        parent = None
        last_part = None
        
        # 遍历路径找到父节点
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                last_part = part
                break
            if isinstance(current, dict) and part in current:
                parent = current
                current = current[part]
            else:
                return False  # 路径不存在
        
        if parent is not None and last_part is not None:
            parent[last_part] = value
            return self.save_settings(self.settings)
        return False