"""
主配置文件,只负责加载配置文件,不负责处理配置文件
"""
import io
import sys
from .ocr_config import *
from .log_config import *
from .ocr_config import *
from .image_config import *
from .auto_config import *
from .st_config import *

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')