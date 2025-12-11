# 自动化框架全局配置
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__))) # 项目根目录


DEFAULT_OCR_ENGINE = "easyocr"  # 默认OCR引擎
DEFAULT_DEVICE_URI = "Windows:///?title_re=.*BrownDust.*" # 默认设备URI
DEFAULT_TASK_TIMEOUT = 300  # 默认任务超时时间(秒)
DEFAULT_TEXT_FUZZY_MATCH = True  # 默认使用模糊文本匹配
DEFAULT_WINDOW_OPERATION_DELAY = 0.0  # 窗口操作默认延迟
DEFAULT_SCREENSHOT_DELAY = 0.0  # 截图操作默认延迟
DEFAULT_CHECK_ELEMENT_DELAY = 0.0  # 检查元素默认延迟
DEFAULT_CLICK_DELAY = 0.0  # 点击操作默认延迟
DEFAULT_KEY_DURATION = 0.1  # 默认按键持续时间(秒)

DEFAULT_BASE_RESOLUTION = (1920, 1080)  # 坐标采集默认分辨率

# 路径配置
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc', 'images')  # 默认模板路径
TEMPLATE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp')  # 支持的图片格式