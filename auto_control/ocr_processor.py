from typing import Optional, Tuple
import numpy as np
from .base_ocr import BaseOCR
from .easyocr_wrapper import EasyOCRWrapper
from .config import get_default_languages
from .coordinate_transformer import CoordinateTransformer

class OCRProcessor:
    def __init__(self, 
                 engine: str = 'easyocr', 
                 logger=None, 
                 coord_transformer: Optional[CoordinateTransformer] = None,** kwargs):
        """
        OCR处理器封装类（统一调用不同OCR引擎，支持坐标转换）
        
        :param engine: OCR引擎类型，目前只支持 'easyocr'（默认）
        :param logger: 日志实例（从上层传递，如Auto类）
        :param coord_transformer: 坐标转换器实例（用于处理坐标转换）
        :param kwargs: 引擎特定参数：
            - languages: 自定义默认语言组合（如 'ch_tra+eng'，可选）
        """
        # 验证引擎类型
        self.engine_type = engine.lower()
        if self.engine_type != 'easyocr':
            raise ValueError(f"不支持的OCR引擎: {engine}，目前只支持 'easyocr'")
        
        # 初始化日志系统（支持降级）
        self.logger = logger if logger else self._create_default_logger()
        
        # 处理默认语言参数（优先使用传入的languages，否则用配置默认值）
        self._default_lang = kwargs.pop('languages', None) or get_default_languages(self.engine_type)
        
        # 初始化坐标转换器
        self.coord_transformer = coord_transformer
        
        # 初始化指定的OCR引擎（确保与BaseOCR接口兼容）
        self.engine: BaseOCR = self._init_engine(**kwargs)
        
        # 初始化完成日志
        self.logger.info(
            f"OCR处理器初始化完成 | "
            f"引擎: {self.engine_type.upper()} | "
            f"默认语言: {self._default_lang} | "
            f"GPU加速: {'启用' if self.engine._use_gpu else '禁用'} | "
            f"坐标转换: {'已配置' if self.coord_transformer else '未配置'}"
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

    def _init_engine(self,** kwargs) -> BaseOCR:
        """根据引擎类型初始化具体OCR实例（确保返回BaseOCR子类）"""
        self.logger.debug(f"开始初始化{self.engine_type.upper()}引擎 | 参数: {kwargs}")
        
        if self.engine_type == 'easyocr':
            # 初始化EasyOCR（参数通过配置文件读取，无需额外传入）
            return EasyOCRWrapper(logger=self.logger)  # 传递日志实例给引擎
        else:
            # 为未来可能的引擎扩展预留接口
            raise ValueError(f"不支持的OCR引擎: {self.engine_type}")

    def set_coord_transformer(self, transformer: CoordinateTransformer) -> None:
        """设置坐标转换器实例"""
        self.coord_transformer = transformer
        self.logger.info("坐标转换器已更新")

    def enable_gpu(self, enable: bool = True):
        """
        启用/禁用GPU加速（代理到基类方法）
        """
        self.engine.enable_gpu(enable)

    def find_text_position(self,
                        image: np.ndarray,
                        target_text: str,
                        lang: Optional[str] = None,
                        fuzzy_match: bool = False,
                        min_confidence: float = 0.6,
                        region: Optional[Tuple[int, int, int, int]] = None,
                        is_base_region: bool = False,
                        return_base_coord: bool = False) -> Optional[Tuple[int, int, int, int]]:
        """
        查找特定文本在图像中的位置（支持限定区域查找，返回最匹配的边界框）
        
        :param image: 输入图像（numpy数组，BGR格式）
        :param target_text: 要查找的目标文本（如 "确认"、"登录"）
        :param lang: 语言代码（如 'ch_tra' 繁体中文，'eng' 英文，支持组合 'ch_tra+eng'）
                    未指定时使用默认语言
        :param fuzzy_match: 是否启用模糊匹配（默认False，精确匹配）
                        启用后使用字符串相似度（≥0.8）判断匹配
        :param min_confidence: 最小置信度阈值（默认0.6，仅筛选高于此值的结果）
        :param region: 限定查找的目标区域（格式：(x, y, w, h)）
        :param is_base_region: region是否为基准坐标（默认False，视为图像原始坐标）
        :param return_base_coord: 是否返回基准坐标（默认False，返回图像原始坐标）
        :return: 目标文本在原图中的边界框 (x, y, w, h)，未找到时返回None
        """
        target_lang = lang or self._default_lang
        
        # 1. 基础输入参数校验
        if image is None or image.size == 0:
            self.logger.error("查找文本位置失败：无效的输入图像")
            return None
        if not target_text.strip():
            self.logger.error("查找文本位置失败：目标文本为空")
            return None
        
        # 2. 处理限定区域（坐标转换+裁剪图像+记录偏移量）
        orig_image = image.copy()  # 保存原图用于最终坐标映射
        region_offset = (0, 0)     # 裁剪区域在原图中的偏移量（x, y）
        processed_region = region
        
        # 区域坐标转换（基准坐标 -> 图像坐标）
        if region and is_base_region and self.coord_transformer:
            try:
                processed_region = self.coord_transformer.convert_original_rect_to_current_client(region)
                self.logger.debug(f"区域坐标转换 | 基准区域: {region} -> 图像区域: {processed_region}")
            except Exception as e:
                self.logger.error(f"限定区域参数无效：{str(e)}，自动切换为全图查找")
                processed_region = None  # 校验失败时回退到全图查找

        if processed_region:
            try:
                r_x, r_y, r_w, r_h = processed_region
                img_h, img_w = orig_image.shape[:2]  # 原图尺寸（h在前，w在后，OpenCV格式）
                
                # 校验region合法性：坐标非负、宽高为正、不超出原图范围
                if r_x < 0 or r_y < 0:
                    raise ValueError(f"区域起始坐标不能为负数：(x={r_x}, y={r_y})")
                if r_w <= 0 or r_h <= 0:
                    raise ValueError(f"区域宽高必须为正数：(w={r_w}, h={r_h})")
                if r_x + r_w > img_w or r_y + r_h > img_h:
                    raise ValueError(
                        f"区域超出原图范围：原图({img_w}x{img_h})，区域终点({r_x+r_w}, {r_y+r_h})"
                    )
                
                # 裁剪子图（OpenCV切片：[y_start:y_end, x_start:x_end]）
                image = orig_image[r_y:r_y + r_h, r_x:r_x + r_w]
                region_offset = (r_x, r_y)  # 记录裁剪区域的左上角偏移
                self.logger.debug(
                    f"已裁剪限定区域 | 原图尺寸: {img_w}x{img_h} | "
                    f"区域参数: {processed_region} | 裁剪后子图尺寸: {image.shape[1]}x{image.shape[0]}"
                )
                
            except (TypeError, ValueError) as e:
                self.logger.error(f"限定区域参数无效：{str(e)}，自动切换为全图查找")
                processed_region = None  # 校验失败时回退到全图查找

        # 3. 日志输出查找参数
        self.logger.debug(
            f"调用文本位置查找接口 | "
            f"目标文本: '{target_text}' | "
            f"语言: {target_lang} | "
            f"模糊匹配: {'是' if fuzzy_match else '否'} | "
            f"最小置信度: {min_confidence} | "
            f"查找范围: {'指定区域' if processed_region else '全图'} | "
            f"输入坐标类型: {'基准坐标' if is_base_region else '图像坐标'} | "
            f"输出坐标类型: {'基准坐标' if return_base_coord else '图像坐标'} | "
            f"图像尺寸: {image.shape[:2]}"
        )
        
        # 4. 检测裁剪后图像中的所有文本
        text_results = self.engine.detect_text(image, target_lang)
        if not text_results:
            self.logger.warning(f"在{'指定区域' if processed_region else '全图'}中未检测到任何文本，无法查找目标 '{target_text}'")
            return None
        
        # 5. 筛选符合条件的匹配结果
        best_match = None
        highest_confidence = 0.0  # 记录最高置信度（优先选择置信度高的匹配）
        
        for result in text_results:
            # 过滤低于最小置信度的结果
            current_confidence = result['confidence']
            if current_confidence < min_confidence:
                self.logger.debug(
                    f"跳过低置信度结果 | 文本: '{result['text']}' | 置信度: {current_confidence} < {min_confidence}"
                )
                continue
            
            # 判断文本是否匹配目标
            is_match = False
            result_text = result['text'].strip()
            
            if fuzzy_match:
                # 模糊匹配：使用difflib计算字符串相似度（≥0.8视为匹配）
                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, result_text, target_text.strip()).ratio()
                is_match = similarity >= 0.8
                self.logger.debug(
                    f"模糊匹配结果 | 识别文本: '{result_text}' | 目标: '{target_text}' | "
                    f"相似度: {similarity:.2f} | 匹配: {'是' if is_match else '否'}"
                )
            else:
                # 精确匹配：完全相等（可根据需求改为忽略大小写）
                is_match = result_text == target_text.strip()
                self.logger.debug(
                    f"精确匹配结果 | 识别文本: '{result_text}' | 目标: '{target_text}' | 匹配: {'是' if is_match else '否'}"
                )
            
            # 找到更优匹配（置信度更高则更新）
            if is_match and current_confidence > highest_confidence:
                highest_confidence = current_confidence
                # 关键：将子图中的边界框坐标映射回原图（加上裁剪区域的偏移量）
                sub_x, sub_y, sub_w, sub_h = result['bbox']
                orig_bbox = (
                    sub_x + region_offset[0],  # 加上x方向偏移
                    sub_y + region_offset[1],  # 加上y方向偏移
                    sub_w,
                    sub_h
                )
                best_match = orig_bbox
                self.logger.debug(
                    f"更新最佳匹配 | 置信度: {highest_confidence} | "
                    f"子图位置: {result['bbox']} | 原图位置: {orig_bbox}"
                )
        
        # 6. 结果坐标转换（图像坐标 -> 原始基准坐标，如果需要）
        final_bbox = best_match
        if best_match and return_base_coord and self.coord_transformer:
            # 使用CoordinateTransformer的方法转换坐标
            final_bbox = self.coord_transformer.convert_current_client_rect_to_original(best_match)
            self.logger.debug(f"结果坐标转换 | 当前客户区坐标: {best_match} -> 原始基准坐标: {final_bbox}")
            
        # 7. 输出最终结果
        if final_bbox:
            self.logger.info(
                f"成功找到目标文本 | "
                f"文本: '{target_text}' | "
                f"位置: {final_bbox} | "
                f"置信度: {highest_confidence:.2f} | "
                f"坐标类型: {'基准坐标' if return_base_coord else '图像坐标'}"
            )
            return final_bbox
        else:
            self.logger.warning(f"在{'指定区域' if processed_region else '全图'}中未找到匹配的目标文本: '{target_text}'")
            return None