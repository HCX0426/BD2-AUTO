import os
from typing import Optional, Tuple, List, Dict
import numpy as np
import cv2
from src.auto_control.ocr.base_ocr import BaseOCR
from src.auto_control.ocr.easyocr_wrapper import EasyOCRWrapper
from src.auto_control.config.ocr_config import get_default_languages
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.display_context import RuntimeDisplayContext
from src.core.path_manager import path_manager, config
import datetime

class OCRProcessor:
    def __init__(self, 
                 engine: str = 'easyocr', 
                 logger=None, 
                 coord_transformer: Optional[CoordinateTransformer] = None,
                 display_context: Optional[RuntimeDisplayContext] = None,
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
        
        # 初始化指定的OCR引擎
        self.engine: BaseOCR = self._init_engine()
        
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

    def _init_engine(self) -> BaseOCR:
        """根据引擎类型初始化具体OCR实例（确保返回BaseOCR子类）"""
        self.logger.debug(f"开始初始化{self.engine_type.upper()}引擎")
        
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
                        min_confidence: float = 0.9,
                        region: Optional[Tuple[int, int, int, int]] = None
        ) -> Optional[Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]]:
        """
        查找文本位置（核心逻辑：文本完全一致优先，即使置信度未达阈值也视为找到）
        规则：区分大小写、忽略空格、完全匹配即有效，多匹配时选置信度最高的
        """
        target_lang = lang or self._default_lang
        # 强制指定中文简体（如果默认语言不含ch_sim，补充它，不影响其他语言）
        if target_lang and "ch_sim" not in target_lang:
            target_lang = f"ch_sim+{target_lang}"
        elif not target_lang:
            target_lang = "ch_sim"  # 无默认语言时，直接用中文简体
        
        # 1. 基础校验（不变）
        if image is None or image.size == 0:
            self.logger.error("查找文本位置失败：无效的输入图像")
            return None
        target_text_clean = target_text.strip()
        if not target_text_clean:
            self.logger.error("查找文本位置失败：目标文本为空")
            return None
        
        # 2. 关键参数+时间戳（不变）
        img_h, img_w = image.shape[:2]  # 截图物理尺寸（用于限制裁剪边界）
        orig_image = image.copy()
        region_offset_phys = (0, 0)
        processed_region_phys = None
        timestamp = datetime.datetime.now().strftime("%H%M%S%f")[:-3]

        is_fullscreen = self.display_context.is_fullscreen
        # 3. 处理region（安全扩展+边界锁，不变）
        if region:
            try:
                if is_fullscreen:
                    rx_phys, ry_phys, rw_phys, rh_phys = region
                    self.logger.debug(f"is_fullscreen=True | 原始物理ROI: {region}")
                else:
                    rx_log, ry_log, rw_log, rh_log = region
                    rx_phys, ry_phys = self.coord_transformer.convert_client_logical_to_physical(rx_log, ry_log)
                    rw_phys = int(round(rw_log * self.display_context.logical_to_physical_ratio))
                    rh_phys = int(round(rh_log * self.display_context.logical_to_physical_ratio))
                    self.logger.debug(f"is_fullscreen=False | 逻辑ROI: {region} → 原始物理ROI: ({rx_phys},{ry_phys},{rw_phys},{rh_phys})")

                # 第一步：先做原始边界校验（避免初始ROI就超出范围）
                rx_phys = max(0, rx_phys)
                ry_phys = max(0, ry_phys)
                rw_phys = min(img_w - rx_phys, rw_phys)
                rh_phys = min(img_h - ry_phys, rh_phys)
                if rw_phys <= 0 or rh_phys <= 0:
                    raise ValueError("初始ROI无效（超出截图范围）")

                # 第二步：安全扩展裁剪区域（带边界锁，不会超出截图）
                expand_pixel = 10  # 扩展10像素（可根据需求调整）
                new_rx = max(0, rx_phys - expand_pixel)
                new_ry = max(0, ry_phys - expand_pixel)
                new_rw = min(img_w - new_rx, rw_phys + 2 * expand_pixel)
                new_rh = min(img_h - new_ry, rh_phys + 2 * expand_pixel)

                # 极端情况：扩展后无效，退回到原始ROI
                if new_rw <= 0 or new_rh <= 0:
                    new_rx, new_ry, new_rw, new_rh = rx_phys, ry_phys, rw_phys, rh_phys
                    self.logger.debug(f"扩展后ROI无效，退回到原始ROI: ({new_rx},{new_ry},{new_rw},{new_rh})")
                else:
                    self.logger.debug(
                        f"ROI安全扩展 | 原始: ({rx_phys},{ry_phys},{rw_phys},{rh_phys}) → "
                        f"扩展后: ({new_rx},{new_ry},{new_rw},{new_rh}) | 截图尺寸: {img_w}x{img_h}"
                    )

                processed_region_phys = (new_rx, new_ry, new_rw, new_rh)
                region_offset_phys = (new_rx, new_ry)

            except Exception as e:
                self.logger.error(f"region处理失败：{str(e)}，切换为全图查找")
                processed_region_phys = None

        # 4. 裁剪截图（用安全扩展后的ROI，不变）
        cropped_image = orig_image
        if processed_region_phys:
            rx_phys, ry_phys, rw_phys, rh_phys = processed_region_phys
            cropped_image = orig_image[ry_phys:ry_phys+rh_phys, rx_phys:rx_phys+rw_phys]
            self.logger.debug(f"截图裁剪完成 | 裁剪后子图尺寸: {cropped_image.shape[1]}x{cropped_image.shape[0]}")
            
            if config.get("debug", False):
                crop_save_path = os.path.join(self.debug_img_dir, f"roi_crop_{target_text_clean}_{timestamp}.png")
                cv2.imwrite(crop_save_path, cropped_image)
                self.logger.info(f"ROI裁剪图保存成功: {crop_save_path}")
        else:
            if config.get("debug", False):
                full_save_path = os.path.join(self.debug_img_dir, f"full_image_{target_text_clean}_{timestamp}.png")
                cv2.imwrite(full_save_path, orig_image)
                self.logger.debug(f"全图查找，保存原图: {full_save_path}")

        # 5. 仅做灰度转RGB（EasyOCR格式要求，不算预处理，不变）
        image_rgb = cropped_image
        if len(image_rgb.shape) == 2:
            image_rgb = cv2.cvtColor(image_rgb, cv2.COLOR_GRAY2RGB)

        # 6. EasyOCR参数优化（适配小文本，不变）
        raw_results = self.engine.reader.readtext(
            image_rgb,
            detail=1,
            paragraph=False,
            text_threshold=0.5,        # 降低文本阈值（小文本特征弱）
            low_text=0.3,              # 降低低文本阈值
            link_threshold=0.7,        # 避免中文拆字
            canvas_size=2048,          # 增大画布精度
            mag_ratio=1.8,             # 放大图像（让小文本特征清晰）
            batch_size=1,              # 单图处理更稳定
            workers=0                  # 禁用多线程冲突
        )

        # 7. 格式化结果（不变）
        formatted_results = []
        for result in raw_results:
            bbox, text, confidence = result[:3]
            x_coords = [int(point[0]) for point in bbox]
            y_coords = [int(point[1]) for point in bbox]
            x_phys_sub = min(x_coords)
            y_phys_sub = min(y_coords)
            w_phys_sub = max(x_coords) - x_phys_sub
            h_phys_sub = max(y_coords) - y_phys_sub
            x_phys_orig = x_phys_sub + region_offset_phys[0]
            y_phys_orig = y_phys_sub + region_offset_phys[1]
            formatted_results.append({
                'text': text.strip(),
                'bbox': (x_phys_sub, y_phys_sub, w_phys_sub, h_phys_sub),
                'bbox_orig_phys': (x_phys_orig, y_phys_orig, w_phys_sub, h_phys_sub),
                'confidence': float(confidence)
            })

        # 8. 保存调试图（不变）
        ocr_save_path = os.path.join(self.debug_img_dir, f"ocr_result_{target_text_clean}_{timestamp}.png")
        self._save_ocr_debug_image(cropped_image, formatted_results, ocr_save_path)

        # 9. 核心修改：匹配逻辑（文本完全一致优先，忽略置信度阈值）
        best_match_phys = None
        highest_confidence = 0.0
        exact_matches = []
        target_text_normalized = target_text_clean.replace(" ", "")  # 忽略空格，区分大小写
        
        # 第一步：筛选所有文本完全匹配的结果（不管置信度是否达到阈值）
        for res in formatted_results:
            res_text_normalized = res['text'].replace(" ", "")  # 忽略空格，区分大小写
            if res_text_normalized == target_text_normalized:
                exact_matches.append(res)
                # 记录最高置信度（用于后续日志提示）
                if res['confidence'] > highest_confidence:
                    highest_confidence = res['confidence']
                self.logger.debug(
                    f"找到精确匹配 | 识别文本: '{res['text']}' | 置信度: {res['confidence']:.4f} | "
                    f"是否达阈值({min_confidence}): {'是' if res['confidence'] >= min_confidence else '否'} | "
                    f"原图物理坐标: {res['bbox_orig_phys']}"
                )
        
        # 第二步：处理匹配结果
        if exact_matches:
            # 有多个完全匹配时，选择置信度最高的（即使最高也低于阈值）
            if len(exact_matches) > 1:
                self.logger.debug(f"找到{len(exact_matches)}个精确匹配结果，选择置信度最高的")
                exact_matches.sort(key=lambda x: x['confidence'], reverse=True)
            
            best_match = exact_matches[0]
            best_match_phys = best_match['bbox_orig_phys']
            highest_confidence = best_match['confidence']
            
            # 日志提示：区分置信度是否达阈值
            if highest_confidence >= min_confidence:
                match_info = f"置信度达标({highest_confidence:.4f} ≥ {min_confidence})"
            else:
                match_info = f"置信度未达阈值({highest_confidence:.4f} < {min_confidence})，但文本完全一致"
        else:
            # 无任何完全匹配结果
            all_recognized = [f"{r['text']}({r['confidence']:.2f})" for r in formatted_results]
            self.logger.warning(
                f"未找到目标文本的精确匹配: '{target_text_clean}' | "
                f"所有识别结果: {all_recognized} | 阈值: {min_confidence}"
            )
            return None

        # 10. 坐标转换（不变）
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
            final_bbox_phys = (x_phys, y_phys, w_phys, h_phys)
            self.logger.info(
                f"找到目标文本（精确匹配） | 文本: '{target_text_clean}' | {match_info} | "
                f"逻辑坐标: {final_bbox_log} | 物理坐标: {final_bbox_phys} | "
                f"匹配结果数: {len(exact_matches)}"
            )
            return (final_bbox_log, final_bbox_phys)
        else:
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