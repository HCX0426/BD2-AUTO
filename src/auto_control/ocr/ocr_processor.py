import os
from typing import Optional, Tuple, List, Dict
import numpy as np
import cv2
from src.auto_control.ocr.base_ocr import BaseOCR
from src.auto_control.ocr.easyocr_wrapper import EasyOCRWrapper
from src.auto_control.config.ocr_config import get_default_languages
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.display_context import RuntimeDisplayContext
from src.auto_control.utils.debug_image_saver import DebugImageSaver
from src.core.path_manager import path_manager
import datetime

class OCRProcessor:
    def __init__(self, 
                 engine: str = 'easyocr', 
                 logger=None, 
                 coord_transformer: CoordinateTransformer = None,
                 display_context: RuntimeDisplayContext = None,
                 test_mode: bool = False,
                 **kwargs):
        """
        OCR处理器封装类（统一调用不同OCR引擎，支持坐标转换）
        
        :param engine: OCR引擎类型，目前只支持 'easyocr'（默认）
        :param logger: 日志实例（从上层传递，如Auto类）
        :param coord_transformer: 坐标转换器实例（用于处理坐标转换）
        :param display_context: 运行时显示上下文（提供窗口状态和尺寸信息）
        :param test_mode: 测试模式开关（控制是否保存调试图片+初始化清空历史图），默认False
        :param kwargs: 引擎特定参数：
            - languages: 自定义默认语言组合（如 'ch_tra+eng'，可选）
        """

        if not logger:
            raise ValueError("初始化失败：logger不能为空（必须传入有效日志实例）")
        if not isinstance(coord_transformer, CoordinateTransformer):
            raise ValueError("初始化失败：coord_transformer必须是CoordinateTransformer实例")
        if not isinstance(display_context, RuntimeDisplayContext):
            raise ValueError("初始化失败：display_context必须是RuntimeDisplayContext实例")
        
        # 验证引擎类型
        self.engine_type = engine.lower()
        if self.engine_type != 'easyocr':
            raise ValueError(f"不支持的OCR引擎: {engine}，目前只支持 'easyocr'")
        
        # 初始化日志系统
        self.logger = logger
        # 初始化坐标转换器和运行时上下文
        self.coord_transformer = coord_transformer
        self.display_context = display_context
        
        # 处理默认语言参数（优先使用传入的languages，否则用配置默认值）
        self._default_lang = kwargs.pop('languages', None) or get_default_languages(self.engine_type)
        
        # 初始化调试工具（新增：公共调试图保存工具）
        self.debug_saver = DebugImageSaver(
            logger=self.logger,
            debug_dir=path_manager.get("match_ocr_debug"),
            test_mode=test_mode
        )
        self.test_mode = test_mode
        
        # 初始化指定的OCR引擎
        self.engine: BaseOCR = self._init_engine()
        
        # 初始化完成日志
        self.logger.info(
            f"OCR处理器初始化完成 | "
            f"引擎: {self.engine_type.upper()} | "
            f"默认语言: {self._default_lang} | "
            f"GPU加速: {'启用' if self.engine._use_gpu else '禁用'} | "
            f"坐标系统: 已配置（上下文+转换器）| "
            f"测试模式: {'启用（已清空历史调试图）' if self.test_mode else '禁用'}"
        )

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
        target_lang = lang or self._default_lang
        if target_lang and "ch_sim" not in target_lang:
            target_lang = f"ch_sim+{target_lang}"
        elif not target_lang:
            target_lang = "ch_sim"
        
        # 1. 基础校验（不变）
        if image is None or image.size == 0:
            self.logger.error("查找文本位置失败：无效的输入图像")
            return None
        target_text_clean = target_text.strip()
        if not target_text_clean:
            self.logger.error("查找文本位置失败：目标文本为空")
            return None
        
        # 2. 关键参数（不变）
        img_h, img_w = image.shape[:2]
        orig_image = image.copy()
        region_offset_phys = (0, 0)
        orig_region_phys = None
        timestamp = datetime.datetime.now().strftime("%H%M%S%f")[:-3]
        is_fullscreen = self.display_context.is_fullscreen

        # ------------------------------ 复用CoordinateTransformer的ROI处理 ------------------------------
        processed_region_phys = None
        if region:
            # 调用公共ROI处理方法（启用扩展，使用图像物理尺寸作为边界）
            processed_region_phys, region_offset_phys = self.coord_transformer.process_roi(
                roi=region,
                boundary_width=img_w,
                boundary_height=img_h,
                enable_expand=True,  # OCR启用安全扩展
                expand_pixel=10  # 扩展10像素（可自定义）
            )
            orig_region_phys = processed_region_phys  # 记录用于标注的区域坐标

        # 4. 裁剪截图（新增：子图有效性检查，避免裁剪后为空）
        cropped_image = orig_image
        if processed_region_phys:
            rx_phys, ry_phys, rw_phys, rh_phys = processed_region_phys
            cropped_image = orig_image[ry_phys:ry_phys+rh_phys, rx_phys:rx_phys+rw_phys]
            # 新增：裁剪后子图为空时回退到原图
            if cropped_image.size == 0:
                self.logger.warning(f"ROI裁剪后子图为空，切换为全图识别 | 原始ROI: {region} | 处理后ROI物理坐标: {processed_region_phys}")
                cropped_image = orig_image
                region_offset_phys = (0, 0)
                orig_region_phys = None
            else:
                self.logger.debug(f"截图裁剪完成 | 裁剪后子图尺寸: {cropped_image.shape[1]}x{cropped_image.shape[0]}")
        else:
            self.logger.debug(f"全图查找，无需裁剪 | 原图尺寸: {img_w}x{img_h}")

        # 后续逻辑（OCR识别、结果格式化、匹配逻辑）不变...
        image_rgb = cropped_image
        if len(image_rgb.shape) == 2:
            image_rgb = cv2.cvtColor(image_rgb, cv2.COLOR_GRAY2RGB)

        raw_results = self.engine.reader.readtext(
            image_rgb,
            detail=1,
            paragraph=False,
            text_threshold=0.5,
            low_text=0.3,
            link_threshold=0.7,
            canvas_size=2048,
            mag_ratio=1.8,
            batch_size=1,
            workers=0
        )

        formatted_results = []
        for result in raw_results:
            bbox, text, confidence = result[:3]
            x_coords = [int(point[0]) for point in bbox]
            y_coords = [int(point[1]) for point in bbox]
            x_phys_sub = min(x_coords)
            y_phys_sub = min(y_coords)
            w_phys_sub = max(x_coords) - x_phys_sub
            h_phys_sub = max(y_coords) - y_phys_sub
            
            # ------------------------------ 核心修改：复用坐标转换器的偏移计算方法 ------------------------------
            # 子图内矩形 → 原图物理矩形（替换手动偏移计算）
            bbox_sub = (x_phys_sub, y_phys_sub, w_phys_sub, h_phys_sub)
            bbox_orig_phys = self.coord_transformer.apply_roi_offset_to_subcoord(
                sub_coord=bbox_sub,
                roi_offset_phys=region_offset_phys
            )
            
            formatted_results.append({
                'text': text.strip(),
                'bbox': bbox_sub,
                'bbox_orig_phys': bbox_orig_phys,  # 使用公用方法计算的原图物理坐标
                'confidence': float(confidence)
            })

        # 核心匹配逻辑（不变）
        best_match_phys = None
        highest_confidence = 0.0
        exact_matches = []
        target_text_normalized = target_text_clean.replace(" ", "")
        
        for res in formatted_results:
            res_text_normalized = res['text'].replace(" ", "")
            if res_text_normalized == target_text_normalized:
                exact_matches.append(res)
                if res['confidence'] > highest_confidence:
                    highest_confidence = res['confidence']
                self.logger.debug(
                    f"找到精确匹配 | 识别文本: '{res['text']}' | 置信度: {res['confidence']:.4f} | "
                    f"是否达阈值({min_confidence}): {'是' if res['confidence'] >= min_confidence else '否'} | "
                    f"原图物理坐标: {res['bbox_orig_phys']}"
                )
        
        if exact_matches:
            if len(exact_matches) > 1:
                self.logger.debug(f"找到{len(exact_matches)}个精确匹配结果，选择置信度最高的")
                exact_matches.sort(key=lambda x: x['confidence'], reverse=True)
            
            best_match = exact_matches[0]
            best_match_phys = best_match['bbox_orig_phys']
            highest_confidence = best_match['confidence']
            
            if highest_confidence >= min_confidence:
                match_info = f"置信度达标({highest_confidence:.4f} ≥ {min_confidence})"
            else:
                match_info = f"置信度未达阈值({highest_confidence:.4f} < {min_confidence})，但文本完全一致"
        else:
            all_recognized = [f"{r['text']}({r['confidence']:.2f})" for r in formatted_results]
            self.logger.warning(
                f"未找到目标文本的精确匹配: '{target_text_clean}' | "
                f"所有识别结果: {all_recognized} | 阈值: {min_confidence} | "
                f"裁剪后子图尺寸: {cropped_image.shape[1]}x{cropped_image.shape[0]}"  # 新增：日志补充子图尺寸，方便调试
            )
            if self.test_mode:
                self.debug_saver.save_ocr_debug(
                    orig_image=orig_image,
                    target_text=target_text_clean,
                    is_success=False,
                    match_score=highest_confidence,
                    min_confidence=min_confidence,
                    is_fullscreen=is_fullscreen,
                    ocr_results=formatted_results,
                    target_bbox_phys=None,
                    orig_region_phys=orig_region_phys,
                    region_offset_phys=region_offset_phys
                )
            return None

        # 测试模式保存图片（不变）
        if self.test_mode:
            self.debug_saver.save_ocr_debug(
                orig_image=orig_image,
                target_text=target_text_clean,
                is_success=True,
                match_score=highest_confidence,
                min_confidence=min_confidence,
                is_fullscreen=is_fullscreen,
                ocr_results=formatted_results,
                target_bbox_phys=best_match_phys,
                orig_region_phys=orig_region_phys,
                region_offset_phys=region_offset_phys
            )

        # ------------------------------ 复用CoordinateTransformer的矩形边界限制 + 全屏/窗口统一转换 ------------------------------
        if best_match_phys:
            # 新增：统一转换物理矩形为逻辑矩形（自动适配全屏/窗口）
            final_bbox_log = self.coord_transformer.get_unified_logical_rect(best_match_phys)
            
            # 保留原有物理坐标返回（兼容上层使用）
            final_bbox_phys = best_match_phys

            self.logger.info(
                f"找到目标文本（精确匹配） | 文本: '{target_text_clean}' | {match_info} | "
                f"逻辑坐标: {final_bbox_log} | 物理坐标: {final_bbox_phys} | "
                f"匹配结果数: {len(exact_matches)}"
            )
            return (final_bbox_log, final_bbox_phys)
        else:
            return None