from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

# 新增全局语言配置常量
DEFAULT_LANGUAGES = 'chi_sim+chi_tra+eng+jpn'  # 默认支持的语言
SUPPORTED_LANGUAGES = {  # 各引擎支持的语言映射
    'tesseract': {
        'chi_sim': '简体中文',
        'chi_tra': '繁体中文',
        'eng': '英文',
        'jpn': '日文'
    },
    'easyocr': {
        'ch_sim': ['ch_sim'],  # 简体中文可以单独使用
        'ch_tra': ['ch_tra', 'en'],  # 繁体中文必须与英文一起使用
        'en': ['en']
    }
}


class BaseOCR(ABC):
    @abstractmethod
    def detect_text(self, image: np.ndarray, lang: str = DEFAULT_LANGUAGES) -> List[Dict[str, Union[str, Tuple[int, int, int, int], float]]]:
        pass

    @abstractmethod
    def recognize_text(self, image: np.ndarray, lang: str = DEFAULT_LANGUAGES) -> str:
        pass

    @abstractmethod
    def detect_and_recognize(self, image: np.ndarray, lang: str = DEFAULT_LANGUAGES) -> List[Dict[str, Union[str, Tuple[int, int, int, int], float]]]:
        pass


class TesseractOCR(BaseOCR):
    def __init__(self, tesseract_path: Optional[str] = None):
        try:
            import pytesseract
            self.pytesseract = pytesseract
            if tesseract_path:
                self.pytesseract.pytesseract.tesseract_cmd = tesseract_path
            print("TesseractOCR初始化成功")
        except ImportError:
            print("请安装pytesseract: pip install pytesseract")
            raise

    def preprocess_image(self, image):
        """预处理图像以提高OCR准确率"""
        # 转换为灰度图
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 应用自适应阈值
        processed = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
        return processed

    def detect_text(self, image, lang='eng'):
        """检测文本位置"""
        processed = self.preprocess_image(image)

        # 使用Tesseract获取文本位置信息
        data = self.pytesseract.image_to_data(
            processed,
            output_type=self.pytesseract.Output.DICT,
            lang=lang
        )

        # 提取文本位置
        results = []
        n_boxes = len(data['text'])
        for i in range(n_boxes):
            if int(data['conf'][i]) > 60:  # 置信度阈值
                text = data['text'][i]
                if text.strip():
                    (x, y, w, h) = (
                        data['left'][i],
                        data['top'][i],
                        data['width'][i],
                        data['height'][i]
                    )
                    results.append({
                        'text': text,
                        'bbox': (x, y, w, h),
                        'confidence': float(data['conf'][i])
                    })
        return results

    def recognize_text(self, image, lang='eng'):
        """识别图像中的文本"""
        processed = self.preprocess_image(image)
        return self.pytesseract.image_to_string(processed, lang=lang)

    def detect_and_recognize(self, image, lang='eng'):
        """同时检测位置和识别文本"""
        processed = self.preprocess_image(image)
        data = self.pytesseract.image_to_data(
            processed,
            output_type=self.pytesseract.Output.DICT,
            lang=lang
        )

        # 返回结构化结果
        return {
            'text': self.pytesseract.image_to_string(processed, lang=lang),
            'details': data
        }


