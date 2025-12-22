import datetime
import logging
import os
from typing import List, Dict, Optional, Tuple, Union
import cv2
import numpy as np


class DebugImageSaver:
    """公共调试图保存工具类：统一模板匹配/OCR识别的调试图标注风格和保存逻辑"""

    def __init__(self, logger: logging.Logger, debug_dir: str, test_mode: bool = False):
        """
        初始化调试图保存工具
        :param logger: 日志实例（从上层处理器传入）
        :param debug_dir: 调试图保存目录
        :param test_mode: 测试模式（是否清空历史图）
        """
        self.logger = logger
        self.debug_dir = debug_dir
        self.test_mode = test_mode

        # 确保调试目录存在
        os.makedirs(self.debug_dir, exist_ok=True)

        # 测试模式：清空历史调试图
        if self.test_mode:
            self._clear_debug_dir()

        # 统一标注样式配置（修复文本类样式的格式错误：color改为三元组，确保lineType是整数）
        self.style = {
            "roi_rect": (255, 0, 0, 2, cv2.LINE_AA),  # 蓝色虚线：ROI区域（color拆分为三通道，兼容rectangle）
            "match_rect": (0, 0, 255, 2, cv2.LINE_AA),  # 红色实线：匹配区域
            "target_rect": (0, 255, 0, 2, cv2.LINE_AA),  # 绿色实线：OCR目标文本区域
            "center_point": (0, 255, 0, 4, -1, cv2.LINE_AA),  # 绿色实心点：中心坐标
            # 文本类样式修复：color为三元组，顺序：(color, font_scale, thickness, line_type)
            "text_success": ((0, 255, 0), 0.5, 1, cv2.LINE_AA),  # 绿色：成功状态文本
            "text_fail": ((0, 0, 255), 0.5, 1, cv2.LINE_AA),  # 红色：失败状态文本
            "text_info": ((255, 255, 255), 0.4, 1, cv2.LINE_AA),  # 白色：辅助信息文本
            "text_small": ((255, 255, 255), 0.35, 1, cv2.LINE_AA),  # 白色小字体：文本内容标注
        }

    def _clear_debug_dir(self) -> None:
        """清空调试目录下的所有PNG格式调试图（复用原有逻辑）"""
        try:
            total_count = 0
            deleted_count = 0
            failed_files = []

            for filename in os.listdir(self.debug_dir):
                file_path = os.path.join(self.debug_dir, filename)
                if os.path.isfile(file_path) and filename.lower().endswith(".png"):
                    total_count += 1
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                        self.logger.debug(f"已删除历史调试图: {filename}")
                    except Exception as e:
                        failed_files.append(f"{filename}（错误：{str(e)}）")

            log_msg = (
                f"测试模式 - 清空调试目录完成 | "
                f"目录: {self.debug_dir} | "
                f"总调试图数: {total_count} | "
                f"成功删除: {deleted_count} | "
                f"删除失败: {len(failed_files)}"
            )
            if failed_files:
                log_msg += f" | 失败文件: {failed_files}"
            self.logger.info(log_msg)

        except Exception as e:
            self.logger.error(f"清空调试目录异常: {str(e)}", exc_info=True)

    def _draw_text(self, img: np.ndarray, text: str, pos: Tuple[int, int], style_key: str) -> None:
        """通用文本绘制方法（根据style_key读取统一样式）- 修复参数取值顺序"""
        # 从样式中正确取出：颜色（三元组）、字体缩放、厚度、线型（均为整数）
        color, font_scale, thickness, line_type = self.style[style_key]
        cv2.putText(
            img, text, pos, cv2.FONT_HERSHEY_SIMPLEX,
            font_scale, color, thickness, line_type
        )

    def save_template_debug(
        self,
        orig_image: np.ndarray,
        template_name: str,
        is_success: bool,
        match_score: float,
        threshold: float,
        is_fullscreen: bool,
        orig_roi_phys: Optional[Tuple[int, int, int, int]] = None,
        processed_roi: Optional[Tuple[int, int, int, int]] = None,
        match_bbox_phys: Optional[Tuple[int, int, int, int]] = None,
        center_phys: Optional[Tuple[int, int]] = None,
        final_bbox_log: Optional[Tuple[int, int, int, int]] = None,
        template_orig_size: Optional[Tuple[int, int]] = None,
        template_scaled_size: Optional[Tuple[int, int]] = None
    ) -> None:
        """
        保存模板匹配调试图（对应ImageProcessor的需求）
        :param orig_image: 原始输入图像（BGR格式）
        :param template_name: 模板名称
        :param is_success: 匹配是否成功
        :param match_score: 匹配分数
        :param threshold: 匹配阈值
        :param is_fullscreen: 是否全屏模式
        :param orig_roi_phys: ROI物理坐标（x,y,w,h）
        :param processed_roi: ROI逻辑坐标（窗口模式用）
        :param match_bbox_phys: 匹配区域物理坐标
        :param center_phys: 匹配区域中心物理坐标
        :param final_bbox_log: 匹配区域逻辑坐标
        :param template_orig_size: 模板原始尺寸（宽,高）
        :param template_scaled_size: 模板缩放后尺寸（宽,高）
        """
        try:
            debug_img = orig_image.copy()
            img_h, img_w = debug_img.shape[:2]
            timestamp = datetime.datetime.now().strftime("%H%M%S%f")[:-3]
            safe_name = template_name.replace("/", "_").replace("\\", "_")
            img_type = "match_success" if is_success else "match_fail"
            save_path = os.path.join(self.debug_dir, f"{img_type}_{safe_name}_{timestamp}.png")

            # 1. 标注ROI区域
            if orig_roi_phys:
                rx, ry, rw, rh = orig_roi_phys
                color, thickness, line_type = self.style["roi_rect"][:3]
                cv2.rectangle(debug_img, (rx, ry), (rx+rw, ry+rh), color, thickness, line_type)
                self._draw_text(debug_img, "Original ROI", (rx+5, ry+20), "text_info")
                # 窗口模式标注逻辑坐标
                if not is_fullscreen and processed_roi:
                    self._draw_text(debug_img, f"ROI(Log): {processed_roi}", (rx+5, ry+40), "text_small")

            # 2. 标注顶部状态信息
            top_texts = [
                f"Template: {template_name}",
                f"Status: {'Match Success' if is_success else 'Match Failed'}",
                f"Score: {match_score:.4f} | Threshold: {threshold}",
                f"Mode: {'Fullscreen' if is_fullscreen else 'Window'}"
            ]
            text_style = "text_success" if is_success else "text_fail"
            y_offset = 30
            for text in top_texts:
                self._draw_text(debug_img, text, (10, y_offset), text_style)
                y_offset += 20

            # 3. 匹配成功：标注匹配区域、中心坐标、详细参数
            if is_success:
                # 匹配区域矩形
                if match_bbox_phys:
                    mx, my, mw, mh = match_bbox_phys
                    color, thickness, line_type = self.style["match_rect"][:3]
                    cv2.rectangle(debug_img, (mx, my), (mx+mw, my+mh), color, thickness, line_type)
                    self._draw_text(debug_img, "Matched Area", (mx+5, my+20), "text_info")

                # 中心坐标点
                if center_phys:
                    cx, cy = center_phys
                    color, radius, thickness, line_type = self.style["center_point"][:4]
                    cv2.circle(debug_img, (cx, cy), radius, color, thickness, line_type)
                    self._draw_text(debug_img, f"Center(Phys): ({cx},{cy})", (cx+10, cy-10), "text_small")

                # 底部详细参数
                bottom_texts = []
                if match_bbox_phys:
                    bottom_texts.append(f"Matched(Phys): {match_bbox_phys}")
                if final_bbox_log:
                    bottom_texts.append(f"Matched(Log): {final_bbox_log}")
                if template_orig_size and template_scaled_size:
                    bottom_texts.append(
                        f"Template Size: Orig({template_orig_size[0]},{template_orig_size[1]}) | "
                        f"Scaled({template_scaled_size[0]},{template_scaled_size[1]})"
                    )

                y_offset = img_h - 30
                for text in reversed(bottom_texts):
                    self._draw_text(debug_img, text, (10, y_offset), "text_info")
                    y_offset -= 20

            # 保存图片
            cv2.imwrite(save_path, debug_img)
            self.logger.debug(f"模板匹配调试图已保存: {save_path}")

        except Exception as e:
            self.logger.error(f"保存模板匹配调试图异常 | 模板: {template_name} | 错误: {str(e)}", exc_info=True)

    def save_ocr_debug(
        self,
        orig_image: np.ndarray,
        target_text: str,
        is_success: bool,
        match_score: float,
        min_confidence: float,
        is_fullscreen: bool,
        ocr_results: List[Dict],
        target_bbox_phys: Optional[Tuple[int, int, int, int]] = None,
        orig_region_phys: Optional[Tuple[int, int, int, int]] = None,
        region_offset_phys: Tuple[int, int] = (0, 0)
    ) -> None:
        """
        保存OCR识别调试图（对应OCRProcessor的需求）
        :param orig_image: 原始输入图像（BGR格式）
        :param target_text: 目标文本
        :param is_success: 是否找到目标文本
        :param match_score: 目标文本置信度
        :param min_confidence: 最小置信度阈值
        :param is_fullscreen: 是否全屏模式
        :param ocr_results: 所有OCR识别结果（格式：[{"text": "", "bbox": (x,y,w,h), ...}]）
        :param target_bbox_phys: 目标文本物理坐标（找到时传入）
        :param orig_region_phys: 筛选区域物理坐标（有region时传入）
        :param region_offset_phys: 区域偏移量（用于还原裁剪后的坐标到原图）
        """
        try:
            debug_img = orig_image.copy()
            img_h, img_w = debug_img.shape[:2]
            timestamp = datetime.datetime.now().strftime("%H%M%S%f")[:-3]
            safe_text = target_text.strip().replace("/", "_").replace("\\", "_").replace(" ", "_")
            img_type = "ocr_success" if is_success else "ocr_fail"
            save_path = os.path.join(self.debug_dir, f"{img_type}_{safe_text}_{timestamp}.png")

            # 1. 标注筛选区域（region）
            if orig_region_phys:
                rx, ry, rw, rh = orig_region_phys
                color, thickness, line_type = self.style["roi_rect"][:3]
                cv2.rectangle(debug_img, (rx, ry), (rx+rw, ry+rh), color, thickness, line_type)
                self._draw_text(debug_img, "OCR Region", (rx+5, ry+20), "text_info")

            # 2. 标注所有OCR识别结果（红色矩形）
            for res in ocr_results:
                x_sub, y_sub, w_sub, h_sub = res["bbox"]
                # 还原到原图物理坐标（加上区域偏移）
                x_orig = x_sub + region_offset_phys[0]
                y_orig = y_sub + region_offset_phys[1]
                text = res["text"].strip()
                conf = res["confidence"]

                # 绘制识别文本框
                color, thickness, line_type = self.style["match_rect"][:3]
                cv2.rectangle(debug_img, (x_orig, y_orig), (x_orig+w_sub, y_orig+h_sub), color, thickness, line_type)
                # 标注文本内容和置信度（避免超出图像边界）
                text_pos = (x_orig+5, y_orig-10) if (y_orig-10) > 10 else (x_orig+5, y_orig+h_sub+20)
                self._draw_text(debug_img, f"{text} ({conf:.2f})", text_pos, "text_small")

            # 3. 标注目标文本（找到时用绿色矩形突出）
            if is_success and target_bbox_phys:
                tx, ty, tw, th = target_bbox_phys
                color, thickness, line_type = self.style["target_rect"][:3]
                cv2.rectangle(debug_img, (tx, ty), (tx+tw, ty+th), color, thickness, line_type)
                self._draw_text(debug_img, f"Target: {target_text}", (tx+5, ty+20), "text_success")
                # 标注目标文本中心坐标
                cx = tx + tw // 2
                cy = ty + th // 2
                circle_color, radius, circle_thickness, line_type = self.style["center_point"][:4]
                cv2.circle(debug_img, (cx, cy), radius, circle_color, circle_thickness, line_type)
                self._draw_text(debug_img, f"Center(Phys): ({cx},{cy})", (cx+10, cy-10), "text_small")

            # 4. 标注顶部状态信息
            top_texts = [
                f"Target Text: '{target_text}'",
                f"Status: {'Found' if is_success else 'Not Found'}",
                f"Match Score: {match_score:.4f} | Min Confidence: {min_confidence}",
                f"OCR Results Count: {len(ocr_results)} | Mode: {'Fullscreen' if is_fullscreen else 'Window'}"
            ]
            text_style = "text_success" if is_success else "text_fail"
            y_offset = 30
            for text in top_texts:
                self._draw_text(debug_img, text, (10, y_offset), text_style)
                y_offset += 20

            # 5. 标注底部辅助信息
            bottom_texts = [
                f"Image Size(Phys): {img_w}x{img_h}",
                f"Region Offset: {region_offset_phys}"
            ]
            y_offset = img_h - 30
            for text in reversed(bottom_texts):
                self._draw_text(debug_img, text, (10, y_offset), "text_info")
                y_offset -= 20

            # 保存图片
            cv2.imwrite(save_path, debug_img)
            self.logger.debug(f"OCR调试图已保存: {save_path}")

        except Exception as e:
            self.logger.error(f"保存OCR调试图异常 | 目标文本: {target_text} | 错误: {str(e)}", exc_info=True)