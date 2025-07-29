# 自动化框架全局配置
DEFAULT_BASE_RESOLUTION = (1920, 1080)  # 默认分辨率
DEFAULT_OCR_ENGINE = "easyocr"  # 默认OCR引擎

DEFAULT_DEVICE_URI = "Windows:///?title_re=BrownDust II" # 默认设备URI
DEFAULT_RESOLUTION_UPDATE = True  # 是否从设备获取分辨率
DEFAULT_TASK_TIMEOUT = 120  # 默认任务超时时间(秒)
MAX_TASK_TIMEOUT = 600      # 最大允许超时时间
DEFAULT_OCR_LANG = None  # 默认OCR语言
DEFAULT_TEXT_FUZZY_MATCH = True  # 默认使用模糊文本匹配
# DEFAULT_TEMPLATE_CONFIDENCE = 0.7  # 默认模板匹配置信度
DEFAULT_WINDOW_OPERATION_DELAY = 0.0  # 窗口操作默认延迟
DEFAULT_SCREENSHOT_DELAY = 0.0  # 截图操作默认延迟
DEFAULT_CHECK_ELEMENT_DELAY = 0.0  # 检查元素默认延迟
# DEFAULT_CUSTOM_TASK_DELAY = 0.0  # 自定义任务默认延迟
DEFAULT_CLICK_DELAY = 0.0  # 点击操作默认延迟
DEFAULT_MAX_RETRY = 1  # 默认最大重试次数
DEFAULT_RETRY_INTERVAL = 1.0  # 默认重试间隔(秒)
DEFAULT_KEY_DURATION = 0.1  # 默认按键持续时间(秒)

DEFAULT_TEXT_MIN_CONFIDENCE = 0.7  # 文本匹配最小置信度阈值