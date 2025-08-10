from enum import Enum
import os

from auto_control.config.auto_config import PROJECT_ROOT

# 基础配置
class ScaleStrategy(Enum):
    FIT = 'fit'
    STRETCH = 'stretch'
    CROP = 'crop'

class MatchMethod(Enum):
    AIRTEST = 'airtest'

# 路径配置

TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc', 'images') # 默认模板路径
AUTO_LOAD_TEMPLATES = True  # 是否自动加载模板
TEMPLATE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp')  # 支持的图片格式

# ROI配置 (可选)
TEMPLATE_ROI_CONFIG = {
    # 'template_name': (x1, y1, x2, y2)  # 0-1范围
    'button_start': (0.4, 0.8, 0.6, 0.9),
    'button_exit': (0.8, 0.05, 0.95, 0.15)
}

# 性能配置
DEFAULT_RESOLUTION = (1920, 1080)
DEFAULT_THRESHOLD = 0.8
DEFAULT_SCALE_STRATEGY = ScaleStrategy.FIT
DEFAULT_MATCH_METHOD = MatchMethod.AIRTEST
MAX_WORKERS = 4