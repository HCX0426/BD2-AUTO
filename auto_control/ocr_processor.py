from typing import List, Dict, Optional, Tuple, Union
import numpy as np
from .ocr_core import TesseractOCR, EasyOCRWrapper
from .config import get_default_languages
from airtest.core.helper import logwrap

class OCRProcessor:
    def __init__(self, engine: str = 'easyocr', **kwargs):
        """
        初始化OCR处理器
        :param engine: 可选 'tesseract' 或 'easyocr' (默认easyocr)
        :param kwargs: 引擎特定参数
            - tesseract_path: Tesseract可执行文件路径(仅Tesseract需要)
            - languages: 指定语言列表(仅EasyOCR有效)
        """
        self.engine_type = engine.lower()
        if self.engine_type not in ['tesseract', 'easyocr']:
            raise ValueError(f"Unsupported OCR engine: {engine}")
        
        # 处理语言参数
        self._default_lang = kwargs.pop('languages', None) or get_default_languages(self.engine_type)
        self.engine = self._init_engine(**kwargs)
        print(f"Initialized {self.engine_type.upper()} OCR processor (default lang: {self._default_lang})")

    def _init_engine(self, **kwargs):
        """初始化指定的OCR引擎"""
        if self.engine_type == 'tesseract':
            return TesseractOCR(kwargs.get('tesseract_path'))
        else:
            # 对于EasyOCR，通过构造函数参数传递语言
            return EasyOCRWrapper()

    def detect_text(self, 
                   image: np.ndarray, 
                   lang: Optional[str] = None) -> List[Dict[str, Union[str, Tuple[int, int, int, int], float]]]:
        """
        检测文本位置(可选语言参数)
        :param image: 输入图像(numpy数组)
        :param lang: 可选语言代码(如 'chi_sim+eng')，默认使用引擎最优配置
        :return: [{'text':..., 'bbox':(x,y,w,h), 'confidence':...}]
        """
        return self.engine.detect_text(image, lang or self._default_lang)

    def recognize_text(self, 
                      image: np.ndarray,
                      lang: Optional[str] = None) -> str:
        """
        识别图像中的文本(可选语言参数)
        :param image: 输入图像(numpy数组)
        :param lang: 可选语言代码，默认使用引擎最优配置
        :return: 识别出的文本字符串
        """
        return self.engine.recognize_text(image, lang or self._default_lang)

    def detect_and_recognize(self,
                            image: np.ndarray,
                            lang: Optional[str] = None) -> List[Dict]:
        """
        同时检测和识别文本(可选语言参数)
        :param image: 输入图像(numpy数组)
        :param lang: 可选语言代码，默认使用引擎最优配置
        :return: [{'text':..., 'bbox':(x,y,w,h), 'confidence':...}]
        """
        return self.engine.detect_and_recognize(image, lang or self._default_lang)

    def batch_process(self,
                     images: List[np.ndarray],
                     lang: Optional[str] = None) -> List[List[Dict]]:
        """
        批量处理多张图像(可选语言参数)
        :param images: 图像列表
        :param lang: 可选语言代码，默认使用引擎最优配置
        :return: 每张图像的识别结果列表
        """
        return self.engine.batch_process(images, lang or self._default_lang)

    def enable_gpu(self, enable: bool = True):
        """启用/禁用GPU加速"""
        self.engine.enable_gpu(enable)
        print(f"GPU acceleration {'enabled' if enable else 'disabled'}")

    @logwrap
    def find_text_position(self,
                          image: np.ndarray,
                          target_text: str,
                          lang: Optional[str] = None,
                          fuzzy_match: bool = False,
                          min_confidence: float = 0.6) -> Optional[Tuple[int, int, int, int]]:
        """
        查找特定文本的位置(可选语言参数)
        :param image: 输入图像
        :param target_text: 要查找的文本
        :param lang: 可选语言代码，默认使用引擎最优配置
        :param fuzzy_match: 是否使用模糊匹配(默认False)
        :param min_confidence: 最小置信度阈值(默认0.6)
        :return: (x, y, w, h)坐标或None
        """
        results = self.detect_and_recognize(image, lang or self._default_lang)
        
        best_match = None
        highest_confidence = 0

        for item in results:
            if item['confidence'] < min_confidence:
                continue
                
            text = item['text']
            is_match = False
            
            if fuzzy_match:
                from difflib import SequenceMatcher
                ratio = SequenceMatcher(None, text, target_text).ratio()
                is_match = ratio >= 0.8
            else:
                is_match = text.strip() == target_text.strip()
            
            if is_match and item['confidence'] > highest_confidence:
                best_match = item['bbox']
                highest_confidence = item['confidence']
        
        return best_match