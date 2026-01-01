import datetime
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from src.auto_control.config.ocr_config import get_default_languages
from src.auto_control.ocr.base_ocr import BaseOCR
from src.auto_control.ocr.easyocr_wrapper import EasyOCRWrapper
from src.auto_control.ocr.paddleocr_wrapper import PaddleOCRWrapper
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.debug_image_saver import DebugImageSaver
from src.auto_control.utils.display_context import RuntimeDisplayContext
from src.core.path_manager import path_manager


class OCRProcessor:
    """
    OCR处理器封装类，统一调用不同OCR引擎并集成坐标转换能力。
    核心特性：
    1. 引擎适配：当前支持EasyOCR和PaddleOCR，可扩展其他OCR引擎
    2. 坐标联动：集成CoordinateTransformer实现物理/逻辑坐标自动转换
    3. 调试能力：支持测试模式，自动保存识别过程的调试图片
    4. 参数统一：基于RuntimeDisplayContext获取全局显示状态，保证数据源唯一
    """

    def __init__(
        self,
        engine: str = "easyocr",
        logger=None,
        coord_transformer: CoordinateTransformer = None,
        display_context: RuntimeDisplayContext = None,
        test_mode: bool = False,
        stop_event=None,
        **kwargs,
    ):
        """
        初始化OCR处理器

        Args:
            engine: OCR引擎类型，支持 'easyocr'（默认）和 'paddleocr'
            logger: 日志实例（必填，用于输出识别过程和错误信息）
            coord_transformer: 坐标转换器实例（必填，处理坐标转换）
            display_context: 运行时显示上下文（必填，提供窗口/屏幕状态）
            test_mode: 测试模式开关（是否保存调试图片，默认False）
            **kwargs: 引擎扩展参数：
                - languages: 自定义识别语言组合（如 'ch_tra+eng'）
        Raises:
            ValueError: 必传参数缺失/类型错误、引擎类型不支持
        """
        # 必传参数校验
        if not logger:
            raise ValueError("初始化失败：logger不能为空")
        if not isinstance(coord_transformer, CoordinateTransformer):
            raise ValueError("初始化失败：coord_transformer必须是CoordinateTransformer实例")
        if not isinstance(display_context, RuntimeDisplayContext):
            raise ValueError("初始化失败：display_context必须是RuntimeDisplayContext实例")

        # 引擎类型校验
        self.engine_type = engine.lower()
        if self.engine_type not in ["easyocr", "paddleocr"]:
            raise ValueError(f"不支持的OCR引擎: {engine}，仅支持 'easyocr' 和 'paddleocr'")

        # 核心属性初始化
        self.logger = logger
        self.coord_transformer = coord_transformer
        self.display_context = display_context  # 全局显示状态容器
        self.test_mode = test_mode
        self.stop_event = stop_event

        # 语言配置（默认/自定义）
        self._default_lang = kwargs.pop("languages", None) or get_default_languages(self.engine_type)

        # OCR识别结果缓存
        self.ocr_cache = {}
        self.ocr_cache_expire = 3.0  # 缓存过期时间（秒）
        self.max_ocr_cache_size = 50  # 最大缓存数量

        # 调试工具初始化
        self.debug_saver = DebugImageSaver(
            logger=self.logger, debug_dir=path_manager.get("match_ocr_debug"), test_mode=test_mode
        )

        # 初始化OCR引擎
        self.engine: BaseOCR = self._init_engine()

        # 初始化完成日志
        self.logger.info(
            f"OCR处理器初始化完成 | 引擎: {self.engine_type.upper()} | "
            f"默认语言: {self._default_lang} | GPU加速: {'启用' if self.engine._use_gpu else '禁用'} | "
            f"坐标系统: 已配置 | 测试模式: {'启用（清空历史调试图）' if self.test_mode else '禁用'}"
        )

    def _init_engine(self) -> BaseOCR:
        """
        初始化具体OCR引擎实例

        Returns:
            BaseOCR: OCR引擎基类实例（EasyOCRWrapper或PaddleOCRWrapper）
        Raises:
            ValueError: 引擎类型不支持
        """
        self.logger.debug(f"初始化{self.engine_type.upper()}引擎")

        if self.engine_type == "easyocr":
            return EasyOCRWrapper(logger=self.logger)
        elif self.engine_type == "paddleocr":
            return PaddleOCRWrapper(logger=self.logger)
        else:
            raise ValueError(f"不支持的OCR引擎: {self.engine_type}")

    def enable_gpu(self, enable: bool = True):
        """
        启用/禁用GPU加速

        Args:
            enable: True=启用，False=禁用（默认True）
        """
        return self.engine.enable_gpu(enable)

    def _generate_image_hash(self, image: np.ndarray) -> str:
        """
        生成图像的哈希值，用于缓存键

        Args:
            image: 输入图像（numpy数组）

        Returns:
            str: 图像的哈希值
        """
        import hashlib

        # 将图像转换为一维数组并计算MD5哈希
        image_bytes = image.tobytes()
        return hashlib.md5(image_bytes).hexdigest()

    def _cleanup_ocr_cache(self) -> None:
        """
        清理过期的OCR缓存
        """
        import time

        current_time = time.time()

        # 清理过期缓存
        expired_keys = [
            key for key, (_, timestamp) in self.ocr_cache.items() if current_time - timestamp > self.ocr_cache_expire
        ]

        for key in expired_keys:
            del self.ocr_cache[key]
            self.logger.debug(f"清理过期OCR缓存: {key[:20]}...")

        # 如果缓存数量仍超过最大值，清理最早的缓存
        if len(self.ocr_cache) > self.max_ocr_cache_size:
            sorted_keys = sorted(self.ocr_cache.items(), key=lambda x: x[1][1])

            keys_to_remove = len(self.ocr_cache) - self.max_ocr_cache_size
            for key, _ in sorted_keys[:keys_to_remove]:
                del self.ocr_cache[key]
                self.logger.debug(f"清理OCR缓存: {key[:20]}...")

    def find_text_position(
        self,
        image: np.ndarray,
        target_text: str,
        lang: Optional[str] = None,
        min_confidence: float = 0.9,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        查找目标文本在图像中的位置，返回逻辑坐标

        Args:
            image: 输入图像（numpy数组）
            target_text: 待查找的目标文本
            lang: 识别语言（默认使用初始化配置的语言）
            min_confidence: 最小置信度阈值（默认0.9）
            region: 识别区域ROI (x, y, w, h)（基于原始基准分辨率）

        Returns:
            Optional[Tuple[int, int, int, int]]:
                逻辑坐标矩形 - 匹配成功；None - 匹配失败
        """
        import time

        current_time = time.time()

        # 清理过期缓存
        self._cleanup_ocr_cache()

        # 1. 语言配置处理
        target_lang = lang or self._default_lang
        if target_lang and "ch_sim" not in target_lang:
            target_lang = f"ch_sim+{target_lang}"
        elif not target_lang:
            target_lang = "ch_sim"

        # 2. 生成缓存键
        image_hash = self._generate_image_hash(image)
        cache_key = f"{image_hash}_{target_text}_{target_lang}_{min_confidence}_{region}"

        # 3. 检查缓存
        if cache_key in self.ocr_cache:
            cached_result, timestamp = self.ocr_cache[cache_key]
            if current_time - timestamp <= self.ocr_cache_expire:
                self.logger.debug(f"使用OCR缓存 | 目标文本: '{target_text}'")
                return cached_result

        # 4. 缓存未命中，继续执行识别

        # 2. 基础参数校验
        if image is None or image.size == 0:
            self.logger.error("查找文本失败：输入图像无效")
            return None

        target_text_clean = target_text.strip()
        if not target_text_clean:
            self.logger.error("查找文本失败：目标文本为空")
            return None

        # 3. 基础参数获取
        img_h, img_w = image.shape[:2]
        orig_image = image.copy()
        is_fullscreen = self.display_context.is_fullscreen

        # 4. ROI处理（坐标转换+安全扩展）
        processed_region_phys, region_offset_phys = self.coord_transformer.process_roi(
            roi=region, boundary_width=img_w, boundary_height=img_h, enable_expand=True, expand_pixel=10
        )
        orig_region_phys = processed_region_phys

        # 5. 图像裁剪
        cropped_image = orig_image
        if processed_region_phys:
            rx_phys, ry_phys, rw_phys, rh_phys = processed_region_phys
            cropped_image = orig_image[ry_phys : ry_phys + rh_phys, rx_phys : rx_phys + rw_phys]

            # 裁剪有效性检查
            if cropped_image.size == 0:
                self.logger.warning(
                    f"ROI裁剪后子图为空，切换全图识别 | 原始ROI: {region} | 处理后ROI: {processed_region_phys}"
                )
                cropped_image = orig_image
                region_offset_phys = (0, 0)
                orig_region_phys = None
            else:
                self.logger.debug(f"图像裁剪完成 | 子图尺寸: {cropped_image.shape[1]}x{cropped_image.shape[0]}")
        else:
            self.logger.debug(f"全图识别 | 原图尺寸: {img_w}x{img_h}")

        # 6. OCR识别前检查是否需要停止
        if self.stop_event and self.stop_event.is_set():
            self.logger.debug("OCR识别被中断：收到停止信号")
            return None

        # 7. OCR识别
        formatted_results = []

        # 根据引擎类型选择不同的识别方法
        if self.engine_type == "easyocr":
            # EasyOCR需要RGB格式图像
            image_rgb = cv2.cvtColor(cropped_image, cv2.COLOR_BGR2RGB)

            # 使用线程执行OCR识别，支持中断
            from threading import Event, Thread

            result_event = Event()
            raw_results = []

            def ocr_worker():
                nonlocal raw_results
                try:
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
                        workers=0,
                    )
                    result_event.set()
                except Exception as e:
                    self.logger.error(f"OCR识别异常: {str(e)}")
                    result_event.set()

            # 启动OCR线程
            ocr_thread = Thread(target=ocr_worker, daemon=True)
            ocr_thread.start()

            # 等待识别完成或停止信号
            while not result_event.is_set():
                if self.stop_event and self.stop_event.is_set():
                    self.logger.debug("OCR识别过程中被中断：收到停止信号")
                    return None
                # 短暂休眠，避免CPU占用过高
                from time import sleep

                sleep(0.1)

            # OCR识别后检查是否需要停止
            if self.stop_event and self.stop_event.is_set():
                self.logger.debug("OCR识别完成后被中断：收到停止信号")
                return None

            # 识别结果格式化（子图→原图坐标转换）
            for result in raw_results:
                # 检查是否需要停止
                if self.stop_event and self.stop_event.is_set():
                    self.logger.debug("OCR结果处理被中断：收到停止信号")
                    return None

                bbox, text, confidence = result[:3]
                # 子图内物理坐标计算
                x_coords = [int(point[0]) for point in bbox]
                y_coords = [int(point[1]) for point in bbox]
                x_phys_sub = min(x_coords)
                y_phys_sub = min(y_coords)
                w_phys_sub = max(x_coords) - x_phys_sub
                h_phys_sub = max(y_coords) - y_phys_sub

                # 子图坐标→原图物理坐标
                bbox_sub = (x_phys_sub, y_phys_sub, w_phys_sub, h_phys_sub)
                bbox_orig_phys = self.coord_transformer.apply_roi_offset_to_subcoord(
                    sub_coord=bbox_sub, roi_offset_phys=region_offset_phys
                )

                formatted_results.append(
                    {
                        "text": text.strip(),
                        "bbox": bbox_sub,
                        "bbox_orig_phys": bbox_orig_phys,
                        "confidence": float(confidence),
                    }
                )
        elif self.engine_type == "paddleocr":
            # 直接使用PaddleOCRWrapper的detect_text方法
            # 注意：这里已经在detect_text方法中处理了语言切换和异常捕获
            raw_results = self.engine.detect_text(cropped_image, target_lang)

            # 检查是否需要停止
            if self.stop_event and self.stop_event.is_set():
                self.logger.info("OCR识别完成后被中断：收到停止信号")
                return None

            # 格式化结果，添加原图物理坐标
            for result in raw_results:
                text = result["text"]
                bbox_sub = result["bbox"]
                confidence = result["confidence"]

                # 子图坐标→原图物理坐标
                bbox_orig_phys = self.coord_transformer.apply_roi_offset_to_subcoord(
                    sub_coord=bbox_sub, roi_offset_phys=region_offset_phys
                )

                formatted_results.append(
                    {
                        "text": text.strip(),
                        "bbox": bbox_sub,
                        "bbox_orig_phys": bbox_orig_phys,
                        "confidence": float(confidence),
                    }
                )

        # 8. 匹配逻辑：精确匹配 + 部分匹配
        best_match_phys = None
        highest_confidence = 0.0
        exact_matches = []
        partial_matches = []
        target_text_normalized = target_text_clean.replace(" ", "")

        for res in formatted_results:
            res_text_normalized = res["text"].replace(" ", "")

            # 精确匹配
            if res_text_normalized == target_text_normalized:
                exact_matches.append(res)
                if res["confidence"] > highest_confidence:
                    highest_confidence = res["confidence"]
                self.logger.debug(
                    f"精确匹配文本: '{res['text']}' | 置信度: {res['confidence']:.4f} | "
                    f"达标({min_confidence}): {'是' if res['confidence'] >= min_confidence else '否'} | "
                    f"物理坐标: {res['bbox_orig_phys']}"
                )
            # 部分匹配：目标文本是识别文本的子字符串
            elif target_text_normalized in res_text_normalized:
                partial_matches.append(res)
                if res["confidence"] > highest_confidence:
                    highest_confidence = res["confidence"]
                self.logger.debug(
                    f"部分匹配文本: '{res['text']}' | 置信度: {res['confidence']:.4f} | "
                    f"达标({min_confidence}): {'是' if res['confidence'] >= min_confidence else '否'} | "
                    f"物理坐标: {res['bbox_orig_phys']}"
                )

        # 9. 匹配结果处理
        match_info = ""
        best_matches = []

        # 优先使用精确匹配结果
        if exact_matches:
            best_matches = exact_matches
            match_type = "精确匹配"
        # 精确匹配失败时使用部分匹配结果
        elif partial_matches:
            best_matches = partial_matches
            match_type = "部分匹配"
        else:
            # 未找到匹配
            all_recognized = [f"{r['text']}({r['confidence']:.2f})" for r in formatted_results]
            self.logger.warning(
                f"未找到目标文本: '{target_text_clean}' | 识别结果: {all_recognized} | "
                f"阈值: {min_confidence} | 子图尺寸: {cropped_image.shape[1]}x{cropped_image.shape[0]}"
            )

            # 测试模式保存失败调试图
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
                    region_offset_phys=region_offset_phys,
                )
            return None

        # 从最佳匹配中选择置信度最高的结果
        best_match = max(best_matches, key=lambda x: x["confidence"])
        best_match_phys = best_match["bbox_orig_phys"]
        match_info = f"匹配类型: {match_type} | 置信度: {best_match['confidence']:.4f}"

        # 10. 测试模式保存成功调试图
        if self.test_mode:
            self.debug_saver.save_ocr_debug(
                orig_image=orig_image,
                target_text=target_text_clean,
                is_success=True,
                match_score=best_match["confidence"],
                min_confidence=min_confidence,
                is_fullscreen=is_fullscreen,
                ocr_results=formatted_results,
                target_bbox_phys=best_match_phys,
                orig_region_phys=orig_region_phys,
                region_offset_phys=region_offset_phys,
            )

        # 11. 最终坐标处理（物理→逻辑转换+边界限制）
        if best_match_phys:
            # 物理坐标→统一逻辑坐标
            final_bbox_log = self.coord_transformer.get_unified_logical_rect(best_match_phys)
            # 逻辑坐标边界限制 - 根据全屏状态使用不同的边界值
            if is_fullscreen:
                # 全屏模式：使用屏幕物理分辨率作为边界
                boundary_width, boundary_height = self.display_context.screen_physical_res
            else:
                # 窗口模式：使用客户区逻辑分辨率作为边界
                boundary_width = self.display_context.client_logical_width
                boundary_height = self.display_context.client_logical_height

            final_bbox_log = self.coord_transformer.limit_rect_to_boundary(
                rect=final_bbox_log,
                boundary_width=boundary_width,
                boundary_height=boundary_height,
            )

            self.logger.info(
                f"找到目标文本 | 文本: '{target_text_clean}' | {match_info} | "
                f"逻辑坐标: {final_bbox_log} | "
                f"匹配数: {len(exact_matches)} | 显示模式: {'全屏' if is_fullscreen else '窗口'}"
            )

            # 更新缓存
            self.ocr_cache[cache_key] = (final_bbox_log, current_time)
            self.logger.debug(f"更新OCR缓存 | 键: {cache_key[:20]}...")

            return final_bbox_log
        else:
            # 更新缓存，即使未找到匹配结果
            self.ocr_cache[cache_key] = (None, current_time)
            self.logger.debug(f"更新OCR缓存 | 键: {cache_key[:20]}... | 结果: None")

            return None
