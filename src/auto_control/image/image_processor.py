import datetime
import logging
import os
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

from src.auto_control.config.auto_config import TEMPLATE_EXTENSIONS
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.display_context import RuntimeDisplayContext
from src.core.path_manager import config, path_manager


class ImageProcessor:
    """图像处理器：对齐OCR流程（先裁剪ROI，再模板缩放）"""

    def __init__(
        self,
        original_base_res: Tuple[int, int],
        logger: Optional[logging.Logger] = None,
        coord_transformer: Optional[CoordinateTransformer] = None,
        display_context: Optional[RuntimeDisplayContext] = None,
        template_dir: str = None,
        test_mode: bool = False
    ) -> None:
        """
        初始化图像处理器（强制依赖上层传入有效实例）
        :param original_base_res: 全屏录制的基准分辨率（必需）
        :param logger: 日志实例（必需）
        :param coord_transformer: 坐标转换器实例（必需）
        :param display_context: 运行时上下文实例（必需）
        :param template_dir: 模板目录（可选，默认使用path_manager的task_template路径）
        :param test_mode: 测试模式开关（控制是否保存调试图+初始化清空历史图），默认False
        :raises ValueError: 任何必需依赖缺失或无效时抛错
        """
        # 强制检查所有必需依赖（不存在/无效直接抛错，不提供降级）
        if not logger:
            raise ValueError("初始化失败：logger不能为空（必须传入有效日志实例）")
        if not isinstance(original_base_res, (tuple, list)) or len(original_base_res) != 2:
            raise ValueError(f"初始化失败：original_base_res必须是二元组（当前：{original_base_res}）")
        if original_base_res[0] <= 0 or original_base_res[1] <= 0:
            raise ValueError(f"初始化失败：original_base_res必须为正整数（当前：{original_base_res}）")
        if not isinstance(coord_transformer, CoordinateTransformer):
            raise ValueError("初始化失败：coord_transformer必须是CoordinateTransformer实例")
        if not isinstance(display_context, RuntimeDisplayContext):
            raise ValueError("初始化失败：display_context必须是RuntimeDisplayContext实例")

        # 赋值核心属性（已校验有效性，直接使用）
        self.logger = logger
        self.original_base_res = original_base_res
        self.coord_transformer = coord_transformer
        self.display_context = display_context
        self.template_dir = template_dir or path_manager.get("task_template")
        self.debug_img_dir = path_manager.get("match_temple_debug")
        self.test_mode = test_mode

        # 初始化辅助属性
        self.templates: Dict[str, np.ndarray] = {}
        os.makedirs(self.debug_img_dir, exist_ok=True)  # 确保调试目录存在

        # 测试模式：清空历史调试图
        if self.test_mode:
            self._clear_debug_images()

        # 匹配参数配置
        self.min_confidence = 0.8
        self.min_template_size = (10, 10)
        self.match_algorithm = cv2.TM_CCOEFF_NORMED

        # 加载模板并输出初始化日志
        self.load_all_templates()
        self.logger.info(
            f"初始化完成 | 加载模板数: {len(self.templates)} | "
            f"原始基准分辨率: {self.original_base_res} | 模板目录: {self.template_dir} | "
            f"测试模式: {'启用（已清空历史调试图）' if self.test_mode else '禁用'}"
        )

    def _clear_debug_images(self) -> None:
        """测试模式专用：清空调试目录下的所有历史调试图（仅删除.png格式）"""
        try:
            total_count = 0  # 总调试图数
            deleted_count = 0  # 成功删除数
            failed_files = []  # 删除失败的文件

            # 遍历调试目录下所有文件
            for filename in os.listdir(self.debug_img_dir):
                file_path = os.path.join(self.debug_img_dir, filename)
                # 仅处理png格式文件（避免误删其他类型文件）
                if os.path.isfile(file_path) and filename.lower().endswith(".png"):
                    total_count += 1
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                        self.logger.debug(f"已删除历史调试图: {filename}")
                    except Exception as e:
                        failed_files.append(f"{filename}（错误：{str(e)}）")

            # 输出清空统计日志
            log_msg = (
                f"测试模式 - 清空调试目录完成 | "
                f"目录: {self.debug_img_dir} | "
                f"总调试图数: {total_count} | "
                f"成功删除: {deleted_count} | "
                f"删除失败: {len(failed_files)}"
            )
            if failed_files:
                log_msg += f" | 失败文件: {failed_files}"
            self.logger.info(log_msg)

        except Exception as e:
            self.logger.error(f"测试模式 - 清空调试目录异常: {str(e)}", exc_info=True)

    def load_template(self, template_name: str, template_path: Optional[str] = None) -> bool:
        try:
            if not template_path:
                template_path = os.path.join(self.template_dir, f"{template_name}.png")
            if not os.path.exists(template_path):
                self.logger.error(f"模板不存在: {template_path}")
                return False

            template_color = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template_color is None:
                self.logger.error(f"读取模板失败: {template_path}")
                return False

            self.templates[template_name] = template_color
            self.logger.debug(f"加载模板成功: {template_name} | 原始尺寸: {template_color.shape[:2]}")
            return True
        except Exception as e:
            self.logger.error(f"加载模板异常: {str(e)}", exc_info=True)
            return False

    def load_all_templates(self) -> None:
        if not os.path.isdir(self.template_dir):
            self.logger.warning(f"模板目录不存在: {self.template_dir}")
            return

        for root, dirs, files in os.walk(self.template_dir):
            for filename in files:
                if filename.lower().endswith(TEMPLATE_EXTENSIONS):
                    rel_path = os.path.relpath(root, self.template_dir)
                    template_name = os.path.join(rel_path, os.path.splitext(filename)[0]).replace('\\', '/') if rel_path != "." else os.path.splitext(filename)[0]
                    template_path = os.path.join(root, filename)
                    self.load_template(template_name, template_path)

    def get_template(self, template_name: str) -> Optional[np.ndarray]:
        template = self.templates.get(template_name)
        if template is None:
            self.logger.warning(f"模板未找到，尝试重新加载: {template_name}")
            if self.load_template(template_name):
                template = self.templates.get(template_name)
        return template

    def match_template(
        self,
        image: np.ndarray,
        template: Union[str, np.ndarray],
        threshold: float = 0.8,
        roi: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        对齐OCR流程的模板匹配：先裁剪ROI→再缩放模板→最后匹配
        Args:
            image: 输入图像（WindowsDevice返回的物理截图，BGR格式）
            template: 模板名称（字符串）或自定义模板（np.ndarray）
            threshold: 匹配阈值（0~1，值越高匹配越严格）
            roi: 感兴趣区域（x, y, w, h）：
                - 上下文全屏时 → 物理坐标（基于屏幕物理分辨率）
                - 上下文窗口时 → 逻辑坐标（基于客户区逻辑尺寸）
        Returns:
            匹配成功返回逻辑坐标矩形（x, y, w, h），失败返回None
        """
        try:
            is_fullscreen = self.display_context.is_fullscreen
            ctx = self.display_context
            self.logger.debug(
                f"上下文全屏状态: {is_fullscreen} | ROI: {roi} | 阈值: {threshold} | "
                f"客户区逻辑尺寸: {ctx.client_logical_res} | 屏幕物理尺寸: {ctx.screen_physical_res}"
            )

            if image is None or image.size == 0:
                self.logger.error("模板匹配失败：输入图像为空或无效")
                return None
            orig_image = image.copy()
            image_phys_h, image_phys_w = orig_image.shape[:2]
            timestamp = datetime.datetime.now().strftime("%H%M%S%f")[:-3]
            roi_offset_phys = (0, 0)

            if isinstance(template, str):
                template_bgr = self.get_template(template)
                if template_bgr is None:
                    self.logger.error(f"模板匹配失败：模板「{template}」不存在或加载失败")
                    return None
                template_name = template
            else:
                if not isinstance(template, np.ndarray) or template.size == 0:
                    self.logger.error("模板匹配失败：自定义模板为无效numpy数组")
                    return None
                template_bgr = template
                template_name = "custom_template"
            template_orig_h, template_orig_w = template_bgr.shape[:2]
            self.logger.debug(
                f"开始模板匹配 | 模板: {template_name} | 原始尺寸: (宽={template_orig_w}, 高={template_orig_h}) | "
                f"输入图像尺寸: (宽={image_phys_w}, 高={image_phys_h}) | 阈值: {threshold} | "
                f"ROI: {roi} | 上下文全屏状态: {is_fullscreen}"
            )

            cropped_image = orig_image
            processed_roi = roi
            if roi:
                try:
                    if not isinstance(roi, (tuple, list)) or len(roi) != 4:
                        raise ValueError(f"ROI格式无效（需为4元组/列表），当前: {type(roi)} {roi}")
                    rx, ry, rw, rh = roi
                    if rx < 0 or ry < 0 or rw <= 0 or rh <= 0:
                        raise ValueError(f"ROI参数无效（x/y非负，w/h正数），当前: ({rx}, {ry}, {rw}, {rh})")

                    if is_fullscreen:
                        rx_phys, ry_phys, rw_phys, rh_phys = rx, ry, rw, rh
                        rx_phys = max(0, rx_phys)
                        ry_phys = max(0, ry_phys)
                        rw_phys = min(rw_phys, ctx.screen_physical_width - rx_phys)
                        rh_phys = min(rh_phys, ctx.screen_physical_height - ry_phys)
                        self.logger.debug(
                            f"全屏模式ROI处理 | 原始物理ROI: {roi} → 调整后: ({rx_phys}, {ry_phys}, {rw_phys}, {rh_phys}) | "
                            f"屏幕物理尺寸: {ctx.screen_physical_res}"
                        )
                    else:
                        client_w_log, client_h_log = ctx.client_logical_res
                        rx_log = max(0, rx)
                        ry_log = max(0, ry)
                        rw_log = min(rw, client_w_log - rx_log)
                        rh_log = min(rh, client_h_log - ry_log)
                        if rw_log <= 0 or rh_log <= 0:
                            raise ValueError(
                                f"逻辑ROI超出客户区范围 | 原始ROI: {roi} | 客户区逻辑尺寸: {client_w_log}x{client_h_log}")
                        rx_phys, ry_phys = self.coord_transformer.convert_client_logical_to_physical(rx_log, ry_log)
                        ratio = ctx.logical_to_physical_ratio
                        rw_phys = int(round(rw_log * ratio))
                        rh_phys = int(round(rh_log * ratio))
                        self.logger.debug(
                            f"窗口模式ROI处理 | 原始逻辑ROI: {roi} → 调整后逻辑ROI: ({rx_log}, {ry_log}, {rw_log}, {rh_log}) → "
                            f"物理ROI: ({rx_phys}, {ry_phys}, {rw_phys}, {rh_phys}) | DPI比例: {ratio:.2f}"
                        )

                    if rw_phys <= 0 or rh_phys <= 0:
                        raise ValueError(f"物理ROI无效（尺寸≤0）: ({rx_phys}, {ry_phys}, {rw_phys}, {rh_phys})")

                    cropped_image = orig_image[ry_phys:ry_phys+rh_phys, rx_phys:rx_phys+rw_phys]
                    roi_offset_phys = (rx_phys, ry_phys)
                    cropped_phys_h, cropped_phys_w = cropped_image.shape[:2]
                    self.logger.debug(
                        f"ROI裁剪完成 | 子图尺寸: (宽={cropped_phys_w}, 高={cropped_phys_h}) | "
                        f"原图偏移: {roi_offset_phys} | 裁剪后图像是否有效: {cropped_image.size > 0}"
                    )

                    if self.test_mode:
                        safe_template_name = template_name.replace("/", "_").replace("\\", "_")
                        crop_save_path = os.path.join(
                            self.debug_img_dir, f"roi_crop_{safe_template_name}_{timestamp}.png"
                        )
                        cv2.imwrite(crop_save_path, cropped_image)
                        self.logger.debug(f"ROI子图已保存至: {crop_save_path}")

                    processed_roi = (rx, ry, rw, rh)

                except ValueError as e:
                    self.logger.warning(f"ROI处理失败：{str(e)}，自动切换为全图匹配")
                    cropped_image = orig_image
                    processed_roi = None
                    roi_offset_phys = (0, 0)

            cropped_phys_h, cropped_phys_w = cropped_image.shape[:2]
            if processed_roi:
                orig_roi_w, orig_roi_h = processed_roi[2], processed_roi[3]
                scale_ratio_w = cropped_phys_w / orig_roi_w if orig_roi_w != 0 else 1.0
                scale_ratio_h = cropped_phys_h / orig_roi_h if orig_roi_h != 0 else 1.0
                scale_ratio = min(scale_ratio_w, scale_ratio_h)
                self.logger.debug(
                    f"模板缩放比例计算（有ROI）| 子图尺寸: (宽={cropped_phys_w}, 高={cropped_phys_h}) | "
                    f"原始ROI尺寸: (宽={orig_roi_w}, 高={orig_roi_h}) | "
                    f"宽比例: {scale_ratio_w:.4f} | 高比例: {scale_ratio_h:.4f} | 最终比例: {scale_ratio:.4f}"
                )
            else:
                orig_base_w, orig_base_h = self.original_base_res
                scale_ratio_w = cropped_phys_w / orig_base_w
                scale_ratio_h = cropped_phys_h / orig_base_h
                scale_ratio = min(scale_ratio_w, scale_ratio_h)
                self.logger.debug(
                    f"模板缩放比例计算（无ROI）| 子图尺寸: (宽={cropped_phys_w}, 高={cropped_phys_h}) | "
                    f"原始基准尺寸: (宽={orig_base_w}, 高={orig_base_h}) | "
                    f"宽比例: {scale_ratio_w:.4f} | 高比例: {scale_ratio_h:.4f} | 最终比例: {scale_ratio:.4f}"
                )

            scaled_w = max(self.min_template_size[0], int(round(template_orig_w * scale_ratio)))
            scaled_h = max(self.min_template_size[1], int(round(template_orig_h * scale_ratio)))
            scaled_w = min(scaled_w, cropped_phys_w - 2)
            scaled_h = min(scaled_h, cropped_phys_h - 2)

            if scaled_w <= 0 or scaled_h <= 0:
                self.logger.error(
                    f"模板缩放失败 | 缩放后尺寸无效: (宽={scaled_w}, 高={scaled_h}) | "
                    f"子图尺寸: (宽={cropped_phys_w}, 高={cropped_phys_h}) | 比例: {scale_ratio:.4f}"
                )
                return None

            interpolation = cv2.INTER_AREA if scale_ratio < 1.0 else cv2.INTER_CUBIC
            scaled_template = cv2.resize(template_bgr, (scaled_w, scaled_h), interpolation=interpolation)
            self.logger.debug(
                f"模板缩放完成 | 原始尺寸: (宽={template_orig_w}, 高={template_orig_h}) → "
                f"缩放后: (宽={scaled_w}, 高={scaled_h}) | 插值方式: {interpolation}"
            )

            if len(cropped_image.shape) == 3:
                cropped_gray = cv2.cvtColor(cropped_image, cv2.COLOR_BGR2GRAY)
            else:
                cropped_gray = cropped_image
            if len(scaled_template.shape) == 3:
                template_gray = cv2.cvtColor(scaled_template, cv2.COLOR_BGR2GRAY)
            else:
                template_gray = scaled_template

            if (template_gray.shape[0] > cropped_gray.shape[0]) or (template_gray.shape[1] > cropped_gray.shape[1]):
                self.logger.error(
                    f"模板匹配失败：模板尺寸超过子图尺寸 | "
                    f"模板尺寸: (宽={template_gray.shape[1]}, 高={template_gray.shape[0]}) | "
                    f"子图尺寸: (宽={cropped_gray.shape[1]}, 高={cropped_gray.shape[0]})"
                )
                return None

            result = cv2.matchTemplate(cropped_gray, template_gray, self.match_algorithm)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            match_score = max_val
            self.logger.debug(
                f"模板匹配完成 | 最高匹配分数: {match_score:.4f} | 阈值: {threshold} | "
                f"匹配位置（子图内）: {max_loc}"
            )

            if match_score < threshold:
                self.logger.debug(
                    f"模板匹配失败：分数不足 | 模板: {template_name} | 分数: {match_score:.4f} < 阈值: {threshold}"
                )
                if self.test_mode:
                    safe_template_name = template_name.replace("/", "_").replace("\\", "_")
                    debug_img = cropped_image.copy()
                    cv2.putText(
                        debug_img, f"Score: {match_score:.4f} < Threshold: {threshold}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1
                    )
                    save_path = os.path.join(
                        self.debug_img_dir, f"match_fail_{safe_template_name}_{timestamp}.png"
                    )
                    cv2.imwrite(save_path, debug_img)
                    self.logger.debug(f"匹配失败调试图已保存至: {save_path}")
                return None

            match_x_sub, match_y_sub = max_loc
            match_x_phys = match_x_sub + roi_offset_phys[0]
            match_y_phys = match_y_sub + roi_offset_phys[1]
            match_w_phys = scaled_template.shape[1]
            match_h_phys = scaled_template.shape[0]
            full_bbox_phys = (match_x_phys, match_y_phys, match_w_phys, match_h_phys)
            self.logger.debug(
                f"坐标映射完成 | 子图内坐标: ({match_x_sub}, {match_y_sub}) → "
                f"全图物理坐标: {full_bbox_phys} | ROI偏移: {roi_offset_phys}"
            )

            if is_fullscreen:
                final_bbox_log = full_bbox_phys
            else:
                x_log = self.coord_transformer.convert_client_physical_to_logical(match_x_phys, match_y_phys)[0]
                y_log = self.coord_transformer.convert_client_physical_to_logical(match_x_phys, match_y_phys)[1]
                ratio = ctx.logical_to_physical_ratio
                w_log = int(round(match_w_phys / ratio)) if ratio > 0 else match_w_phys
                h_log = int(round(match_h_phys / ratio)) if ratio > 0 else match_h_phys
                client_w_log, client_h_log = ctx.client_logical_res
                x_log = max(0, min(x_log, client_w_log - 1))
                y_log = max(0, min(y_log, client_h_log - 1))
                w_log = max(1, min(w_log, client_w_log - x_log))
                h_log = max(1, min(h_log, client_h_log - y_log))
                final_bbox_log = (x_log, y_log, w_log, h_log)

            if self.test_mode:
                safe_template_name = template_name.replace("/", "_").replace("\\", "_")
                debug_img = orig_image.copy()
                cv2.rectangle(
                    debug_img, (match_x_phys, match_y_phys),
                    (match_x_phys + match_w_phys, match_y_phys + match_h_phys),
                    (0, 0, 255), 2
                )
                center_x_phys = match_x_phys + match_w_phys // 2
                center_y_phys = match_y_phys + match_h_phys // 2
                cv2.circle(debug_img, (center_x_phys, center_y_phys), 3, (0, 255, 0), -1)
                text = (
                    f"Template: {template_name} | Score: {match_score:.4f} | "
                    f"Phys: {full_bbox_phys} | Log: {final_bbox_log} | Mode: {'Fullscreen' if is_fullscreen else 'Window'}"
                )
                cv2.putText(
                    debug_img, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 0), 1, lineType=cv2.LINE_AA
                )
                save_path = os.path.join(
                    self.debug_img_dir, f"match_success_{safe_template_name}_{timestamp}.png"
                )
                cv2.imwrite(save_path, debug_img)
                self.logger.debug(f"匹配成功调试图已保存至: {save_path}")

            self.logger.info(
                f"模板匹配成功 | 模板: {template_name} | 逻辑坐标: {final_bbox_log} | "
                f"物理坐标: {full_bbox_phys} | 匹配分数: {match_score:.4f} | "
                f"模式: {'全屏' if is_fullscreen else '窗口'}"
            )
            return final_bbox_log

        except Exception as e:
            template_name = template if isinstance(template, str) else "custom_template"
            self.logger.error(f"模板匹配异常 | 模板: {template_name} | 错误: {str(e)}", exc_info=True)
            return None

    def get_center(self, rect: Union[Tuple[int, int, int, int], np.ndarray]) -> Tuple[int, int]:
        if rect is None:
            self.logger.warning("计算中心失败：矩形为None")
            return (0, 0)
        if isinstance(rect, np.ndarray):
            rect = tuple(rect.tolist())
        if not isinstance(rect, (tuple, list)) or len(rect) != 4:
            self.logger.warning(f"计算中心失败：无效矩形 {rect}")
            return (0, 0)
        try:
            x, y, w, h = map(int, rect)
            center_x = x + w // 2
            center_y = y + h // 2
            return (center_x, center_y)
        except (ValueError, TypeError):
            self.logger.warning(f"计算中心失败：矩形值错误 {rect}")
            return (0, 0)