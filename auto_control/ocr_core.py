from abc import ABC, abstractmethod
from typing import Dict, List, Optional

import cv2
import numpy as np

from .config import (PREPROCESS_CONFIG, convert_lang_code,
                     get_default_languages, get_engine_config,
                     validate_lang_combination)


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
    def recognize_text(self, image: np.ndarray, lang: str) -> str:
        """仅识别文本内容"""
        pass

    @abstractmethod
    def detect_and_recognize(self, image: np.ndarray, lang: str) -> List[Dict]:
        """同时检测和识别文本"""
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


class EasyOCRWrapper(BaseOCR):
    def __init__(self, logger=None):
        """
        EasyOCR实现（封装EasyOCR库）
        :param logger: 日志实例
        """
        super().__init__(logger=logger)
        
        # 延迟导入easyocr
        import easyocr
        
        # 加载引擎配置
        config = get_engine_config('easyocr')
        self._use_gpu = config['gpu']
        self.timeout = config['timeout']

        # 初始化默认语言
        default_langs = get_default_languages('easyocr').split('+')
        self._lang_list = self._convert_lang_param(default_langs)
        self._current_lang = '+'.join(default_langs)

        # 创建EasyOCR Reader实例
        self.reader = easyocr.Reader(
            lang_list=self._lang_list,
            gpu=self._use_gpu,
            model_storage_directory=config.get('model_storage'),
            download_enabled=True  # 允许自动下载缺失的模型
        )

        self.logger.debug(
            f"EasyOCR实例初始化完成 | "
            f"默认语言: {self._current_lang} | "
            f"GPU加速: {'启用' if self._use_gpu else '禁用'} | "
            f"模型目录: {config.get('model_storage', '默认目录')}"
        )

    def _convert_lang_param(self, langs: List[str]) -> List[str]:
        """将语言参数转换为EasyOCR支持的格式"""
        # 验证语言组合合法性
        validated_langs = validate_lang_combination(langs, 'easyocr')
        # 转换语言代码
        converted_langs = [convert_lang_code(lang, 'easyocr') for lang in validated_langs]
        
        self.logger.debug(f"语言参数转换 | 原始: {langs} → 转换后: {converted_langs}")
        return converted_langs

    def _check_gpu_available(self) -> bool:
        """检测GPU是否可用（依赖PyTorch）"""
        try:
            import torch
            available = torch.cuda.is_available()
            self.logger.debug(f"GPU可用性检测 | 可用: {available} | 设备数: {torch.cuda.device_count()}")
            return available
        except ImportError:
            self.logger.warning("未安装PyTorch，无法使用GPU加速")
            return False

    def detect_text(self, image: np.ndarray, lang: str) -> List[Dict]:
        """检测文本位置及内容"""
        try:
            # 切换语言（如果与当前语言不同）
            if lang != self._current_lang:
                self._current_lang = lang
                self._lang_list = self._convert_lang_param(lang.split('+'))
                self.logger.info(f"切换OCR语言: {lang}")

            # EasyOCR需要RGB格式图像
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            self.logger.debug(
                f"开始文本检测 | 语言: {lang} | 图像尺寸: {image.shape[:2]} | "
                f"GPU加速: {'启用' if self._use_gpu else '禁用'}"
            )

            # 调用EasyOCR识别（detail=1返回详细结果）
            raw_results = self.reader.readtext(
                image_rgb,
                detail=1,
                paragraph=False,  # 不合并为段落
                text_threshold=0.7,  # 文本置信度阈值
                batch_size=1
            )

            # 格式化结果（统一输出格式）
            formatted_results = []
            for result in raw_results:
                bbox, text, confidence = result[:3]  # 前3个元素为边界框、文本、置信度
                
                # 从多边形边界框转换为矩形边界框
                x_coords = [int(point[0]) for point in bbox]
                y_coords = [int(point[1]) for point in bbox]
                x = min(x_coords)
                y = min(y_coords)
                w = max(x_coords) - x
                h = max(y_coords) - y

                formatted_results.append({
                    'text': text.strip(),
                    'bbox': (x, y, w, h),
                    'confidence': float(confidence)
                })

            self.logger.info(f"文本检测完成 | 有效结果数量: {len(formatted_results)}")
            return formatted_results

        except Exception as e:
            self.logger.warning(f"EasyOCR文本检测失败: {str(e)}", exc_info=True)
            return []

    def recognize_text(self, image: np.ndarray, lang: str) -> str:
        """仅识别文本内容（返回纯文本字符串）"""
        try:
            # 复用detect_text获取结果，再提取文本
            detect_results = self.detect_text(image, lang)
            # 合并所有文本（按顺序）
            result_text = "\n".join([item['text'] for item in detect_results])

            self.logger.info(f"文本识别完成 | 识别长度: {len(result_text)} 字符")
            return result_text

        except Exception as e:
            self.logger.warning(f"EasyOCR文本识别失败: {str(e)}", exc_info=True)
            return ""

    def detect_and_recognize(self, image: np.ndarray, lang: str) -> List[Dict]:
        """同时检测和识别文本（复用detect_text方法）"""
        self.logger.debug("调用detect_and_recognize（复用detect_text逻辑）")
        return self.detect_text(image, lang)

    def batch_process(self, images: List[np.ndarray], lang: str) -> List[List[Dict]]:
        """批量处理多张图像（使用EasyOCR的批量接口）"""
        try:
            # 切换语言（如果需要）
            if lang != self._current_lang:
                self._current_lang = lang
                self._lang_list = self._convert_lang_param(lang.split('+'))
                self.logger.info(f"批量处理语言切换: {lang}")

            self.logger.info(f"开始批量处理 | 图像总数: {len(images)} | 语言: {lang}")

            # 转换所有图像为RGB格式
            images_rgb = [cv2.cvtColor(img, cv2.COLOR_BGR2RGB) for img in images]

            # 使用EasyOCR的批量接口（效率更高）
            raw_batch_results = self.reader.readtext_batched(
                images_rgb,
                detail=1,
                paragraph=False,
                batch_size=len(images)  # 批量大小等于图像数量
            )

            # 格式化批量结果
            formatted_batch_results = []
            for idx, raw_results in enumerate(raw_batch_results, 1):
                formatted = []
                for result in raw_results:
                    bbox, text, confidence = result[:3]
                    x_coords = [int(point[0]) for point in bbox]
                    y_coords = [int(point[1]) for point in bbox]
                    x = min(x_coords)
                    y = min(y_coords)
                    w = max(x_coords) - x
                    h = max(y_coords) - y

                    formatted.append({
                        'text': text.strip(),
                        'bbox': (x, y, w, h),
                        'confidence': float(confidence)
                    })
                formatted_batch_results.append(formatted)
                self.logger.debug(f"批量图像 {idx}/{len(images)} 处理完成 | 结果数: {len(formatted)}")

            self.logger.info("批量处理全部完成")
            return formatted_batch_results

        except Exception as e:
            self.logger.error(f"EasyOCR批量处理失败: {str(e)}", exc_info=True)
            return []