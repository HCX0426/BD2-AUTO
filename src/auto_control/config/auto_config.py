"""自动化框架全局配置"""

from src.core.path_manager import config

# OCR与设备相关
DEFAULT_OCR_ENGINE = config.get("framework.default_ocr_engine", "easyocr")  # 默认值兜底
DEFAULT_DEVICE_URI = config.get("framework.default_device_uri", "Windows:///?title_re=.*BrownDust.*")

# 超时与延迟相关
DEFAULT_TASK_TIMEOUT = config.get("framework.default_task_timeout", 300)
DEFAULT_TEXT_FUZZY_MATCH = config.get("framework.default_text_fuzzy_match", True)
DEFAULT_WINDOW_OPERATION_DELAY = config.get("framework.default_window_operation_delay", 0.0)
DEFAULT_SCREENSHOT_DELAY = config.get("framework.default_screenshot_delay", 0.0)
DEFAULT_SCREENSHOT_CACHE_EXPIRE = config.get("framework.default_screenshot_cache_expire", 0.5)  # 截图缓存过期时间（秒）
DEFAULT_CHECK_ELEMENT_DELAY = config.get("framework.default_check_element_delay", 0.0)
DEFAULT_CLICK_DELAY = config.get("framework.default_click_delay", 0.0)
DEFAULT_KEY_DURATION = config.get("framework.default_key_duration", 0.1)

# 分辨率与路径相关
DEFAULT_BASE_RESOLUTION = config.get("framework.default_base_resolution", (1920, 1080))
TEMPLATE_EXTENSIONS = tuple(config.get("framework.template_extensions", (".png", ".jpg", ".jpeg", ".bmp")))
