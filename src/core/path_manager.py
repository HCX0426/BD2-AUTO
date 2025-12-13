import os
import sys
import json

class PathManager:
    def __init__(self):
        self.env = self._get_env()  # 自动判断 dev/prod
        self._init_base_paths()  # 初始化基础路径（static_base/dynamic_base）
        self._init_all_paths()   # 初始化所有具体路径（包括 task_path）
        self._print_path_info()  # 最后打印路径信息（确保所有属性已定义）

    def _get_env(self) -> str:
        """自动判断环境：打包后=prod，开发环境=dev"""
        if getattr(sys, 'frozen', False):
            return "prod"
        return "dev"

    def _init_base_paths(self):
        """初始化基础路径（static_base/dynamic_base）"""
        self.is_packaged = getattr(sys, 'frozen', False)
        self.meipass_path = sys._MEIPASS if self.is_packaged else None

        if self.is_packaged:
            self.static_base = self.meipass_path
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))  # src/core
            src_dir = os.path.dirname(current_dir)  # src
            self.static_base = os.path.dirname(src_dir)  # BD2-AUTO

        # 动态数据路径
        if self.env == "prod":
            self.dynamic_base = os.path.join(self.static_base, "runtime", "prod")
        else:
            self.dynamic_base = os.path.join(self.static_base, "runtime", "dev")

        os.makedirs(self.dynamic_base, exist_ok=True)
        # 此处不打印，避免访问未定义的属性

    def _init_all_paths(self):
        """统一定义所有路径（包括 task_path）"""
        # 1. 后台配置文件（settings.json）：项目核心默认配置（不暴露给UI）
        self.backend_settings_path = os.path.join(self.static_base, "config", self.env, "settings.json")
        
        # 2. UI用户配置文件（app_settings.json）：用户通过UI修改的配置（持久化）
        if self.is_packaged:
            self.ui_app_settings_path = os.path.join(self.dynamic_base, "app_settings.json")
        else:
            self.ui_app_settings_path = os.path.join(self.dynamic_base, "app_settings.json")

        # 3. 其他原有路径
        self.task_template_path = os.path.join(self.static_base, "src", "auto_tasks", "pc", "templates")
        self.task_path = os.path.join(self.static_base, "src", "auto_tasks", "pc")  # 定义 task_path
        self.log_path = os.path.join(self.dynamic_base, "logs")
        self.cache_path = os.path.join(self.dynamic_base, "cache")
        self.task_configs_path = os.path.join(self.dynamic_base, "task_configs.json")
        self.match_temple_debug_path = os.path.join(self.dynamic_base, "temple_debug")
        self.match_ocr_debug_path = os.path.join(self.dynamic_base, "ocr_debug")

        self.ocr_model_path = os.path.join(self.dynamic_base, "ocr_models")  # OCR模型存储目录

        # 收集所有需要创建的目录路径
        dirs_to_create = [
            os.path.dirname(self.ui_app_settings_path),
            self.log_path,
            self.cache_path,
            self.match_temple_debug_path,
            self.match_ocr_debug_path,
            self.ocr_model_path,

        ]

        # 去重后循环创建目录
        for dir_path in set(dirs_to_create):
            os.makedirs(dir_path, exist_ok=True)

    def _print_path_info(self):
        """打印路径信息（确保所有属性已定义后执行）"""
        print(f"[PathManager] Static base: {self.static_base} | Env: {self.env}")
        print(f"[PathManager] Dynamic base: {self.dynamic_base}")
        print(f"[PathManager] 后台配置: {self.backend_settings_path}")
        print(f"[PathManager] UI用户配置: {self.ui_app_settings_path}")
        print(f"[PathManager] 任务路径: {self.task_path}")  # 此时 task_path 已定义

    def get(self, path_key: str) -> str:
        """对外提供统一路径接口"""
        path_map = {
            "backend_settings": self.backend_settings_path,
            "ui_app_settings": self.ui_app_settings_path,
            "task_template": self.task_template_path,
            "log": self.log_path,
            "cache": self.cache_path,
            "task_configs": self.task_configs_path,
            "app_settings": self.ui_app_settings_path,
            "task_path": self.task_path,  # 对外提供 task_path
            "match_temple_debug": self.match_temple_debug_path,
            "match_ocr_debug": self.match_ocr_debug_path,
            "ocr_model": self.ocr_model_path,
        }
        return path_map.get(path_key, "")

# 全局路径单例
path_manager = PathManager()

# ------------------------------
# 配置加载逻辑（明确优先级：UI用户配置 > 后台默认配置）
# ------------------------------
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
        """从嵌套字典按路径获取值（支持如 "device.windows_app_title"）"""
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