from enum import Enum
import os

from auto_control.config.auto_config import PROJECT_ROOT

# 路径配置
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc', 'images')  # 默认模板路径
AUTO_LOAD_TEMPLATES = True  # 是否自动加载模板
TEMPLATE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp')  # 支持的图片格式

# 性能配置

DEFAULT_THRESHOLD = 0.8
MAX_WORKERS = 4