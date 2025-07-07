from abc import ABC, abstractmethod

import cv2
import numpy as np


class BaseOCR(ABC):
    @abstractmethod
    def detect_text(self, image, lang='eng'):
        """检测图像中的文本位置"""
        pass

    @abstractmethod
    def recognize_text(self, image, lang='eng'):
        """识别图像中的文本内容"""
        pass

    @abstractmethod
    def detect_and_recognize(self, image, lang='eng'):
        """检测并识别图像中的文本"""
        pass


class TesseractOCR(BaseOCR):
    def __init__(self, tesseract_path=None):
        try:
            import pytesseract
            self.pytesseract = pytesseract

            if tesseract_path:
                self.pytesseract.pytesseract.tesseract_cmd = tesseract_path
        except ImportError:
            raise ImportError("请安装pytesseract: pip install pytesseract")

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
    def __init__(self, languages=['en']):
        try:
            import easyocr
            self.reader = easyocr.Reader(languages)
        except ImportError:
            raise ImportError("请安装easyocr: pip install easyocr")

    def detect_text(self, image, lang='en'):
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

    def recognize_text(self, image, lang='en'):
        """识别图像中的文本"""
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self.reader.readtext(image_rgb)
        return "\n".join([result[1] for result in results])

    def detect_and_recognize(self, image, lang='en'):
        """同时检测位置和识别文本"""
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self.reader.readtext(image_rgb)

        formatted = []
        for bbox, text, confidence in results:
            (top_left, top_right, bottom_right, bottom_left) = bbox
            x_min = int(min([p[0] for p in bbox]))
            y_min = int(min([p[1] for p in bbox]))
            x_max = int(max([p[0] for p in bbox]))
            y_max = int(max([p[1] for p in bbox]))

            formatted.append({
                'text': text,
                'bbox': (x_min, y_min, x_max - x_min, y_max - y_min),
                'confidence': confidence
            })

        return formatted


class OCRProcessor:
    def __init__(self, engine='tesseract', **kwargs):
        """
        :param engine: 可选 'tesseract' 或 'easyocr'
        :param kwargs: 引擎特定参数
        """
        if engine == 'tesseract':
            self.engine = TesseractOCR(**kwargs)
        elif engine == 'easyocr':
            self.engine = EasyOCRWrapper(**kwargs)
        else:
            raise ValueError(f"不支持的OCR引擎: {engine}")

    def detect_text(self, image, lang='en'):
        return self.engine.detect_text(image, lang)

    def recognize_text(self, image, lang='en'):
        return self.engine.recognize_text(image, lang)

    def detect_and_recognize(self, image, lang='en'):
        return self.engine.detect_and_recognize(image, lang)

    def find_text_position(self, image, target_text, lang='en'):
        """
        在图像中查找特定文本的位置
        :param target_text: 要查找的文本
        :return: (x, y, w, h) 或 None
        """
        results = self.detect_and_recognize(image, lang)
        if isinstance(self.engine, TesseractOCR):
            details = results['details']
            n_boxes = len(details['text'])
            for i in range(n_boxes):
                if target_text.lower() in details['text'][i].lower():
                    return (
                        details['left'][i],
                        details['top'][i],
                        details['width'][i],
                        details['height'][i]
                    )
        elif isinstance(self.engine, EasyOCRWrapper):
            for item in results:
                if target_text.lower() in item['text'].lower():
                    return item['bbox']
        return None
