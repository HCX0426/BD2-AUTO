from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

from .config.control__config import (PREPROCESS_CONFIG, convert_lang_code,
                                     get_default_languages, get_engine_config,
                                     validate_lang_combination)


class BaseOCR(ABC):
    def __init__(self):
        self._use_gpu = False

    @abstractmethod
    def detect_text(self, image: np.ndarray, lang: str) -> List[Dict]:
        pass

    @abstractmethod
    def recognize_text(self, image: np.ndarray, lang: str) -> str:
        pass

    @abstractmethod
    def detect_and_recognize(self, image: np.ndarray, lang: str) -> List[Dict]:
        pass

    @abstractmethod
    def batch_process(self, images: List[np.ndarray], lang: str) -> List[List[Dict]]:
        pass

    @abstractmethod
    def _check_gpu_available(self) -> bool:
        """检测 GPU 是否可用"""
        pass

    def enable_gpu(self, enable: bool = True):
        if enable:
            if self._check_gpu_available():
                self._use_gpu = True
                print("GPU enabled")
            else:
                self._use_gpu = False
                print("GPU is not available, using CPU instead")
        else:
            self._use_gpu = False
            print("GPU disabled")

    def _preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """通用图像预处理流程"""
        cfg = PREPROCESS_CONFIG
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # 降噪
        denoised = cv2.fastNlMeansDenoising(
            gray,
            h=cfg['denoise']['h']
        )

        # 对比度增强
        clahe = cv2.createCLAHE(
            clipLimit=cfg['clahe']['clip_limit'],
            tileGridSize=cfg['clahe']['tile_size']
        )
        enhanced = clahe.apply(denoised)

        # 二值化
        _, binary = cv2.threshold(
            enhanced, 0, 255,
            cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )

        return binary


class TesseractOCR(BaseOCR):
    def __init__(self, tesseract_path: Optional[str] = None):
        super().__init__()
        import pytesseract
        self.pytesseract = pytesseract
        if tesseract_path:
            self.pytesseract.pytesseract.tesseract_cmd = tesseract_path

        config = get_engine_config('tesseract')
        self._use_gpu = config['gpu']
        self.timeout = config['timeout']

    def _check_gpu_available(self) -> bool:
        # Tesseract 不直接支持 GPU，总是返回 False
        return False

    def detect_text(self, image, lang):
        processed = self._preprocess_image(image)
        lang = convert_lang_code(lang, 'tesseract')

        data = self.pytesseract.image_to_data(
            processed,
            output_type=self.pytesseract.Output.DICT,
            lang=lang,
            timeout=self.timeout
        )

        results = []
        for i, text in enumerate(data['text']):
            if int(data['conf'][i]) > 60 and text.strip():
                results.append({
                    'text': text,
                    'bbox': (
                        data['left'][i],
                        data['top'][i],
                        data['width'][i],
                        data['height'][i]
                    ),
                    'confidence': float(data['conf'][i])
                })
        return results

    def recognize_text(self, image, lang):
        processed = self._preprocess_image(image)
        lang = convert_lang_code(lang, 'tesseract')
        return self.pytesseract.image_to_string(
            processed,
            lang=lang,
            timeout=self.timeout
        )

    def detect_and_recognize(self, image, lang):
        return self.detect_text(image, lang)

    def batch_process(self, images, lang):
        return [self.detect_and_recognize(img, lang) for img in images]


class EasyOCRWrapper(BaseOCR):
    def __init__(self):
        super().__init__()
        import easyocr
        config = get_engine_config('easyocr')
        self._use_gpu = config['gpu']
        self.timeout = config['timeout']

        # 获取默认语言并初始化Reader
        default_langs = get_default_languages('easyocr').split('+')
        self._lang_list = self._convert_lang_param(default_langs)
        self._current_lang = '+'.join(default_langs)

        # 新版EasyOCR参数
        self.reader = easyocr.Reader(
            lang_list=self._lang_list,
            gpu=self._use_gpu,
            model_storage_directory=config.get('model_storage'),
            download_enabled=True  # 允许自动下载模型
        )

    def _convert_lang_param(self, langs: List[str]) -> List[str]:
        """转换语言参数为EasyOCR格式"""
        validated_langs = validate_lang_combination(langs, 'easyocr')
        return [convert_lang_code(l, 'easyocr') for l in validated_langs]

    def _check_gpu_available(self) -> bool:
        import torch
        return torch.cuda.is_available()

    def detect_text(self, image, lang):
        # 检查语言是否变化，新版可能支持动态切换
        if lang != self._current_lang:
            self._current_lang = lang
            self._lang_list = self._convert_lang_param(lang.split('+'))

        # 新版EasyOCR可以直接在readtext中指定语言
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self.reader.readtext(
            image_rgb,
            detail=1,
            paragraph=False,
            text_threshold=0.7,  # 可调整的阈值
            batch_size=1
        )

        formatted = []
        for item in results:
            bbox, text, confidence = item[:3]  # 新版可能返回4个值
            x_coords = [int(p[0]) for p in bbox]
            y_coords = [int(p[1]) for p in bbox]
            x, y = min(x_coords), min(y_coords)
            w, h = max(x_coords) - x, max(y_coords) - y
            formatted.append({
                'text': text,
                'bbox': (x, y, w, h),
                'confidence': float(confidence)
            })
        return formatted

    def recognize_text(self, image, lang):
        results = self.detect_text(image, lang)
        return "\n".join([r['text'] for r in results])

    def detect_and_recognize(self, image, lang):
        return self.detect_text(image, lang)

    def batch_process(self, images, lang):
        # 新版EasyOCR支持批量处理
        if lang != self._current_lang:
            self._current_lang = lang
            self._lang_list = self._convert_lang_param(lang.split('+'))

        image_rgbs = [cv2.cvtColor(img, cv2.COLOR_BGR2RGB) for img in images]

        # 使用batch_size参数提高效率
        batch_results = self.reader.readtext_batched(
            image_rgbs,
            detail=1,
            paragraph=False,
            batch_size=len(images)
        )
        formatted_results = []
        for results in batch_results:
            formatted = []
            for item in results:
                bbox, text, confidence = item[:3]
                x_coords = [int(p[0]) for p in bbox]
                y_coords = [int(p[1]) for p in bbox]
                x, y = min(x_coords), min(y_coords)
                w, h = max(x_coords) - x, max(y_coords) - y
                formatted.append({
                    'text': text,
                    'bbox': (x, y, w, h),
                    'confidence': float(confidence)
                })
            formatted_results.append(formatted)
        return formatted_results
