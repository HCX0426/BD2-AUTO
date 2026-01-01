import json
import os
import sys


class PathManager:
    def __init__(self):
        self.env = self._get_env()  # 自动判断 dev/prod
        self._init_base_paths()  # 初始化基础路径（static_base/dynamic_base）
        self._init_all_paths()  # 初始化所有具体路径（包括 task_path）
        self._print_path_info()  # 最后打印路径信息（确保所有属性已定义）

    def _get_env(self) -> str:
        """自动判断环境：打包后=prod，开发环境=dev"""
        if getattr(sys, "frozen", False):
            return "prod"
        return "dev"

    def _init_base_paths(self):
        """初始化基础路径（static_base/dynamic_base）"""
        self.is_packaged = getattr(sys, "frozen", False)
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

    def _init_all_paths(self):
        """统一定义所有路径（包括 task_path）"""
        # 1. 后台配置文件（settings.json）：项目核心默认配置（不暴露给UI）
        self.backend_settings_path = os.path.join(self.static_base, "config", self.env, "settings.json")

        # 2. UI用户配置文件（app_settings.json）：用户通过UI修改的配置（持久化）
        self.ui_app_settings_path = os.path.join(self.dynamic_base, "app_settings.json")

        # 3. ROI配置文件（rois.json）：自动化任务中使用的ROI区域配置
        self.rois_config_path = os.path.join(self.static_base, "config", self.env, "rois.json")

        # 3. 其他原有路径
        self.task_template_path = os.path.join(self.static_base, "src", "auto_tasks", "templates")
        self.task_path = os.path.join(self.static_base, "src", "auto_tasks", "tasks")  # 定义 task_path
        self.log_path = os.path.join(self.dynamic_base, "logs")
        self.cache_path = os.path.join(self.dynamic_base, "cache")
        self.task_configs_path = os.path.join(self.dynamic_base, "task_configs.json")
        self.match_temple_debug_path = os.path.join(self.dynamic_base, "temple_debug")
        self.match_ocr_debug_path = os.path.join(self.dynamic_base, "ocr_debug")
        self.gui_log_path = os.path.join(self.dynamic_base, "gui_log")  # GUI日志目录

        self.ocr_model_path = os.path.join(self.dynamic_base, "ocr_models")  # OCR模型存储目录

        # 收集所有需要创建的目录路径
        dirs_to_create = [
            os.path.dirname(self.ui_app_settings_path),
            self.log_path,
            self.cache_path,
            self.match_temple_debug_path,
            self.match_ocr_debug_path,
            self.ocr_model_path,
            self.gui_log_path,
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
            "rois_config": self.rois_config_path,
            "task_template": self.task_template_path,
            "log": self.log_path,
            "cache": self.cache_path,
            "task_configs": self.task_configs_path,
            "app_settings": self.ui_app_settings_path,
            "task_path": self.task_path,  # 对外提供 task_path
            "match_temple_debug": self.match_temple_debug_path,
            "match_ocr_debug": self.match_ocr_debug_path,
            "ocr_model": self.ocr_model_path,
            "gui_log": self.gui_log_path,
        }
        return path_map.get(path_key, "")


## 全局路径单例
path_manager = PathManager()
