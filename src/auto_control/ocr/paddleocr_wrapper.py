import importlib
from typing import Dict, List

import cv2
import numpy as np

from src.auto_control.config.ocr_config import (
    convert_lang_code,
    get_default_languages,
    get_engine_config,
    validate_lang_combination,
)
from src.auto_control.ocr.base_ocr import BaseOCR


class PaddleOCRWrapper(BaseOCR):
    def __init__(self, logger=None):
        """
        PaddleOCR实现（封装PaddleOCR库，使用轻量版）
        :param logger: 日志实例
        """
        super().__init__(logger=logger)

        # 延迟导入paddleocr
        import paddleocr

        # 加载引擎配置
        config = get_engine_config("paddleocr")
        gpu_config = config["gpu"]
        if gpu_config == "auto":
            # 自动检测GPU可用性
            self._use_gpu = self._check_gpu_available()
        else:
            # 强制启用/禁用（但启用前仍需检测可用性）
            self._use_gpu = gpu_config and self._check_gpu_available()
        self.timeout = config["timeout"]
        self.model_dir = config.get("model_dir")
        self.use_lightweight = config.get("use_lightweight", True)  # 默认使用轻量版

        # 初始化默认语言
        default_langs = get_default_languages("paddleocr").split("+")
        self._lang_list = self._convert_lang_param(default_langs)
        self._current_lang = "+".join(default_langs)

        # 创建PaddleOCR实例（使用轻量版）
        self.ocr = paddleocr.PaddleOCR(
            use_angle_cls=True,  # 启用角度分类器
            lang=self._lang_list[0],  # PaddleOCR只支持单个语言参数
            use_gpu=self._use_gpu,
            det_model_dir=None,  # 使用默认模型
            rec_model_dir=None,  # 使用默认模型
            cls_model_dir=None,  # 使用默认模型
            det_db_thresh=0.3,  # 检测阈值
            det_db_box_thresh=0.5,  # 框阈值
            det_db_unclip_ratio=2.0,  # 非裁剪比率
            use_onnx=False,  # 不使用ONNX
            ocr_version="PP-OCRv4" if self.use_lightweight else "PP-OCRv4",  # 使用最新版本
        )

        self.logger.debug(
            f"PaddleOCR实例初始化完成 | "
            f"默认语言: {self._current_lang} | "
            f"GPU加速: {'启用' if self._use_gpu else '禁用'} | "
            f"轻量版: {'是' if self.use_lightweight else '否'} | "
            f"模型目录: {self.model_dir or '默认目录'}"
        )

    def _convert_lang_param(self, langs: List[str]) -> List[str]:
        """将语言参数转换为PaddleOCR支持的格式"""
        # 验证语言组合合法性
        validated_langs = validate_lang_combination(langs, "paddleocr")
        # 转换语言代码
        converted_langs = [convert_lang_code(lang, "paddleocr") for lang in validated_langs]

        self.logger.debug(f"语言参数转换 | 原始: {langs} → 转换后: {converted_langs}")
        return converted_langs

    def _check_gpu_available(self) -> bool:
        """检测GPU是否可用（依赖PaddlePaddle）"""
        try:
            torch_spec = importlib.util.find_spec("torch")
            paddle_spec = importlib.util.find_spec("paddle")
            
            if paddle_spec is None:
                # 如果找不到paddle模块，则没有GPU支持
                return False

            import paddle

            available = paddle.is_compiled_with_cuda() and paddle.device.get_device() != 'cpu'
            self.logger.debug(f"GPU可用性检测 | 可用: {available} | 设备: {paddle.device.get_device()}")
            return available
        except ImportError:
            self.logger.warning("未安装PaddlePaddle，无法使用GPU加速")
            return False

    def detect_text(self, image: np.ndarray, lang: str) -> List[Dict]:
        """检测文本位置及内容"""
        try:
            # 切换语言（如果与当前语言不同）
            if lang != self._current_lang:
                self._current_lang = lang
                self._lang_list = self._convert_lang_param(lang.split("+"))
                self.logger.info(f"切换OCR语言: {lang}")
                
                # 重新初始化PaddleOCR实例以更改语言
                import paddleocr
                self.ocr = paddleocr.PaddleOCR(
                    use_angle_cls=True,
                    lang=self._lang_list[0],  # PaddleOCR只支持单个语言参数
                    use_gpu=self._use_gpu,
                    det_db_thresh=0.3,
                    det_db_box_thresh=0.5,
                    det_db_unclip_ratio=2.0,
                    use_onnx=False,
                    ocr_version="PP-OCRv4" if self.use_lightweight else "PP-OCRv4",
                )

            height, width = image.shape[:2]  # 获取图像的高度和宽度
            self.logger.debug(
                f"开始文本检测 | 语言: {lang} | 图像尺寸: ({width}, {height}) | "
                f"GPU加速: {'启用' if self._use_gpu else '禁用'}"
            )

            # 调用PaddleOCR识别
            raw_results = self.ocr.ocr(image, cls=True)

            # 格式化结果（统一输出格式）
            formatted_results = []
            if raw_results and len(raw_results) > 0:
                for line in raw_results[0]:
                    bbox, (text, confidence) = line
                    
                    # 从多边形边界框转换为矩形边界框
                    x_coords = [int(point[0]) for point in bbox]
                    y_coords = [int(point[1]) for point in bbox]
                    x = min(x_coords)
                    y = min(y_coords)
                    w = max(x_coords) - x
                    h = max(y_coords) - y

                    formatted_results.append({"text": text.strip(), "bbox": (x, y, w, h), "confidence": float(confidence)})

            # 日志添加最高置信度信息
            if formatted_results:
                max_confidence = max([r["confidence"] for r in formatted_results])
                self.logger.info(
                    f"文本检测完成 | 有效结果数量: {len(formatted_results)} | 最高置信度: {max_confidence:.2f}"
                )
            else:
                self.logger.info(f"文本检测完成 | 有效结果数量: 0")

            return formatted_results

        except Exception as e:
            self.logger.warning(f"PaddleOCR文本检测失败: {str(e)}", exc_info=True)
            return []

    def batch_process(self, images: List[np.ndarray], lang: str) -> List[List[Dict]]:
        """批量处理多张图像"""
        try:
            # 切换语言（如果需要）
            if lang != self._current_lang:
                self._current_lang = lang
                self._lang_list = self._convert_lang_param(lang.split("+"))
                self.logger.info(f"批量处理语言切换: {lang}")
                
                # 重新初始化PaddleOCR实例以更改语言
                import paddleocr
                self.ocr = paddleocr.PaddleOCR(
                    use_angle_cls=True,
                    lang=self._lang_list[0],  # PaddleOCR只支持单个语言参数
                    use_gpu=self._use_gpu,
                    det_db_thresh=0.3,
                    det_db_box_thresh=0.5,
                    det_db_unclip_ratio=2.0,
                    use_onnx=False,
                    ocr_version="PP-OCRv4" if self.use_lightweight else "PP-OCRv4",
                )

            self.logger.info(f"开始批量处理 | 图像总数: {len(images)} | 语言: {lang}")

            # 格式化批量结果
            formatted_batch_results = []
            for idx, image in enumerate(images, 1):
                # 对每张图像单独调用OCR
                raw_results = self.ocr.ocr(image, cls=True)
                formatted = []
                
                if raw_results and len(raw_results) > 0:
                    for line in raw_results[0]:
                        bbox, (text, confidence) = line
                        x_coords = [int(point[0]) for point in bbox]
                        y_coords = [int(point[1]) for point in bbox]
                        x = min(x_coords)
                        y = min(y_coords)
                        w = max(x_coords) - x
                        h = max(y_coords) - y

                        formatted.append({"text": text.strip(), "bbox": (x, y, w, h), "confidence": float(confidence)})
                
                formatted_batch_results.append(formatted)
                self.logger.debug(f"批量图像 {idx}/{len(images)} 处理完成 | 结果数: {len(formatted)}")

            self.logger.info("批量处理全部完成")
            return formatted_batch_results

        except Exception as e:
            self.logger.error(f"PaddleOCR批量处理失败: {str(e)}", exc_info=True)
            return []
