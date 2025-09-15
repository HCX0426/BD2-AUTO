import os

from auto_control.config.auto_config import PROJECT_ROOT

# 路径配置
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc', 'images')  # 默认模板路径
TEMPLATE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp')  # 支持的图片格式