class EasyOCRWrapper(BaseOCR):
    def __init__(self, languages: List[str] = ['ch_sim', 'en']):  # 默认只使用简体中文和英文
        try:
            import easyocr

            # 根据语言自动处理组合
            processed_langs = []
            for lang in languages:
                if lang in SUPPORTED_LANGUAGES['easyocr']:
                    processed_langs.extend(
                        SUPPORTED_LANGUAGES['easyocr'][lang])
            # 去重
            processed_langs = list(dict.fromkeys(processed_langs))

            self.reader = easyocr.Reader(processed_langs)
            print(f"EasyOCR初始化完成，使用语言: {processed_langs}")
        except ImportError:
            print("请安装easyocr: pip install easyocr")
            raise

    def detect_text(self, image, lang=DEFAULT_LANGUAGES):  # 使用全局默认语言
        """检测文本位置"""
        # 转换图像格式
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # 检测文本
        results = self.reader.detect(image_rgb)

        # 格式化结果
        formatted = []
        for i, bbox in enumerate(results[0][0]):
            x_min, y_min = map(int, bbox[0])
            x_max, y_max = map(int, bbox[2])
            formatted.append({
                'bbox': (x_min, y_min, x_max - x_min, y_max - y_min)
            })
        return formatted

    def recognize_text(self, image, lang=DEFAULT_LANGUAGES):  # 使用全局默认语言
        """识别图像中的文本"""
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self.reader.readtext(image_rgb)
        return "\n".join([result[1] for result in results])

    def detect_and_recognize(self, image, lang=DEFAULT_LANGUAGES):  # 使用全局默认语言
        """同时检测位置和识别文本"""
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self.reader.readtext(image_rgb)

        # 统一返回格式
        formatted = []
        for item in results:
            if len(item) == 3:  # (bbox, text, confidence)
                bbox, text, confidence = item
                (x_min, y_min) = map(int, map(min, zip(*bbox)))
                (x_max, y_max) = map(int, map(max, zip(*bbox)))
                formatted.append({
                    'text': text,
                    'bbox': (x_min, y_min, x_max - x_min, y_max - y_min),
                    'confidence': confidence
                })
        return formatted


class OCRProcessor:
    def __init__(self, engine: str = 'tesseract', **kwargs):
        self.engine_map = {
            'tesseract': TesseractOCR,
            'easyocr': EasyOCRWrapper
        }

        if engine not in self.engine_map:
            raise ValueError(f"不支持的OCR引擎: {engine}")

        try:
            self.engine = self.engine_map[engine](**kwargs)
            print(f"OCR处理器初始化完成，使用引擎: {engine}")
            print(f"支持的语言: {SUPPORTED_LANGUAGES.get(engine, {})}")
        except Exception as e:
            print(f"OCR引擎初始化失败: {str(e)}")
            raise

    def detect_text(self, image, lang=DEFAULT_LANGUAGES):
        return self.engine.detect_text(image, lang)

    def recognize_text(self, image, lang=DEFAULT_LANGUAGES):
        return self.engine.recognize_text(image, lang)

    def detect_and_recognize(self, image, lang=DEFAULT_LANGUAGES):
        return self.engine.detect_and_recognize(image, lang)

    def find_text_position(self, image, target_text, lang=DEFAULT_LANGUAGES,
                           fuzzy_match=False, regex=False):
        results = self.engine.detect_and_recognize(image, lang)

        # 修改结果处理逻辑
        found_results = []
        for item in results:
            if isinstance(item, tuple) and len(item) == 3:
                bbox, text, prob = item
            elif isinstance(item, dict):
                bbox = item.get('bbox')
                text = item.get('text')
                prob = item.get('confidence', 0)
            else:
                continue

            if fuzzy_match:
                if self._fuzzy_compare(text, target_text):
                    found_results.append(self._bbox_to_rect(bbox))
            elif regex:
                import re
                if re.search(target_text, text):
                    found_results.append(self._bbox_to_rect(bbox))
            else:
                if text.strip() == target_text.strip():
                    found_results.append(self._bbox_to_rect(bbox))

        return found_results[0] if found_results else None

    def _fuzzy_compare(self, text1, text2, threshold=0.8):
        """模糊字符串比较"""
        from difflib import SequenceMatcher
        ratio = SequenceMatcher(None, text1, text2).ratio()
        return ratio >= threshold

    def _bbox_to_rect(self, bbox):
        """将边界框转换为(x,y,w,h)格式"""
        x_coords = [point[0] for point in bbox]
        y_coords = [point[1] for point in bbox]
        x = min(x_coords)
        y = min(y_coords)
        w = max(x_coords) - x
        h = max(y_coords) - y
        return (x, y, w, h)
