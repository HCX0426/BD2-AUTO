# ocr_processor.py
from typing import List, Dict, Optional, Tuple, Union
import numpy as np
from .ocr_core import TesseractOCR, EasyOCRWrapper, BaseOCR
from .config import get_default_languages
from airtest.core.helper import logwrap


class OCRProcessor:
    def __init__(self, engine: str = 'easyocr', logger=None, **kwargs):
        """
        OCR处理器封装类（统一调用不同OCR引擎）
        
        :param engine: OCR引擎类型，可选 'tesseract' 或 'easyocr'（默认easyocr）
        :param logger: 日志实例（从上层传递，如Auto类）
        :param kwargs: 引擎特定参数：
            - tesseract_path: Tesseract可执行文件路径（仅Tesseract需要）
            - languages: 自定义默认语言组合（如 'chi_sim+eng'，可选）
        """
        # 验证引擎类型
        self.engine_type = engine.lower()
        if self.engine_type not in ['tesseract', 'easyocr']:
            raise ValueError(f"不支持的OCR引擎: {engine}，仅支持 'tesseract' 和 'easyocr'")
        
        # 初始化日志系统（支持降级）
        self.logger = logger if logger else self._create_default_logger()
        
        # 处理默认语言参数（优先使用传入的languages，否则用配置默认值）
        self._default_lang = kwargs.pop('languages', None) or get_default_languages(self.engine_type)
        
        # 初始化指定的OCR引擎
        self.engine: BaseOCR = self._init_engine(**kwargs)
        
        # 初始化完成日志
        self.logger.info(
            f"OCR处理器初始化完成 | "
            f"引擎: {self.engine_type.upper()} | "
            f"默认语言: {self._default_lang} | "
            f"GPU加速: {'启用' if self.engine._use_gpu else '禁用'}"
        )

    def _create_default_logger(self):
        """无日志实例时的降级实现（使用print输出）"""
        class DefaultLogger:
            @staticmethod
            def debug(msg):
                print(f"[DEBUG] OCRProcessor: {msg}")
            
            @staticmethod
            def info(msg):
                print(f"[INFO] OCRProcessor: {msg}")
            
            @staticmethod
            def warning(msg):
                print(f"[WARNING] OCRProcessor: {msg}")
            
            @staticmethod
            def error(msg, exc_info=False):
                print(f"[ERROR] OCRProcessor: {msg}")
        
        return DefaultLogger()

    def _init_engine(self, **kwargs) -> BaseOCR:
        """根据引擎类型初始化具体OCR实例"""
        self.logger.debug(f"开始初始化{self.engine_type.upper()}引擎 | 参数: {kwargs}")
        
        if self.engine_type == 'tesseract':
            # 初始化Tesseract（支持传入可执行文件路径）
            return TesseractOCR(
                tesseract_path=kwargs.get('tesseract_path'),
                logger=self.logger  # 传递日志实例给引擎
            )
        elif self.engine_type == 'easyocr':
            # 初始化EasyOCR（参数通过配置文件读取，无需额外传入）
            return EasyOCRWrapper(logger=self.logger)  # 传递日志实例给引擎

    def detect_text(self, 
                   image: np.ndarray, 
                   lang: Optional[str] = None) -> List[Dict[str, Union[str, Tuple[int, int, int, int], float]]]:
        """
        检测图像中的文本位置及内容（返回详细边界框信息）
        
        :param image: 输入图像（numpy数组，BGR格式）
        :param lang: 语言代码（如 'chi_sim' 中文，'eng' 英文，支持组合 'chi_sim+eng'）
                     未指定时使用默认语言
        :return: 文本检测结果列表，每个元素为字典：
                 {
                     'text': 识别的文本内容,
                     'bbox': (x, y, w, h) 文本边界框（x/y为左上角坐标，w/h为宽高）,
                     'confidence': 识别置信度（0-100或0-1，取决于引擎）
                 }
        """
        # 确定目标语言（优先使用传入的lang，否则用默认值）
        target_lang = lang or self._default_lang
        
        # 输入参数校验
        if image is None or image.size == 0:
            self.logger.error("无效的输入图像（空图像或尺寸为0）")
            return []
        
        self.logger.debug(
            f"调用文本检测接口 | "
            f"引擎: {self.engine_type.upper()} | "
            f"语言: {target_lang} | "
            f"图像尺寸: {image.shape[:2]}"
        )
        
        # 调用引擎的检测方法
        results = self.engine.detect_text(image, target_lang)
        
        self.logger.debug(f"文本检测接口返回 | 有效结果数量: {len(results)}")
        return results

    def recognize_text(self, 
                      image: np.ndarray,
                      lang: Optional[str] = None) -> str:
        """
        识别图像中的文本内容（仅返回纯文本字符串，不包含位置信息）
        
        :param image: 输入图像（numpy数组，BGR格式）
        :param lang: 语言代码（未指定时使用默认语言）
        :return: 识别出的纯文本字符串（空字符串表示识别失败或无文本）
        """
        target_lang = lang or self._default_lang
        
        # 输入参数校验
        if image is None or image.size == 0:
            self.logger.error("无效的输入图像（空图像或尺寸为0）")
            return ""
        
        self.logger.debug(
            f"调用文本识别接口 | "
            f"引擎: {self.engine_type.upper()} | "
            f"语言: {target_lang} | "
            f"图像尺寸: {image.shape[:2]}"
        )
        
        # 调用引擎的识别方法
        result_text = self.engine.recognize_text(image, target_lang)
        
        # 日志记录识别结果（截断过长文本，避免日志冗余）
        log_text = result_text[:50] + "..." if len(result_text) > 50 else result_text
        self.logger.info(f"文本识别接口返回 | 文本长度: {len(result_text)} | 内容: {log_text}")
        
        return result_text

    def detect_and_recognize(self,
                            image: np.ndarray,
                            lang: Optional[str] = None) -> List[Dict]:
        """
        同时检测和识别文本（功能同detect_text，统一接口命名）
        
        :param image: 输入图像（numpy数组，BGR格式）
        :param lang: 语言代码（未指定时使用默认语言）
        :return: 文本检测与识别结果列表（同detect_text的返回格式）
        """
        target_lang = lang or self._default_lang
        self.logger.debug(f"调用检测与识别接口 | 语言: {target_lang}")
        
        results = self.engine.detect_and_recognize(image, target_lang)
        self.logger.debug(f"检测与识别接口返回 | 结果数量: {len(results)}")
        
        return results

    def batch_process(self,
                     images: List[np.ndarray],
                     lang: Optional[str] = None) -> List[List[Dict]]:
        """
        批量处理多张图像的文本检测与识别
        
        :param images: 输入图像列表（每个元素为numpy数组，BGR格式）
        :param lang: 语言代码（所有图像共用同一语言，未指定时使用默认语言）
        :return: 批量处理结果列表，每个元素为单张图像的检测结果（同detect_text格式）
        """
        target_lang = lang or self._default_lang
        
        # 输入参数校验
        if not images or any(img is None or img.size == 0 for img in images):
            self.logger.error("批量处理失败：输入图像列表为空或包含无效图像")
            return []
        
        self.logger.info(
            f"调用批量处理接口 | "
            f"引擎: {self.engine_type.upper()} | "
            f"语言: {target_lang} | "
            f"图像总数: {len(images)}"
        )
        
        # 调用引擎的批量处理方法
        batch_results = self.engine.batch_process(images, target_lang)
        
        self.logger.info(
            f"批量处理接口返回 | "
            f"成功处理: {len(batch_results)} 张 | "
            f"总结果数: {sum(len(res) for res in batch_results)}"
        )
        
        return batch_results

    def enable_gpu(self, enable: bool = True):
        """
        启用/禁用GPU加速（仅EasyOCR支持，Tesseract无GPU支持）
        
        :param enable: True=启用，False=禁用
        """
        self.logger.debug(f"{'启用' if enable else '禁用'}GPU加速")
        self.engine.enable_gpu(enable)

    @logwrap
    def find_text_position(self,
                          image: np.ndarray,
                          target_text: str,
                          lang: Optional[str] = None,
                          fuzzy_match: bool = False,
                          min_confidence: float = 0.6) -> Optional[Tuple[int, int, int, int]]:
        """
        查找特定文本在图像中的位置（返回最匹配的边界框）
        
        :param image: 输入图像（numpy数组，BGR格式）
        :param target_text: 要查找的目标文本（如 "确认"、"登录"）
        :param lang: 语言代码（未指定时使用默认语言）
        :param fuzzy_match: 是否启用模糊匹配（默认False，精确匹配）
                           启用后使用字符串相似度（≥0.8）判断匹配
        :param min_confidence: 最小置信度阈值（默认0.6，仅筛选高于此值的结果）
        :return: 目标文本的边界框 (x, y, w, h)，未找到时返回None
        """
        target_lang = lang or self._default_lang
        
        # 输入参数校验
        if image is None or image.size == 0:
            self.logger.error("查找文本位置失败：无效的输入图像")
            return None
        if not target_text.strip():
            self.logger.error("查找文本位置失败：目标文本为空")
            return None
        
        self.logger.debug(
            f"调用文本位置查找接口 | "
            f"目标文本: '{target_text}' | "
            f"语言: {target_lang} | "
            f"模糊匹配: {'是' if fuzzy_match else '否'} | "
            f"最小置信度: {min_confidence} | "
            f"图像尺寸: {image.shape[:2]}"
        )
        
        # 第一步：检测图像中的所有文本
        text_results = self.detect_and_recognize(image, target_lang)
        if not text_results:
            self.logger.warning(f"未检测到任何文本，无法查找目标 '{target_text}'")
            return None
        
        # 第二步：筛选符合条件的匹配结果
        best_match = None
        highest_confidence = 0.0  # 记录最高置信度
        
        for result in text_results:
            # 过滤低于最小置信度的结果
            current_confidence = result['confidence']
            if current_confidence < min_confidence:
                self.logger.debug(
                    f"跳过低置信度结果 | 文本: '{result['text']}' | 置信度: {current_confidence} < {min_confidence}"
                )
                continue
            
            # 判断是否匹配目标文本
            is_match = False
            result_text = result['text'].strip()
            
            if fuzzy_match:
                # 模糊匹配：计算字符串相似度（使用difflib）
                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, result_text, target_text).ratio()
                is_match = similarity >= 0.8  # 相似度≥0.8视为匹配
                self.logger.debug(
                    f"模糊匹配结果 | 文本: '{result_text}' | 目标: '{target_text}' | "
                    f"相似度: {similarity:.2f} | 匹配: {'是' if is_match else '否'}"
                )
            else:
                # 精确匹配：完全相等（忽略大小写？根据需求可调整）
                is_match = result_text == target_text.strip()
                self.logger.debug(
                    f"精确匹配结果 | 文本: '{result_text}' | 目标: '{target_text}' | 匹配: {'是' if is_match else '否'}"
                )
            
            # 找到更优匹配（置信度更高）
            if is_match and current_confidence > highest_confidence:
                highest_confidence = current_confidence
                best_match = result['bbox']
                self.logger.debug(
                    f"更新最佳匹配 | 置信度: {highest_confidence} | 位置: {best_match}"
                )
        
        # 输出最终结果
        if best_match:
            self.logger.info(
                f"成功找到目标文本 | "
                f"文本: '{target_text}' | "
                f"位置: {best_match} | "
                f"置信度: {highest_confidence}"
            )
            return best_match
        else:
            self.logger.warning(f"未找到匹配的目标文本: '{target_text}'")
            return None