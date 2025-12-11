from abc import ABC, abstractmethod
from typing import Dict, List
import cv2
import numpy as np

from src.auto_control.config.ocr_config import PREPROCESS_CONFIG

class BaseOCR(ABC):
    def __init__(self, logger=None):
        """
        OCR基类初始化
        :param logger: 日志实例（从上层传递）
        """
        self._use_gpu = False
        # 初始化日志（支持降级方案）
        self.logger = logger if logger else self._create_default_logger()

    def _create_default_logger(self):
        """无日志实例时的降级实现"""
        class DefaultLogger:
            @staticmethod
            def debug(msg):
                print(f"[DEBUG] BaseOCR: {msg}")
            
            @staticmethod
            def info(msg):
                print(f"[INFO] BaseOCR: {msg}")
            
            @staticmethod
            def warning(msg):
                print(f"[WARNING] BaseOCR: {msg}")
            
            @staticmethod
            def error(msg, exc_info=False):
                print(f"[ERROR] BaseOCR: {msg}")
        
        return DefaultLogger()

    @abstractmethod
    def detect_text(self, image: np.ndarray, lang: str) -> List[Dict]:
        """检测文本位置及内容"""
        pass

    @abstractmethod
    def batch_process(self, images: List[np.ndarray], lang: str) -> List[List[Dict]]:
        """批量处理多张图像"""
        pass

    @abstractmethod
    def _check_gpu_available(self) -> bool:
        """检测GPU是否可用"""
        pass

    def enable_gpu(self, enable: bool = True):
        """启用/禁用GPU加速"""
        if enable:
            if self._check_gpu_available():
                self._use_gpu = True
                self.logger.info("GPU加速已启用")
            else:
                self._use_gpu = False
                self.logger.warning("GPU不可用，将使用CPU进行处理")
        else:
            self._use_gpu = False
            self.logger.info("GPU加速已禁用")

    def _preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """通用图像预处理流程（降噪、增强、二值化）"""
        cfg = PREPROCESS_CONFIG
        
        # 转为灰度图
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # 1. 降噪
        denoised = cv2.fastNlMeansDenoising(gray, h=cfg['denoise']['h'])
        
        # 2. 对比度增强
        clahe = cv2.createCLAHE(
            clipLimit=cfg['clahe']['clip_limit'],
            tileGridSize=cfg['clahe']['tile_size']
        )
        enhanced = clahe.apply(denoised)
        
        # 3. 二值化（OTSU自动阈值）
        _, binary = cv2.threshold(
            enhanced, 0, 255,
            cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )

        self.logger.debug(f"图像预处理完成 | 原始尺寸: {image.shape[:2]} | 处理后尺寸: {binary.shape[:2]}")
        return binary