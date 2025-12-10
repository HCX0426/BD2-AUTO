import os
import cv2
import numpy as np
from auto_control.base_ocr import BaseOCR
from .config import (convert_lang_code,
                     get_default_languages, get_engine_config,
                     validate_lang_combination)

from typing import Dict, List

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

        # 调试目录
        self.debug_img_dir = os.path.join(os.getcwd(), "debug", "ocr_image")
        os.makedirs(self.debug_img_dir, exist_ok=True)
        self.logger.info(f"调试图片保存目录: {self.debug_img_dir}")

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
            
            if formatted_results:
                save_filename = f"easyocr_{lang}_match.png"
                save_path = os.path.join(self.debug_img_dir, save_filename)
                self._save_ocr_debug_image(image, formatted_results, save_path)

            self.logger.info(f"文本检测完成 | 有效结果数量: {len(formatted_results)}")
            return formatted_results

        except Exception as e:
            self.logger.warning(f"EasyOCR文本检测失败: {str(e)}", exc_info=True)
            return []

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
            
            for idx, results in enumerate(formatted_batch_results, 1):
                if results:
                    save_filename = f"easyocr_batch_{idx}_{lang}_match.png"
                    save_path = os.path.join(self.debug_img_dir, save_filename)
                    self._save_ocr_debug_image(images[idx-1], results, save_path)

            self.logger.info("批量处理全部完成")
            return formatted_batch_results

        except Exception as e:
            self.logger.error(f"EasyOCR批量处理失败: {str(e)}", exc_info=True)
            return []


    def _save_ocr_debug_image(self, original_image: np.ndarray, results: List[Dict], save_path: str) -> None:
        """
        根据OCR结果保存带有标记的调试图像。
        :param original_image: 原始图像
        :param results: OCR识别的结果列表
        :param save_path: 调试图像保存路径
        """
        try:
            debug_image = cv2.cvtColor(original_image, cv2.COLOR_GRAY2BGR) if len(original_image.shape) == 2 else original_image.copy()
            
            for result in results:
                x, y, w, h = result['bbox']
                text = result['text']
                confidence = result['confidence']
                
                # 绘制矩形框和文本信息
                cv2.rectangle(debug_image, (x, y), (x + w, y + h), (0, 0, 255), 2)
                cv2.putText(debug_image, f"{text} ({confidence:.2f})", (x, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

            cv2.imwrite(save_path, debug_image)
            self.logger.info(f"OCR调试图片保存成功: {save_path}")
        except Exception as e:
            self.logger.error(f"保存OCR调试图片失败: {str(e)}", exc_info=True)
