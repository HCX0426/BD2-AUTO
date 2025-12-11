import os
import sys
from environment import get_current_env  # 从 environment.py 获取 ENV（dev/prod）

class PathManager:
    def __init__(self):
        self.env = get_current_env()  # 结果："dev" 或 "prod"
        self._init_base_paths()
        self._init_all_paths()

    def _init_base_paths(self):
        """初始化基础路径：区分开发/打包环境"""
        # 1. 判断是否为 PyInstaller 打包环境（存在 _MEIPASS）
        self.is_packaged = getattr(sys, 'frozen', False)
        self.meipass_path = sys._MEIPASS if self.is_packaged else None

        # 2. 静态资源基础路径（开发时用项目根目录，打包后用 _MEIPASS）
        if self.is_packaged:
            # 打包后：静态资源（config/prod、templates）从 _MEIPASS 读取
            self.static_base = self.meipass_path
        else:
            # 开发时：静态资源从项目根目录读取
            # 修正路径计算逻辑：从当前文件向上两级到达 src 目录，再向上一级到达项目根目录
            current_dir = os.path.dirname(os.path.abspath(__file__))  # src/core
            src_dir = os.path.dirname(current_dir)  # src
            self.static_base = os.path.dirname(src_dir)  # 项目根目录 (BD2-AUTO)

        # 3. 动态数据基础路径（用户侧固定目录，不随打包/移动变化）
        if self.env == "prod":
            # 生产环境（用户侧）：动态数据放在用户目录下（避免权限问题）
            # self.dynamic_base = os.path.join(os.path.expanduser("~"), "BD2-AUTO", "runtime", "prod")
            self.dynamic_base = os.path.join(self.static_base, "runtime", "prod")
        else:
            # 开发环境：动态数据放在项目内 runtime/dev
            self.dynamic_base = os.path.join(self.static_base, "runtime", "dev")

        # 确保动态目录存在（首次运行自动创建）
        os.makedirs(self.dynamic_base, exist_ok=True)
        print(f"Static base path: {self.static_base}")
        print(f"Dynamic base path: {self.dynamic_base}")

    def _init_all_paths(self):
        """统一定义所有路径（静态+动态）"""
        # 静态资源路径（打包时嵌入，只读）
        self.config_path = os.path.join(self.static_base, "config", self.env)  # 开发读 config/dev，打包读 config/prod
        self.task_template_path = os.path.join(self.static_base, "src", "auto_tasks", "pc", "templates")  # 任务模板图片
        self.task_path = os.path.join(self.static_base, "src", "auto_tasks", "pc")  # 任务目录

        # 动态数据路径（可写，用户侧保留）
        self.log_path = os.path.join(self.dynamic_base, "logs")
        self.cache_path = os.path.join(self.dynamic_base, "cache")
        self.user_config_path = os.path.join(self.dynamic_base, "user_config.json")  # 用户自定义配置（覆盖默认）
        self.task_configs_path = os.path.join(self.dynamic_base, "task_configs.json")  # 任务配置文件（覆盖默认）
        self.app_settings_path = os.path.join(self.dynamic_base, "app_settings.json")  # 应用设置文件（覆盖默认）
        self.match_temple_debug_path = os.path.join(self.dynamic_base, "temple_debug")  # 匹配模板调试文件（覆盖默认）
        self.match_ocr_debug_path = os.path.join(self.dynamic_base, "ocr_debug")  # 匹配OCR调试文件（覆盖默认）

        # 确保动态子目录存在
        for path in [self.log_path, self.cache_path]:
            os.makedirs(path, exist_ok=True)
            
        # 打印关键路径用于调试
        print(f"Task path: {self.task_path}")

    def get(self, path_key: str) -> str:
        """对外提供统一路径获取接口，避免硬编码"""
        path_map = {
            "config": self.config_path,
            "task_template": self.task_template_path,
            "log": self.log_path,
            "cache": self.cache_path,
            "user_config": self.user_config_path,
            "task_configs": self.task_configs_path,
            "app_settings": self.app_settings_path,
            "task": self.task_path,
            "match_temple_debug": self.match_temple_debug_path,
            "match_ocr_debug": self.match_ocr_debug_path,
        }
        return path_map.get(path_key, "")

# 全局单例，全项目统一调用
path_manager = PathManager()