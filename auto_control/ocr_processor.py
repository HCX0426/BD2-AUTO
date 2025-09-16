from typing import List, Dict, Optional, Tuple, Union
import numpy as np
from .ocr_core import EasyOCRWrapper, BaseOCR
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
        # 从坐标转换器获取原始基准分辨率（缓存，避免重复获取）
        self._original_base_res = coord_transformer._original_base_res if (coord_transformer and hasattr(coord_transformer, '_original_base_res')) else (0, 0)
        
        # 初始化指定的OCR引擎（确保与BaseOCR接口兼容）
        self.engine: BaseOCR = self._init_engine(**kwargs)
        
        # 初始化完成日志
        self.logger.info(
            f"OCR处理器初始化完成 | "
            f"引擎: {self.engine_type.upper()} | "
            f"默认语言: {self._default_lang} | "
            f"GPU加速: {'启用' if self.engine._use_gpu else '禁用'} | "
            f"坐标转换: {'已配置' if self.coord_transformer else '未配置'} | "
            f"原始基准分辨率: {self._original_base_res}"
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
        """设置坐标转换器实例，同步更新原始基准分辨率"""
        self.coord_transformer = transformer
        self._original_base_res = transformer._original_base_res if (transformer and hasattr(transformer, '_original_base_res')) else (0, 0)
        self.logger.info(f"坐标转换器已更新 | 原始基准分辨率: {self._original_base_res}")

    def _convert_current_client_to_base(self, x: int, y: int) -> Tuple[int, int]:
        """
        补充：当前客户区坐标 → 原始基准坐标（反向转换）
        逻辑：基于原始基准分辨率与当前客户区尺寸的比例推导
        """
        if not self.coord_transformer:
            self.logger.warning("无坐标转换器，无法将当前客户区坐标转为原始基准坐标")
            return (x, y)
        
        # 获取当前客户区尺寸（从坐标转换器动态获取）
        curr_client_w, curr_client_h = self.coord_transformer._current_client_size
        orig_base_w, orig_base_h = self._original_base_res
        
        # 校验参数有效性（避免除零错误）
        if curr_client_w <= 0 or curr_client_h <= 0 or orig_base_w <= 0 or orig_base_h <= 0:
            self.logger.warning(
                f"无效参数，无法反向转换坐标 | "
                f"当前客户区尺寸: ({curr_client_w},{curr_client_h}) | "
                f"原始基准分辨率: ({orig_base_w},{orig_base_h})"
            )
            return (x, y)
        
        # 反向转换比例：原始基准尺寸 / 当前客户区尺寸
        scale_x = orig_base_w / curr_client_w
        scale_y = orig_base_h / curr_client_h
        
        # 计算原始基准坐标（四舍五入为整数）
        base_x = int(round(x * scale_x))
        base_y = int(round(y * scale_y))
        
        self.logger.debug(
            f"当前客户区→原始基准坐标转换 | "
            f"当前坐标: ({x},{y}) | 比例(x:y): {scale_x:.2f}:{scale_y:.2f} | "
            f"原始基准坐标: ({base_x},{base_y})"
        )
        return (base_x, base_y)

    def _convert_current_client_rect_to_base(self, rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """
        补充：当前客户区矩形 → 原始基准矩形（反向转换，处理ROI）
        :param rect: 当前客户区矩形 (x, y, w, h)
        :return: 原始基准矩形 (x, y, w, h)
        """
        x, y, w, h = rect
        # 转换左上角坐标
        base_x, base_y = self._convert_current_client_to_base(x, y)
        # 转换宽高（使用相同比例）
        curr_client_w, curr_client_h = self.coord_transformer._current_client_size
        orig_base_w, orig_base_h = self._original_base_res
        if curr_client_w <= 0 or curr_client_h <= 0 or orig_base_w <= 0 or orig_base_h <= 0:
            return (base_x, base_y, w, h)
        scale_x = orig_base_w / curr_client_w
        scale_y = orig_base_h / curr_client_h
        base_w = int(round(w * scale_x))
        base_h = int(round(h * scale_y))
        # 确保尺寸为正
        base_w = max(1, base_w)
        base_h = max(1, base_h)
        
        self.logger.debug(
            f"当前客户区→原始基准矩形转换 | "
            f"当前矩形: {rect} | 比例(x:y): {scale_x:.2f}:{scale_y:.2f} | "
            f"原始基准矩形: ({base_x},{base_y},{base_w},{base_h})"
        )
        return (base_x, base_y, base_w, base_h)

    def detect_text(self, 
                   image: np.ndarray, 
                   lang: Optional[str] = None,
                   is_base_coord: bool = False,
                   preprocess: bool = True) -> List[Dict[str, Union[str, Tuple[int, int, int, int], float]]]:
        """
        检测图像中的文本位置及内容（返回详细边界框信息）
        
        :param image: 输入图像（numpy数组，BGR格式）
        :param lang: 语言代码（如 'ch_tra' 繁体中文，'eng' 英文，支持组合 'ch_tra+eng'）
                     未指定时使用默认语言
        :param is_base_coord: 是否将结果转换为基准坐标（默认False，返回图像原始坐标）
        :param preprocess: 是否启用基类的图像预处理（默认True）
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
        
        # 图像预处理（使用基类的预处理方法）
        processed_image = image
        if preprocess:
            processed_image = self.engine._preprocess_image(image)
        
        self.logger.debug(
            f"调用文本检测接口 | "
            f"引擎: {self.engine_type.upper()} | "
            f"语言: {target_lang} | "
            f"原始尺寸: {image.shape[:2]} | "
            f"处理后尺寸: {processed_image.shape[:2]} | "
            f"坐标类型: {'基准坐标' if is_base_coord else '原始坐标'}"
        )
        
        # 调用引擎的检测方法（确保与BaseOCR接口一致）
        results = self.engine.detect_text(processed_image, target_lang)
        
        # 如果需要转换为基准坐标（调用补充的反向转换方法）
        if is_base_coord and self.coord_transformer:
            converted_results = []
            for result in results:
                bbox = result['bbox']
                x, y, w, h = bbox
                # 转换左上角坐标，宽高同步转换
                base_x, base_y = self._convert_current_client_to_base(x, y)
                curr_client_w, curr_client_h = self.coord_transformer._current_client_size
                orig_base_w, orig_base_h = self._original_base_res
                if curr_client_w > 0 and curr_client_h > 0 and orig_base_w > 0 and orig_base_h > 0:
                    scale_x = orig_base_w / curr_client_w
                    scale_y = orig_base_h / curr_client_h
                    base_w = int(round(w * scale_x))
                    base_h = int(round(h * scale_y))
                else:
                    base_w, base_h = w, h
                converted_bbox = (base_x, base_y, base_w, base_h)
                converted_result = {**result, 'bbox': converted_bbox}
                converted_results.append(converted_result)
            results = converted_results
        
        self.logger.debug(f"文本检测接口返回 | 有效结果数量: {len(results)}")
        return results

    def recognize_text(self, 
                      image: np.ndarray,
                      lang: Optional[str] = None,
                      region: Optional[Tuple[int, int, int, int]] = None,
                      is_base_region: bool = False,
                      preprocess: bool = True) -> str:
        """
        识别图像中的文本内容（仅返回纯文本字符串，不包含位置信息）
        
        :param image: 输入图像（numpy数组，BGR格式）
        :param lang: 语言代码（未指定时使用默认语言）
        :param region: 限定识别区域（格式：(x, y, w, h)），未指定时默认全图识别
        :param is_base_region: region是否为基准坐标（默认False，视为图像原始坐标）
        :param preprocess: 是否启用基类的图像预处理（默认True）
        :return: 识别出的纯文本字符串（空字符串表示识别失败或无文本）
        """
        target_lang = lang or self._default_lang
        
        # 输入参数校验
        if image is None or image.size == 0:
            self.logger.error("无效的输入图像（空图像或尺寸为0）")
            return ""
        
        # 处理区域坐标转换（修正方法名：convert_base_rect_to_client → convert_original_rect_to_current_client）
        processed_region = region
        if region and is_base_region and self.coord_transformer:
            try:
                # 原始基准矩形 → 当前客户区矩形（使用正确的方法名）
                processed_region = self.coord_transformer.convert_original_rect_to_current_client(region)
                self.logger.debug(f"区域坐标转换 | 基准区域: {region} -> 图像区域: {processed_region}")
            except Exception as e:
                self.logger.error(f"区域坐标转换失败: {str(e)}，将使用原始区域")
                processed_region = region
        
        # 裁剪区域（如果指定）
        processed_image = image
        if processed_region:
            try:
                r_x, r_y, r_w, r_h = processed_region
                img_h, img_w = image.shape[:2]
                
                # 确保区域在图像范围内
                r_x = max(0, min(r_x, img_w - 1))
                r_y = max(0, min(r_y, img_h - 1))
                r_w = max(1, min(r_w, img_w - r_x))
                r_h = max(1, min(r_h, img_h - r_y))
                
                processed_image = image[r_y:r_y + r_h, r_x:r_x + r_w]
            except Exception as e:
                self.logger.error(f"区域裁剪失败: {str(e)}，将使用全图识别")
                processed_region = None
        
        # 图像预处理（使用基类的预处理方法）
        if preprocess:
            processed_image = self.engine._preprocess_image(processed_image)
        
        self.logger.debug(
            f"调用文本识别接口 | "
            f"引擎: {self.engine_type.upper()} | "
            f"语言: {target_lang} | "
            f"原始图像尺寸: {image.shape[:2]} | "
            f"处理图像尺寸: {processed_image.shape[:2]} | "
            f"识别范围: {'指定区域' if processed_region else '全图'}"
        )
        
        # 调用引擎的识别方法（确保与BaseOCR接口一致）
        result_text = self.engine.recognize_text(processed_image, target_lang)
        
        # 日志记录识别结果（截断过长文本，避免日志冗余）
        log_text = result_text[:50] + "..." if len(result_text) > 50 else result_text
        self.logger.info(f"文本识别接口返回 | 文本长度: {len(result_text)} | 内容: {log_text}")
        
        return result_text

    def detect_and_recognize(self,
                            image: np.ndarray,
                            lang: Optional[str] = None,
                            is_base_coord: bool = False,
                            preprocess: bool = True) -> List[Dict]:
        """
        同时检测和识别文本（功能同detect_text，统一接口命名）
        
        :param image: 输入图像（numpy数组，BGR格式）
        :param lang: 语言代码（未指定时使用默认语言）
        :param is_base_coord: 是否将结果转换为基准坐标（默认False，返回图像原始坐标）
        :param preprocess: 是否启用基类的图像预处理（默认True）
        :return: 文本检测与识别结果列表（同detect_text的返回格式）
        """
        target_lang = lang or self._default_lang
        self.logger.debug(f"调用检测与识别接口 | 语言: {target_lang} | 坐标类型: {'基准坐标' if is_base_coord else '原始坐标'}")
        
        # 图像预处理
        processed_image = image
        if preprocess:
            processed_image = self.engine._preprocess_image(image)
        
        # 调用引擎方法（确保与BaseOCR接口一致）
        results = self.engine.detect_and_recognize(processed_image, target_lang)
        
        # 坐标转换处理（使用补充的反向转换方法）
        if is_base_coord and self.coord_transformer:
            converted_results = []
            for result in results:
                bbox = result['bbox']
                x, y, w, h = bbox
                # 转换左上角坐标和宽高
                base_x, base_y = self._convert_current_client_to_base(x, y)
                curr_client_w, curr_client_h = self.coord_transformer._current_client_size
                orig_base_w, orig_base_h = self._original_base_res
                if curr_client_w > 0 and curr_client_h > 0 and orig_base_w > 0 and orig_base_h > 0:
                    scale_x = orig_base_w / curr_client_w
                    scale_y = orig_base_h / curr_client_h
                    base_w = int(round(w * scale_x))
                    base_h = int(round(h * scale_y))
                else:
                    base_w, base_h = w, h
                converted_bbox = (base_x, base_y, base_w, base_h)
                converted_result = {**result, 'bbox': converted_bbox}
                converted_results.append(converted_result)
            results = converted_results
        
        self.logger.debug(f"检测与识别接口返回 | 结果数量: {len(results)}")
        return results

    def batch_process(self,
                     images: List[np.ndarray],
                     lang: Optional[str] = None,
                     is_base_coord: bool = False,
                     preprocess: bool = True) -> List[List[Dict]]:
        """
        批量处理多张图像的文本检测与识别
        
        :param images: 输入图像列表（每个元素为numpy数组，BGR格式）
        :param lang: 语言代码（所有图像共用同一语言，未指定时使用默认语言）
        :param is_base_coord: 是否将结果转换为基准坐标（默认False，返回图像原始坐标）
        :param preprocess: 是否启用基类的图像预处理（默认True）
        :return: 批量处理结果列表，每个元素为单张图像的检测结果（同detect_text格式）
        """
        target_lang = lang or self._default_lang
        
        # 输入参数校验
        if not images or any(img is None or img.size == 0 for img in images):
            self.logger.error("批量处理失败：输入图像列表为空或包含无效图像")
            return []
        
        # 图像预处理
        processed_images = []
        for img in images:
            if preprocess:
                processed_img = self.engine._preprocess_image(img)
                processed_images.append(processed_img)
            else:
                processed_images.append(img)
        
        self.logger.info(
            f"调用批量处理接口 | "
            f"引擎: {self.engine_type.upper()} | "
            f"语言: {target_lang} | "
            f"图像总数: {len(images)} | "
            f"坐标类型: {'基准坐标' if is_base_coord else '原始坐标'}"
        )
        
        # 调用引擎的批量处理方法（确保与BaseOCR接口一致）
        batch_results = self.engine.batch_process(processed_images, target_lang)
        
        # 坐标转换处理（使用补充的反向转换方法）
        if is_base_coord and self.coord_transformer:
            converted_batch = []
            for results in batch_results:
                converted_results = []
                for result in results:
                    bbox = result['bbox']
                    x, y, w, h = bbox
                    # 转换左上角坐标和宽高
                    base_x, base_y = self._convert_current_client_to_base(x, y)
                    curr_client_w, curr_client_h = self.coord_transformer._current_client_size
                    orig_base_w, orig_base_h = self._original_base_res
                    if curr_client_w > 0 and curr_client_h > 0 and orig_base_w > 0 and orig_base_h > 0:
                        scale_x = orig_base_w / curr_client_w
                        scale_y = orig_base_h / curr_client_h
                        base_w = int(round(w * scale_x))
                        base_h = int(round(h * scale_y))
                    else:
                        base_w, base_h = w, h
                    converted_bbox = (base_x, base_y, base_w, base_h)
                    converted_result = {**result, 'bbox': converted_bbox}
                    converted_results.append(converted_result)
                converted_batch.append(converted_results)
            batch_results = converted_batch
        
        self.logger.info(
            f"批量处理接口返回 | "
            f"成功处理: {len(batch_results)} 张 | "
            f"总结果数: {sum(len(res) for res in batch_results)}"
        )
        return batch_results

    def enable_gpu(self, enable: bool = True):
        """
        启用/禁用GPU加速（代理到基类方法）
        """
        self.engine.enable_gpu(enable)
        # 同步本地状态（与基类保持一致）
        self._use_gpu = self.engine._use_gpu

    def find_text_position(self,
                        image: np.ndarray,
                        target_text: str,
                        lang: Optional[str] = None,
                        fuzzy_match: bool = False,
                        min_confidence: float = 0.6,
                        region: Optional[Tuple[int, int, int, int]] = None,
                        is_base_region: bool = False,
                        return_base_coord: bool = False,
                        preprocess: bool = False) -> Optional[Tuple[int, int, int, int]]:
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
        :param preprocess: 是否启用基类的图像预处理（默认True）
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
        
        # 区域坐标转换（基准坐标 -> 图像坐标，修正方法名）
        if region and is_base_region and self.coord_transformer:
            try:
                # 使用正确的方法名：convert_original_rect_to_current_client
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

        # 3. 图像预处理
        processed_image = image
        if preprocess:
            processed_image = self.engine._preprocess_image(image)

        # 4. 日志输出查找参数
        self.logger.debug(
            f"调用文本位置查找接口 | "
            f"目标文本: '{target_text}' | "
            f"语言: {target_lang} | "
            f"模糊匹配: {'是' if fuzzy_match else '否'} | "
            f"最小置信度: {min_confidence} | "
            f"查找范围: {'指定区域' if processed_region else '全图'} | "
            f"输入坐标类型: {'基准坐标' if is_base_region else '图像坐标'} | "
            f"输出坐标类型: {'基准坐标' if return_base_coord else '图像坐标'} | "
            f"原始尺寸: {image.shape[:2]} | "
            f"处理后尺寸: {processed_image.shape[:2]}"
        )
        
        # 5. 检测裁剪后图像中的所有文本（复用基类的detect_and_recognize方法）
        text_results = self.engine.detect_and_recognize(processed_image, target_lang)
        if not text_results:
            self.logger.warning(f"在{'指定区域' if processed_region else '全图'}中未检测到任何文本，无法查找目标 '{target_text}'")
            return None
        
        # 6. 筛选符合条件的匹配结果
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
        
        # 7. 结果坐标转换（图像坐标 -> 原始基准坐标，如果需要）
        final_bbox = best_match
        if best_match and return_base_coord and self.coord_transformer:
            # 使用补充的反向转换方法，转换整个矩形
            final_bbox = self._convert_current_client_rect_to_base(best_match)
            self.logger.debug(f"结果坐标转换 | 当前客户区坐标: {best_match} -> 原始基准坐标: {final_bbox}")
        
        # 8. 输出最终结果
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