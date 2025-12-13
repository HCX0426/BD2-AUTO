from abc import ABC, abstractmethod
from typing import Dict, List

import numpy as np


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
        """检查GPU是否可用"""
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
            self.logger.info("GPU加速不可用")