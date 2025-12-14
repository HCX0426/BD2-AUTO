import os
import time
from typing import Optional, Tuple, List, Dict
import numpy as np
import cv2
from src.auto_control.ocr.base_ocr import BaseOCR
from src.auto_control.ocr.easyocr_wrapper import EasyOCRWrapper
from src.auto_control.config.ocr_config import get_default_languages
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.display_context import RuntimeDisplayContext  # 新增导入
from src.core.path_manager import path_manager


class OCRProcessor:
    def __init__(self, 
                 engine: str = 'easyocr', 
                 logger=None, 
                 coord_transformer: Optional[CoordinateTransformer] = None,
                 display_context: Optional[RuntimeDisplayContext] = None,  # 新增：运行时上下文
                 **kwargs):
        """
        OCR处理器封装类（统一调用不同OCR引擎，支持坐标转换）
        
        :param engine: OCR引擎类型，目前只支持 'easyocr'（默认）
        :param logger: 日志实例（从上层传递，如Auto类）
        :param coord_transformer: 坐标转换器实例（用于处理坐标转换）
        :param display_context: 运行时显示上下文（提供窗口状态和尺寸信息）
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
        
        # 初始化坐标转换器和运行时上下文（强制校验）
        self.coord_transformer = coord_transformer
        self.display_context = display_context
        
        # 校验必要依赖
        if not self.coord_transformer:
            raise ValueError("坐标转换器(coord_transformer)必须初始化后传入")
        if not self.display_context:
            raise ValueError("运行时上下文(display_context)必须初始化后传入")
        
        # 初始化调试目录
        self.debug_img_dir = path_manager.get("match_ocr_debug")
        os.makedirs(self.debug_img_dir, exist_ok=True)
        
        # 初始化指定的OCR引擎（确保与BaseOCR接口兼容）
        self.engine: BaseOCR = self._init_engine(** kwargs)
        
        # 初始化完成日志
        self.logger.info(
            f"OCR处理器初始化完成 | "
            f"引擎: {self.engine_type.upper()} | "
            f"默认语言: {self._default_lang} | "
            f"GPU加速: {'启用' if self.engine._use_gpu else '禁用'} | "
            f"坐标系统: 已配置（上下文+转换器）"
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
        """根据引擎类型初始化具体OCR实例（确保返回BaseOCR子类）"""
        self.logger.debug(f"开始初始化{self.engine_type.upper()}引擎 | 参数: {kwargs}")
        
        if self.engine_type == 'easyocr':
            # 初始化EasyOCR（参数通过配置文件读取，无需额外传入）
            return EasyOCRWrapper(logger=self.logger)  # 传递日志实例给引擎
        else:
            # 为未来可能的引擎扩展预留接口
            raise ValueError(f"不支持的OCR引擎: {self.engine_type}")

    def enable_gpu(self, enable: bool = True):
        """启用/禁用GPU加速（代理到基类方法）"""
        return self.engine.enable_gpu(enable)

    def find_text_position(self,
                        image: np.ndarray,
                        target_text: str,
                        lang: Optional[str] = None,
                        fuzzy_match: bool = False,
                        min_confidence: float = 0.9,
                        region: Optional[Tuple[int, int, int, int]] = None,
                        is_base_region: bool = False,
                        return_base_coord: bool = False) -> Optional[Tuple[int, int, int, int]]:
        """
        查找特定文本在图像中的位置（支持限定区域查找，返回最匹配的边界框）
        
        核心优化：基于display_context提供的客户区尺寸进行坐标校验，确保区域有效性
        """
        target_lang = lang or self._default_lang
        
        # 1. 基础输入参数校验
        if image is None or image.size == 0:
            self.logger.error("查找文本位置失败：无效的输入图像")
            return None
        if not target_text.strip():
            self.logger.error("查找文本位置失败：目标文本为空")
            return None
        
        # 2. 获取当前客户区尺寸（用于坐标校验）
        client_logical_w, client_logical_h = self.display_context.client_logical_res
        img_h, img_w = image.shape[:2]
        self.logger.debug(
            f"当前客户区逻辑尺寸: {client_logical_w}x{client_logical_h} | "
            f"输入图像尺寸: {img_w}x{img_h}"
        )
        
        # 3. 处理限定区域（坐标转换+裁剪图像+记录偏移量）
        orig_image = image.copy()  # 保存原图用于最终坐标映射和调试保存
        region_offset = (0, 0)     # 裁剪区域在原图中的偏移量（x, y）
        processed_region = region
        
        # 区域坐标转换（基准坐标 -> 图像坐标）
        if region and is_base_region:
            try:
                processed_region = self.coord_transformer.convert_original_rect_to_current_client(region)
                self.logger.debug(f"区域坐标转换 | 基准区域: {region} -> 图像区域: {processed_region}")
            except Exception as e:
                self.logger.error(f"限定区域参数无效：{str(e)}，自动切换为全图查找")
                processed_region = None  # 校验失败时回退到全图查找

        if processed_region:
            try:
                r_x, r_y, r_w, r_h = processed_region
                
                # 增强版区域合法性校验（结合客户区尺寸）
                if r_x < 0 or r_y < 0:
                    raise ValueError(f"区域起始坐标不能为负数：(x={r_x}, y={r_y})")
                if r_w <= 0 or r_h <= 0:
                    raise ValueError(f"区域宽高必须为正数：(w={r_w}, h={r_h})")
                if r_x + r_w > client_logical_w or r_y + r_h > client_logical_h:
                    raise ValueError(
                        f"区域超出客户区范围：客户区({client_logical_w}x{client_logical_h})，"
                        f"区域终点({r_x+r_w}, {r_y+r_h})"
                    )
                # 图像尺寸可能小于客户区（如窗口化时），需二次校验
                if r_x + r_w > img_w or r_y + r_h > img_h:
                    self.logger.warning(
                        f"区域超出图像范围，自动裁剪至图像边界 | 图像({img_w}x{img_h})，"
                        f"区域终点({r_x+r_w}, {r_y+r_h})"
                    )
                    r_w = max(1, min(r_w, img_w - r_x))
                    r_h = max(1, min(r_h, img_h - r_y))
                
                # 裁剪子图（OpenCV切片：[y_start:y_end, x_start:x_end]）
                image = orig_image[r_y:r_y + r_h, r_x:r_x + r_w]
                region_offset = (r_x, r_y)  # 记录裁剪区域的左上角偏移
                self.logger.debug(
                    f"已裁剪限定区域 | 客户区尺寸: {client_logical_w}x{client_logical_h} | "
                    f"区域参数: {processed_region} | 裁剪后子图尺寸: {image.shape[1]}x{image.shape[0]}"
                )
                
            except (TypeError, ValueError) as e:
                self.logger.error(f"限定区域参数无效：{str(e)}，自动切换为全图查找")
                processed_region = None  # 校验失败时回退到全图查找

        # 4. 日志输出查找参数
        self.logger.debug(
            f"调用文本位置查找接口 | "
            f"目标文本: '{target_text}' | "
            f"语言: {target_lang} | "
            f"模糊匹配: {'是' if fuzzy_match else '否'} | "
            f"最小置信度: {min_confidence} | "
            f"查找范围: {'指定区域' if processed_region else '全图'} | "
            f"输入坐标类型: {'基准坐标' if is_base_region else '图像坐标'} | "
            f"输出坐标类型: {'基准坐标' if return_base_coord else '图像坐标'}"
        )
        
        # 5. 检测裁剪后图像中的所有文本
        text_results = self.engine.detect_text(image, target_lang)
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
        
        # 7. 保存最高置信度结果（无论是否匹配目标文本）
        if text_results:
            max_conf_result = max(text_results, key=lambda x: x['confidence'])
            max_text = max_conf_result['text']
            max_confidence = max_conf_result['confidence']
            
            # 生成文件名：findtext_时分秒_目标文本_最高置信度文本.png
            timestamp = time.strftime("%H%M%S", time.localtime())
            safe_target = ''.join(c if c.isalnum() else '_' for c in target_text)[:10]
            safe_text = ''.join(c if c.isalnum() else '_' for c in max_text)[:10]
            conf_str = f"{max_confidence:.2f}"
            save_filename = f"findtext_{target_lang}_{timestamp}_target_{safe_target}_max_{safe_text}_{conf_str}.png"
            save_path = os.path.join(self.debug_img_dir, save_filename)
            
            # 转换子图结果到原图坐标
            sub_x, sub_y, sub_w, sub_h = max_conf_result['bbox']
            orig_max_bbox = (
                sub_x + region_offset[0],
                sub_y + region_offset[1],
                sub_w,
                sub_h
            )
            # 保存标注图（使用原图）
            self._save_ocr_debug_image(orig_image, [{'bbox': orig_max_bbox, 'text': max_text, 'confidence': max_confidence}], save_path)
            self.logger.debug(f"已保存最高置信度OCR结果图: {save_filename} | 文本: {max_text} | 置信度: {max_confidence:.2f}")
        
        # 8. 结果坐标转换（图像坐标 -> 原始基准坐标，如果需要）
        final_bbox = best_match
        if best_match and return_base_coord:
            # 使用CoordinateTransformer的方法转换坐标
            final_bbox = self.coord_transformer.convert_current_client_rect_to_original(best_match)
            self.logger.debug(f"结果坐标转换 | 当前客户区坐标: {best_match} -> 原始基准坐标: {final_bbox}")
            
        # 9. 输出最终结果
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

    def batch_process(self, images: List[np.ndarray], lang: Optional[str] = None) -> List[List[Dict]]:
        """批量处理图像（代理到引擎并添加调试保存）"""
        target_lang = lang or self._default_lang
        results = self.engine.batch_process(images, target_lang)
        
        # 为批量处理结果添加调试保存
        for idx, (image, img_results) in enumerate(zip(images, results), 1):
            if img_results:
                max_conf_result = max(img_results, key=lambda x: x['confidence'])
                max_text = max_conf_result['text']
                max_confidence = max_conf_result['confidence']
                
                timestamp = time.strftime("%H%M%S", time.localtime())
                safe_text = ''.join(c if c.isalnum() else '_' for c in max_text)[:20]
                conf_str = f"{max_confidence:.2f}"
                save_filename = f"batch_{self.engine_type}_{idx}_{target_lang}_{timestamp}_{safe_text}_{conf_str}.png"
                save_path = os.path.join(self.debug_img_dir, save_filename)
                
                self._save_ocr_debug_image(image, [max_conf_result], save_path)
                self.logger.debug(f"批量图像 {idx} 最高置信度结果已保存: {save_filename}")
        
        return results

    def _save_ocr_debug_image(self, original_image: np.ndarray, results: List[Dict], save_path: str) -> None:
        """根据OCR结果保存带有标记的调试图像"""
        try:
            # 处理灰度图转彩色图的情况
            debug_image = cv2.cvtColor(original_image, cv2.COLOR_GRAY2BGR) if len(
                original_image.shape) == 2 else original_image.copy()

            for result in results:
                x, y, w, h = result['bbox']
                text = result['text']
                confidence = result['confidence']

                # 绘制矩形框和文本信息
                cv2.rectangle(debug_image, (x, y), (x + w, y + h), (0, 0, 255), 2)
                cv2.putText(debug_image, f"{text} ({confidence:.2f})", (x, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

            # 确保保存目录存在
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            cv2.imwrite(save_path, debug_image)
            self.logger.info(f"OCR调试图片保存成功: {save_path}")
        except Exception as e:
            self.logger.error(f"保存OCR调试图片失败: {str(e)}", exc_info=True)

    def get_scaled_bbox(self, bbox: Tuple[int, int, int, int], is_base_coord: bool = False) -> Tuple[int, int, int, int]:
        """
        将边界框坐标转换为实际屏幕像素坐标（基于上下文的缩放因子）
        
        :param bbox: 输入边界框 (x, y, w, h)
        :param is_base_coord: 输入是否为基准坐标（默认False为客户区坐标）
        :return: 缩放后的屏幕像素坐标 (x, y, w, h)
        """
        if not bbox:
            self.logger.error("无效的边界框输入，无法进行缩放转换")
            return ()
        
        # 坐标转换：基准坐标 -> 客户区坐标（如需）
        processed_bbox = bbox
        if is_base_coord:
            processed_bbox = self.coord_transformer.convert_original_rect_to_current_client(bbox)
        
        # 获取上下文的缩放因子（客户区逻辑尺寸 -> 屏幕像素尺寸）
        scale_x, scale_y = self.display_context.scale_factors
        x, y, w, h = processed_bbox
        
        # 计算缩放后的像素坐标（四舍五入为整数）
        scaled_bbox = (
            int(round(x * scale_x)),
            int(round(y * scale_y)),
            int(round(w * scale_x)),
            int(round(h * scale_y))
        )
        
        self.logger.debug(
            f"边界框缩放转换 | 输入坐标: {bbox} | "
            f"缩放因子: ({scale_x:.2f}, {scale_y:.2f}) | "
            f"输出像素坐标: {scaled_bbox}"
        )
        return scaled_bbox