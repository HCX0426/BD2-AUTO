from enum import Enum
from typing import Tuple, Optional

import cv2

class ScaleStrategy(Enum):
    """图像缩放策略枚举"""
    FIT = 'fit'      # 保持宽高比，适应目标区域
    STRETCH = 'stretch'  # 拉伸填充目标区域
    CROP = 'crop'    # 裁剪以适应目标区域

class MatchMethod(Enum):
    """模板匹配方法枚举"""
    SQDIFF = cv2.TM_SQDIFF
    SQDIFF_NORMED = cv2.TM_SQDIFF_NORMED
    CCORR = cv2.TM_CCORR
    CCORR_NORMED = cv2.TM_CCORR_NORMED
    CCOEFF = cv2.TM_CCOEFF
    CCOEFF_NORMED = cv2.TM_CCOEFF_NORMED

# 默认配置
DEFAULT_RESOLUTION = (1920, 1080)
DEFAULT_THRESHOLD = 0.8
DEFAULT_SCALE_STRATEGY = ScaleStrategy.FIT
DEFAULT_MATCH_METHOD = MatchMethod.CCOEFF_NORMED
MAX_WORKERS = 4