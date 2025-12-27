import datetime
import logging
import os
from typing import Dict, List, Optional, Tuple, TypeGuard, Union

import cv2
import numpy as np

# 处理PIL导入（中文绘制依赖），兼容无PIL环境
try:
    from PIL import Image, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logging.warning("PIL库未安装，中文文本将使用CV2默认字体（可能显示乱码）")


class DebugImageSaver:
    """公共调试图保存工具类：统一模板匹配/OCR识别的调试图标注风格和保存逻辑"""

    def __init__(
        self,
        logger: logging.Logger,
        debug_dir: str,
        test_mode: bool = False,
        custom_style: Optional[Dict] = None,
        chinese_font_path: str = "simhei.ttf",
    ):
        """
        初始化调试图保存工具
        :param logger: 日志实例（从上层处理器传入）
        :param debug_dir: 调试图保存目录
        :param test_mode: 测试模式（是否清空历史图）
        :param custom_style: 自定义样式（覆盖默认样式，格式同self.style）
        :param chinese_font_path: 中文字体文件路径（如simhei.ttf）
        """
        self.logger = logger
        self.debug_dir = debug_dir
        self.test_mode = test_mode
        self.chinese_font_path = chinese_font_path

        # 确保调试目录存在
        os.makedirs(self.debug_dir, exist_ok=True)

        # 测试模式：清空历史调试图
        if self.test_mode:
            self._clear_debug_dir()

        # ========== 核心样式修改 ==========
        self.style = {
            "roi_rect": (255, 0, 0, 2, cv2.LINE_AA),  # 蓝色：传的原始ROI区域
            "match_rect": (0, 0, 255, 2, cv2.LINE_AA),  # 红色：选中的ROI/匹配区域
            "target_rect": (0, 0, 255, 2, cv2.LINE_AA),  # 红色：OCR选中的目标文本区域
            "center_point": (0, 255, 0, 4, -1, cv2.LINE_AA),  # 绿色：中心坐标点
            # 所有文本统一改为绿色
            "text_success": ((0, 255, 0), 0.5, 1, cv2.LINE_AA),  # 绿色：成功状态文本
            "text_fail": ((0, 255, 0), 0.5, 1, cv2.LINE_AA),  # 绿色：失败状态文本（按要求改为绿色）
            "text_info": ((0, 255, 0), 0.4, 1, cv2.LINE_AA),  # 绿色：辅助信息文本
            "text_small": ((0, 255, 0), 0.35, 1, cv2.LINE_AA),  # 绿色：文本内容标注
        }

        # 合并自定义样式
        if custom_style:
            self._validate_custom_style(custom_style)
            self.style.update(custom_style)
            self.logger.debug(f"已应用自定义样式，覆盖{len(custom_style)}个样式项")

    def _validate_custom_style(self, custom_style: Dict) -> None:
        """校验自定义样式格式合法性"""
        valid_keys = self.style.keys()
        for key, value in custom_style.items():
            if key not in valid_keys:
                raise ValueError(f"自定义样式键'{key}'无效，合法键：{list(valid_keys)}")
            # 校验值的格式
            if key in ["roi_rect", "match_rect", "target_rect"]:
                if not (
                    isinstance(value, (list, tuple))
                    and len(value) == 5
                    and isinstance(value[0], (int, float))
                    and isinstance(value[1], (int, float))
                    and isinstance(value[2], (int, float))
                    and isinstance(value[3], int)
                    and isinstance(value[4], int)
                ):
                    raise ValueError(f"样式'{key}'格式错误，需为(color_r, color_g, color_b, thickness, line_type)")
            elif key == "center_point":
                if not (
                    isinstance(value, (list, tuple))
                    and len(value) == 6
                    and isinstance(value[0], (int, float))
                    and isinstance(value[1], (int, float))
                    and isinstance(value[2], (int, float))
                    and isinstance(value[3], int)
                    and isinstance(value[4], int)
                    and isinstance(value[5], int)
                ):
                    raise ValueError(
                        f"样式'{key}'格式错误，需为(color_r, color_g, color_b, radius, thickness, line_type)"
                    )
            elif key.startswith("text_"):
                if not (
                    isinstance(value, (list, tuple))
                    and len(value) == 4
                    and isinstance(value[0], (list, tuple))
                    and len(value[0]) == 3
                    and isinstance(value[1], (int, float))
                    and isinstance(value[2], int)
                    and isinstance(value[3], int)
                ):
                    raise ValueError(f"样式'{key}'格式错误，需为((r,g,b), font_scale, thickness, line_type)")

    def _clear_debug_dir(self) -> None:
        """清空调试目录下的所有PNG格式调试图（复用原有逻辑，增强异常处理）"""
        try:
            total_count = 0
            deleted_count = 0
            failed_files = []

            for filename in os.listdir(self.debug_dir):
                file_path = os.path.join(self.debug_dir, filename)
                if not os.path.isfile(file_path):
                    continue
                if filename.lower().endswith(".png"):
                    total_count += 1
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                        self.logger.debug(f"已删除历史调试图: {filename}")
                    except PermissionError:
                        failed_files.append(f"{filename}（权限不足）")
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

    def _is_valid_bbox(self, bbox: Optional[Tuple[int, int, int, int]]) -> TypeGuard[Tuple[int, int, int, int]]:
        """校验bbox是否为合法的(x,y,w,h)整数元组（非负）"""
        if not bbox:
            return False
        if len(bbox) != 4:
            return False
        return all(isinstance(v, int) and v >= 0 for v in bbox)

    def _is_valid_point(self, point: Optional[Tuple[int, int]]) -> TypeGuard[Tuple[int, int]]:
        """校验坐标点是否合法"""
        if not point:
            return False
        if len(point) != 2:
            return False
        return all(isinstance(v, int) and v >= 0 for v in point)

    def _is_bbox_in_image(self, bbox: Tuple[int, int, int, int], img_h: int, img_w: int) -> bool:
        """校验bbox是否在图片范围内"""
        x, y, w, h = bbox
        return x + w <= img_w and y + h <= img_h and x >= 0 and y >= 0

    def _draw_text_wrap(
        self, img: np.ndarray, text: str, pos: Tuple[int, int], style_key: str, max_char_per_line: int = 30
    ) -> None:
        """
        自动换行绘制文本（支持中文）
        :param img: 待绘制图像
        :param text: 文本内容
        :param pos: 起始坐标 (x, y)
        :param style_key: 样式键
        :param max_char_per_line: 每行最大字符数
        """
        img_h, img_w = img.shape[:2]
        # 拆分长文本为多行
        text_lines = []
        for i in range(0, len(text), max_char_per_line):
            text_lines.append(text[i : i + max_char_per_line])

        y_offset = pos[1]
        for line in text_lines:
            # 避免超出图片边界（增加更严格的边界校验）
            if y_offset > img_h - 20:  # 预留更多空间
                self.logger.warning(f"文本'{line}'超出图片底部，停止绘制")
                break
            if pos[0] > img_w - 50:  # 预留文本宽度空间
                self.logger.warning(f"文本'{line}'超出图片右侧，跳过绘制")
                continue

            # 优先绘制中文，失败则降级为CV2默认
            if any(ord(c) > 127 for c in line) and PIL_AVAILABLE:
                # 修复：传入img副本，避免原数组被破坏
                self._draw_chinese_text(img, line, (pos[0], y_offset), style_key)
            else:
                self._draw_text(img, line, (pos[0], y_offset), style_key)
            y_offset += 20  # 行间距

    def _draw_chinese_text(self, img: np.ndarray, text: str, pos: Tuple[int, int], style_key: str) -> None:
        """绘制中文文本（修复黑块问题：通道匹配+避免直接覆盖原数组）"""
        try:
            color, font_scale, thickness, _ = self.style[style_key]
            img_h, img_w = img.shape[:2]
            # 1. 处理通道数：确保是3通道BGR
            if len(img.shape) == 2:  # 灰度图转3通道
                img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            else:  # BGR转RGB
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

            # 2. 创建PIL图片（基于副本，避免修改原数组）
            pil_img = Image.fromarray(img_rgb).copy()
            draw = ImageDraw.Draw(pil_img)

            # 3. 加载中文字体（限制字体大小，避免越界）
            font_size = int(12 * font_scale)
            font_size = min(font_size, 16)  # 最大字体限制为16，防止黑块
            try:
                font = ImageFont.truetype(self.chinese_font_path, font_size)
            except (FileNotFoundError, OSError):
                self.logger.warning(f"中文字体文件'{self.chinese_font_path}'未找到，使用默认字体")
                font = ImageFont.load_default()

            # 4. 校验绘制坐标（避免越界）
            draw_x = max(0, min(pos[0], img_w - 10))
            draw_y = max(0, min(pos[1], img_h - 10))

            # 5. 绘制文本（使用tuple(color)确保PIL兼容）
            draw.text((draw_x, draw_y), text, fill=tuple(color), font=font)

            # 6. 转换回CV2格式并合并到原图（修复直接赋值问题）
            pil_img_np = np.array(pil_img)
            if len(img.shape) == 2:  # 灰度图还原
                pil_img_bgr = cv2.cvtColor(pil_img_np, cv2.COLOR_RGB2GRAY)
                img[:] = pil_img_bgr
            else:  # 3通道还原
                pil_img_bgr = cv2.cvtColor(pil_img_np, cv2.COLOR_RGB2BGR)
                img[:] = pil_img_bgr

        except Exception as e:
            self.logger.warning(f"绘制中文文本失败，降级为CV2默认绘制 | 错误: {str(e)}")
            self._draw_text(img, text, pos, style_key)

    def _draw_text(self, img: np.ndarray, text: str, pos: Tuple[int, int], style_key: str) -> None:
        """通用文本绘制方法（根据style_key读取统一样式）- 增强参数校验"""
        try:
            # 从样式中正确取出参数
            color, font_scale, thickness, line_type = self.style[style_key]
            # 类型转换（避免浮点型导致CV2报错）
            font_scale = float(font_scale)
            thickness = int(thickness)
            line_type = int(line_type)

            # 限制字体缩放（避免过大导致黑块）
            font_scale = min(font_scale, 0.8)

            # 校验绘制坐标
            draw_x = max(0, min(pos[0], img.shape[1] - 10))
            draw_y = max(0, min(pos[1], img.shape[0] - 10))

            # 绘制文本
            cv2.putText(img, text, (draw_x, draw_y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness, line_type)
        except Exception as e:
            self.logger.warning(f"绘制文本失败 | 文本: {text} | 错误: {str(e)}")

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
        template_scaled_size: Optional[Tuple[int, int]] = None,
    ) -> None:
        """
        保存模板匹配调试图（对应ImageProcessor的需求，参数完全不变）
        """
        try:
            # 基础参数校验
            if orig_image is None or len(orig_image.shape) < 2:
                self.logger.error("原始图像为空或格式错误，跳过保存")
                return
            debug_img = orig_image.copy()
            img_h, img_w = debug_img.shape[:2]
            timestamp = datetime.datetime.now().strftime("%H%M%S%f")[:-3]
            safe_name = template_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
            img_type = "match_success" if is_success else "match_fail"
            save_path = os.path.join(self.debug_dir, f"{img_type}_{safe_name}_{timestamp}.png")

            # 1. 标注ROI区域（增加合法性校验）
            if self._is_valid_bbox(orig_roi_phys) and self._is_bbox_in_image(orig_roi_phys, img_h, img_w):
                rx, ry, rw, rh = orig_roi_phys
                color, thickness, line_type = self.style["roi_rect"][:3]
                cv2.rectangle(debug_img, (rx, ry), (rx + rw, ry + rh), color, int(thickness), int(line_type))
                self._draw_text_wrap(debug_img, "Original ROI", (rx + 5, ry + 20), "text_info")
                # 窗口模式标注逻辑坐标
                if not is_fullscreen and self._is_valid_bbox(processed_roi):
                    self._draw_text_wrap(debug_img, f"ROI(Log): {processed_roi}", (rx + 5, ry + 40), "text_small")
            elif orig_roi_phys:
                self.logger.warning(f"无效的ROI坐标: {orig_roi_phys}，跳过ROI标注")

            # 2. 标注顶部状态信息（自动换行）
            top_texts = [
                f"Template: {template_name}",
                f"Status: {'Match Success' if is_success else 'Match Failed'}",
                f"Score: {match_score:.4f} | Threshold: {threshold}",
                f"Mode: {'Fullscreen' if is_fullscreen else 'Window'}",
            ]
            text_style = "text_success" if is_success else "text_fail"
            y_offset = 30
            for text in top_texts:
                self._draw_text_wrap(debug_img, text, (10, y_offset), text_style)
                y_offset += 20

            # 3. 匹配成功：标注匹配区域、中心坐标、详细参数（增加合法性校验）
            if is_success:
                # 匹配区域矩形（红色：选中的ROI）
                if self._is_valid_bbox(match_bbox_phys) and self._is_bbox_in_image(match_bbox_phys, img_h, img_w):
                    mx, my, mw, mh = match_bbox_phys
                    color, thickness, line_type = self.style["match_rect"][:3]
                    cv2.rectangle(debug_img, (mx, my), (mx + mw, my + mh), color, int(thickness), int(line_type))
                    self._draw_text_wrap(debug_img, "Matched Area", (mx + 5, my + 20), "text_info")
                elif match_bbox_phys:
                    self.logger.warning(f"无效的匹配区域坐标: {match_bbox_phys}，跳过标注")

                # 中心坐标点（绿色）
                if self._is_valid_point(center_phys) and 0 <= center_phys[0] < img_w and 0 <= center_phys[1] < img_h:
                    cx, cy = center_phys
                    color, radius, thickness, line_type = self.style["center_point"][:4]
                    cv2.circle(debug_img, (cx, cy), int(radius), color, int(thickness), int(line_type))
                    self._draw_text_wrap(debug_img, f"Center(Phys): ({cx},{cy})", (cx + 10, cy - 10), "text_small")
                elif center_phys:
                    self.logger.warning(f"无效的中心坐标: {center_phys}，跳过中心标注")

                # 底部详细参数（自动换行）
                bottom_texts = []
                if self._is_valid_bbox(match_bbox_phys):
                    bottom_texts.append(f"Matched(Phys): {match_bbox_phys}")
                if self._is_valid_bbox(final_bbox_log):
                    bottom_texts.append(f"Matched(Log): {final_bbox_log}")
                if template_orig_size and template_scaled_size:
                    bottom_texts.append(
                        f"Template Size: Orig({template_orig_size[0]},{template_orig_size[1]}) | "
                        f"Scaled({template_scaled_size[0]},{template_scaled_size[1]})"
                    )

                y_offset = img_h - 30
                for text in reversed(bottom_texts):
                    self._draw_text_wrap(debug_img, text, (10, y_offset), "text_info")
                    y_offset -= 20

            # 保存图片（增强异常处理，添加压缩参数避免黑块）
            try:
                cv2.imwrite(save_path, debug_img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
                self.logger.debug(f"模板匹配调试图已保存: {save_path}")
            except cv2.error as e:
                self.logger.error(f"CV2保存图片失败 | 路径: {save_path} | 错误: {str(e)}")
            except Exception as e:
                self.logger.error(f"保存图片失败 | 路径: {save_path} | 错误: {str(e)}")

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
        region_offset_phys: Tuple[int, int] = (0, 0),
    ) -> None:
        """
        保存OCR识别调试图（对应OCRProcessor的需求，参数完全不变）
        """
        try:
            # 基础参数校验
            if orig_image is None or len(orig_image.shape) < 2:
                self.logger.error("原始图像为空或格式错误，跳过保存")
                return
            if not isinstance(ocr_results, list):
                self.logger.error("OCR结果非列表类型，跳过保存")
                return

            # 修复：创建深度拷贝，避免原图像被修改导致黑块
            debug_img = orig_image.copy()
            img_h, img_w = debug_img.shape[:2]
            timestamp = datetime.datetime.now().strftime("%H%M%S%f")[:-3]
            safe_text = target_text.strip().replace("/", "_").replace("\\", "_").replace(" ", "_")[:50]  # 限制长度
            img_type = "ocr_success" if is_success else "ocr_fail"
            save_path = os.path.join(self.debug_dir, f"{img_type}_{safe_text}_{timestamp}.png")

            # 1. 标注筛选区域（region）（蓝色：传的ROI）
            if self._is_valid_bbox(orig_region_phys) and self._is_bbox_in_image(orig_region_phys, img_h, img_w):
                rx, ry, rw, rh = orig_region_phys
                color, thickness, line_type = self.style["roi_rect"][:3]
                cv2.rectangle(debug_img, (rx, ry), (rx + rw, ry + rh), color, int(thickness), int(line_type))
                self._draw_text_wrap(debug_img, "OCR Region", (rx + 5, ry + 20), "text_info")
            elif orig_region_phys:
                self.logger.warning(f"无效的OCR区域坐标: {orig_region_phys}，跳过区域标注")

            # 2. 标注所有OCR识别结果（红色：选中的ROI）
            for idx, res in enumerate(ocr_results):
                # 校验OCR结果格式
                if not isinstance(res, dict) or "bbox" not in res or "text" not in res or "confidence" not in res:
                    self.logger.warning(f"第{idx}个OCR结果格式错误: {res}，跳过标注")
                    continue
                bbox = res["bbox"]
                if not self._is_valid_bbox(bbox):
                    self.logger.warning(f"第{idx}个OCR结果bbox无效: {bbox}，跳过标注")
                    continue

                x_sub, y_sub, w_sub, h_sub = bbox
                # 还原到原图物理坐标（加上区域偏移）
                x_orig = x_sub + region_offset_phys[0]
                y_orig = y_sub + region_offset_phys[1]
                # 校验还原后的坐标是否在图片内（更严格）
                if not (
                    0 <= x_orig < img_w and 0 <= y_orig < img_h and x_orig + w_sub <= img_w and y_orig + h_sub <= img_h
                ):
                    self.logger.warning(
                        f"第{idx}个OCR结果还原后坐标超出图片范围: ({x_orig},{y_orig},{w_sub},{h_sub})，跳过标注"
                    )
                    continue

                text = res["text"].strip()
                conf = res["confidence"]

                # 绘制识别文本框（红色，限制厚度）
                color, thickness, line_type = self.style["match_rect"][:3]
                thickness = min(int(thickness), 2)  # 最大厚度2，防止黑块
                cv2.rectangle(
                    debug_img, (x_orig, y_orig), (x_orig + w_sub, y_orig + h_sub), color, thickness, int(line_type)
                )
                # 标注文本内容和置信度（绿色文字）
                text_y = y_orig - 10 if (y_orig - 10) > 10 else (y_orig + h_sub + 20)
                text_pos = (x_orig + 5, text_y)
                self._draw_text_wrap(debug_img, f"{text} ({conf:.2f})", text_pos, "text_small")

            # 3. 标注目标文本（红色：选中的ROI，绿色文字）
            if (
                is_success
                and self._is_valid_bbox(target_bbox_phys)
                and self._is_bbox_in_image(target_bbox_phys, img_h, img_w)
            ):
                tx, ty, tw, th = target_bbox_phys
                color, thickness, line_type = self.style["target_rect"][:3]
                thickness = min(int(thickness), 2)  # 限制厚度
                cv2.rectangle(debug_img, (tx, ty), (tx + tw, ty + th), color, thickness, int(line_type))
                self._draw_text_wrap(debug_img, f"Target: {target_text}", (tx + 5, ty + 20), "text_success")
                # 标注目标文本中心坐标（绿色）
                cx = tx + tw // 2
                cy = ty + th // 2
                if 0 <= cx < img_w and 0 <= cy < img_h:
                    circle_color, radius, circle_thickness, line_type = self.style["center_point"][:4]
                    radius = min(int(radius), 4)  # 限制半径
                    cv2.circle(debug_img, (cx, cy), radius, circle_color, int(circle_thickness), int(line_type))
                    self._draw_text_wrap(debug_img, f"Center(Phys): ({cx},{cy})", (cx + 10, cy - 10), "text_small")
                else:
                    self.logger.warning(f"目标文本中心坐标超出图片范围: ({cx},{cy})，跳过中心标注")
            elif is_success and target_bbox_phys:
                self.logger.warning(f"无效的目标文本bbox: {target_bbox_phys}，跳过目标标注")

            # 4. 标注顶部状态信息（绿色文字）
            top_texts = [
                f"Target Text: '{target_text}'",
                f"Status: {'Found' if is_success else 'Not Found'}",
                f"Match Score: {match_score:.4f} | Min Confidence: {min_confidence}",
                f"OCR Results Count: {len(ocr_results)} | Mode: {'Fullscreen' if is_fullscreen else 'Window'}",
            ]
            text_style = "text_success" if is_success else "text_fail"
            y_offset = 30
            for text in top_texts:
                self._draw_text_wrap(debug_img, text, (10, y_offset), text_style)
                y_offset += 20

            # 5. 标注底部辅助信息（绿色文字）
            bottom_texts = [f"Image Size(Phys): {img_w}x{img_h}", f"Region Offset: {region_offset_phys}"]
            y_offset = img_h - 30
            for text in reversed(bottom_texts):
                self._draw_text_wrap(debug_img, text, (10, y_offset), "text_info")
                y_offset -= 20

            # 保存图片（增强异常处理，添加压缩参数避免黑块）
            try:
                cv2.imwrite(save_path, debug_img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
                self.logger.debug(f"OCR调试图已保存: {save_path}")
            except cv2.error as e:
                self.logger.error(f"CV2保存图片失败 | 路径: {save_path} | 错误: {str(e)}")
            except Exception as e:
                self.logger.error(f"保存图片失败 | 路径: {save_path} | 错误: {str(e)}")

        except Exception as e:
            self.logger.error(f"保存OCR调试图异常 | 目标文本: {target_text} | 错误: {str(e)}", exc_info=True)
