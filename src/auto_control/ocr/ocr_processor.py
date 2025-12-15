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
import datetime


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
        查找文本位置（按需求修改：去预处理+保存裁剪图+保存OCR结果图）
        :param is_base_region: True=region是物理坐标（基准ROI），False=region是逻辑坐标
        :return: 客户区逻辑坐标
        """
        target_lang = lang or self._default_lang
        
        # 1. 基础校验
        if image is None or image.size == 0:
            self.logger.error("查找文本位置失败：无效的输入图像")
            return None
        if not target_text.strip():
            self.logger.error("查找文本位置失败：目标文本为空")
            return None
        
        # 2. 关键参数+时间戳（用于保存图片命名）
        img_h, img_w = image.shape[:2]  # 截图物理尺寸
        orig_image = image.copy()
        region_offset_phys = (0, 0)
        processed_region_phys = None  # 最终裁剪用的物理坐标
        is_fullscreen = self.coord_transformer.is_fullscreen
        timestamp = datetime.datetime.now().strftime("%H%M%S")  # 精确到毫秒，避免重名

        # 3. 处理region（核心：区分is_base_region）
        if region:
            try:
                if is_base_region:
                    # is_base_region=True：region是物理坐标（全屏基准ROI），直接用
                    rx_phys, ry_phys, rw_phys, rh_phys = region
                    self.logger.debug(f"is_base_region=True | 直接使用物理ROI裁剪: {region}")
                else:
                    # is_base_region=False：region是逻辑坐标，转物理坐标
                    rx_log, ry_log, rw_log, rh_log = region
                    rx_phys, ry_phys = self.coord_transformer.convert_client_logical_to_physical(rx_log, ry_log)
                    rw_phys = int(round(rw_log * self.display_context.logical_to_physical_ratio))
                    rh_phys = int(round(rh_log * self.display_context.logical_to_physical_ratio))
                    self.logger.debug(f"is_base_region=False | 逻辑ROI: {region} → 物理ROI: ({rx_phys},{ry_phys},{rw_phys},{rh_phys})")

                # 校验物理坐标不超出截图范围
                if rx_phys < 0: rx_phys = 0
                if ry_phys < 0: ry_phys = 0
                if rx_phys + rw_phys > img_w: rw_phys = img_w - rx_phys
                if ry_phys + rh_phys > img_h: rh_phys = img_h - ry_phys
                if rw_phys <= 0 or rh_phys <= 0:
                    raise ValueError("裁剪后物理区域无效")

                processed_region_phys = (rx_phys, ry_phys, rw_phys, rh_phys)
                region_offset_phys = (rx_phys, ry_phys)
                self.logger.debug(f"裁剪物理ROI确认: {processed_region_phys} | 截图尺寸: {img_w}x{img_h}")
            except Exception as e:
                self.logger.error(f"region处理失败：{str(e)}，切换为全图查找")
                processed_region_phys = None

        # 4. 裁剪截图 + 保存ROI裁剪图
        cropped_image = orig_image
        if processed_region_phys:
            rx_phys, ry_phys, rw_phys, rh_phys = processed_region_phys
            cropped_image = orig_image[ry_phys:ry_phys+rh_phys, rx_phys:rx_phys+rw_phys]
            self.logger.debug(f"截图裁剪完成 | 裁剪后子图尺寸: {cropped_image.shape[1]}x{cropped_image.shape[0]}")
            
            # 保存ROI裁剪图（原图未预处理，方便查看是否截到文本）
            crop_save_path = os.path.join(self.debug_img_dir, f"roi_crop_{target_text}_{timestamp}.png")
            cv2.imwrite(crop_save_path, cropped_image)
            self.logger.info(f"ROI裁剪图保存成功: {crop_save_path}")
        else:
            # 全图查找时，也保存全图（方便调试）
            full_save_path = os.path.join(self.debug_img_dir, f"full_image_{target_text}_{timestamp}.png")
            cv2.imwrite(full_save_path, orig_image)
            self.logger.debug(f"全图查找，保存原图: {full_save_path}")

        # 5. 移除图像预处理（直接用原图识别）
        image_rgb = cropped_image  # 无需任何处理，直接传给OCR
        if len(image_rgb.shape) == 2:  # 若为灰度图，转RGB（EasyOCR要求）
            image_rgb = cv2.cvtColor(image_rgb, cv2.COLOR_GRAY2RGB)

        # 6. OCR识别（恢复默认参数，避免置信度过低）
        raw_results = self.engine.reader.readtext(
            image_rgb,
            detail=1,
            paragraph=False,
            text_threshold=0.7,  # 恢复默认高阈值，提升识别精度
            low_text=0.4,
            link_threshold=0.8,
            canvas_size=1024,
            mag_ratio=1.0,  # 不放大，避免失真
        )

        # 7. 格式化结果 + 保存OCR识别结果图
        formatted_results = []
        for result in raw_results:
            bbox, text, confidence = result[:3]
            x_coords = [int(point[0]) for point in bbox]
            y_coords = [int(point[1]) for point in bbox]
            x_phys_sub = min(x_coords)
            y_phys_sub = min(y_coords)
            w_phys_sub = max(x_coords) - x_phys_sub
            h_phys_sub = max(y_coords) - y_phys_sub
            # 映射到原图物理坐标（加裁剪偏移）
            x_phys_orig = x_phys_sub + region_offset_phys[0]
            y_phys_orig = y_phys_sub + region_offset_phys[1]
            formatted_results.append({
                'text': text.strip(),
                'bbox': (x_phys_sub, y_phys_sub, w_phys_sub, h_phys_sub),  # 裁剪图内的坐标（用于画图）
                'bbox_orig_phys': (x_phys_orig, y_phys_orig, w_phys_sub, h_phys_sub),  # 原图物理坐标
                'confidence': float(confidence)
            })

        # 保存OCR识别结果图（在裁剪图上标记识别到的文本）
        ocr_save_path = os.path.join(self.debug_img_dir, f"ocr_result_{target_text}_{timestamp}.png")
        self._save_ocr_debug_image(cropped_image, formatted_results, ocr_save_path)

        # 8. 筛选匹配结果（恢复严格匹配，避免误识别）
        best_match_phys = None
        highest_confidence = 0.0
        target_text_clean = target_text.strip().lower().replace(" ", "")
        for res in formatted_results:
            curr_conf = res['confidence']
            if curr_conf < min_confidence:  # 按传入的min_confidence过滤（默认0.9）
                continue
            res_text_clean = res['text'].strip().lower().replace(" ", "")
            
            # 模糊匹配（如需严格匹配，可把similarity阈值设为1.0）
            from difflib import SequenceMatcher
            similarity = SequenceMatcher(None, res_text_clean, target_text_clean).ratio()
            if similarity >= 0.8 and curr_conf > highest_confidence:  # 提高相似度阈值，减少误判
                highest_confidence = curr_conf
                best_match_phys = res['bbox_orig_phys']
                self.logger.debug(
                    f"匹配成功 | 识别文本: '{res['text']}' | 相似度: {similarity:.2f} | "
                    f"置信度: {curr_conf:.4f} | 原图物理坐标: {best_match_phys}"
                )

        # 9. 物理坐标→逻辑坐标（返回结果）
        if best_match_phys:
            x_phys, y_phys, w_phys, h_phys = best_match_phys
            x_log = self.coord_transformer.convert_client_physical_to_logical(x_phys, y_phys)[0]
            y_log = self.coord_transformer.convert_client_physical_to_logical(x_phys, y_phys)[1]
            w_log = int(round(w_phys / self.display_context.logical_to_physical_ratio))
            h_log = int(round(h_phys / self.display_context.logical_to_physical_ratio))
            
            client_w_log, client_h_log = self.display_context.client_logical_res
            x_log = max(0, min(x_log, client_w_log - 1))
            y_log = max(0, min(y_log, client_h_log - 1))
            w_log = max(1, min(w_log, client_w_log - x_log))
            h_log = max(1, min(h_log, client_h_log - y_log))
            
            final_bbox_log = (x_log, y_log, w_log, h_log)
            self.logger.info(
                f"找到目标文本 | 文本: '{target_text}' | 逻辑坐标: {final_bbox_log} | "
                f"物理坐标: {best_match_phys} | 置信度: {highest_confidence:.4f}"
            )
            return final_bbox_log
        else:
            self.logger.warning(
                f"未找到目标文本: '{target_text}' | 识别到的文本: {[r['text'] for r in formatted_results]} | "
                f"置信度范围: {[f'{r["confidence"]:.4f}' for r in formatted_results]}"
            )
            return None

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