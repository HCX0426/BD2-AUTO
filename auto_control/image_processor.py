import cv2
import numpy as np
import os
from typing import Optional, Tuple, Dict, List, Union
import logging

# 导入坐标转换器
from auto_control.config.image_config import TEMPLATE_DIR
from auto_control.coordinate_transformer import CoordinateTransformer


class ImageProcessor:
    """图像处理器：修复基础分辨率模板适配窗口化问题（先缩放模板再匹配）"""
    
    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        coord_transformer: Optional[CoordinateTransformer] = None,
        template_dir: str = TEMPLATE_DIR,
        original_base_res: Tuple[int, int] = (1920, 1080)  # 模板原始基准分辨率（全屏1920×1080）
    ):
        """
        初始化图像处理器
        :param original_base_res: 模板采集时的基准分辨率（默认1920×1080，与用户模板一致）
        """
        self.logger = logger or self._create_default_logger()
        self.template_dir = template_dir
        self.templates: Dict[str, np.ndarray] = {}  # 存储模板图像: 名称 -> 图像矩阵
        self.coord_transformer = coord_transformer  # 坐标转换器实例
        self.original_base_res = original_base_res  # 模板原始基准分辨率（关键新增）
        
        # 确保模板目录存在
        if not os.path.exists(self.template_dir):
            os.makedirs(self.template_dir)
            self.logger.info(f"创建模板目录: {self.template_dir}")
        
        # 加载目录中的所有模板
        self.load_all_templates()
        self.logger.info(
            f"图像处理器初始化完成 | 加载模板数: {len(self.templates)} | "
            f"模板原始基准分辨率: {self.original_base_res}"
        )

    def _create_default_logger(self) -> logging.Logger:
        """创建默认日志器（无外部日志时使用）"""
        logger = logging.getLogger("ImageProcessor")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def load_template(self, template_name: str, template_path: Optional[str] = None) -> bool:
        """加载单个模板图像（保持不变）"""
        try:
            # 确定模板路径
            if not template_path:
                template_path = os.path.join(self.template_dir, f"{template_name}.png")
            
            # 检查文件是否存在
            if not os.path.exists(template_path):
                self.logger.error(f"模板文件不存在: {template_path}")
                return False
            
            # 读取模板（灰度图，便于匹配）
            template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            if template is None:
                self.logger.error(f"无法读取模板文件: {template_path}（文件损坏或格式错误）")
                return False
            
            self.templates[template_name] = template
            self.logger.debug(
                f"模板加载成功: {template_name} | 原始尺寸: {template.shape[:2]} | "
                f"基于基准分辨率: {self.original_base_res}"
            )
            return True
        except Exception as e:
            self.logger.error(f"加载模板失败: {str(e)}", exc_info=True)
            return False

    def load_all_templates(self) -> int:
        """加载模板目录中的所有PNG模板（包括子目录，保持不变）"""
        loaded = 0
        if not os.path.isdir(self.template_dir):
            self.logger.warning(f"模板目录不存在: {self.template_dir}")
            return 0
        
        # 递归搜索所有子目录中的PNG文件
        for root, dirs, files in os.walk(self.template_dir):
            for filename in files:
                if filename.lower().endswith(".png"):
                    # 使用相对路径作为模板名称，避免重名冲突
                    rel_path = os.path.relpath(root, self.template_dir)
                    if rel_path == ".":
                        template_name = os.path.splitext(filename)[0]
                    else:
                        template_name = os.path.join(rel_path, os.path.splitext(filename)[0]).replace('\\', '/')
                    
                    template_path = os.path.join(root, filename)
                    if self.load_template(template_name, template_path):
                        loaded += 1
        
        self.logger.info(f"从目录加载模板完成: {loaded}个模板")
        return loaded

    def get_template(self, template_name: str) -> Optional[np.ndarray]:
        """获取已加载的模板（保持不变）"""
        # 打印调试信息：确认传入的模板名和已加载的模板列表
        loaded_names = list(self.templates.keys())
        self.logger.debug(f"尝试获取模板: {template_name} | 已加载模板数: {len(loaded_names)}")
        
        # 从字典获取模板（不存在则返回None）
        template = self.templates.get(template_name)
        
        # 仅判断是否为None（不触碰numpy数组的真值判断）
        if template is None:
            self.logger.warning(f"未找到模板: {template_name}（尝试重新加载）")
            # 尝试重新加载模板
            if self.load_template(template_name):
                # 重新加载后再次获取（确保拿到最新值）
                template = self.templates.get(template_name)
                if template is not None:
                    self.logger.info(f"模板重新加载成功: {template_name} | 尺寸: {template.shape[:2]}")
                else:
                    self.logger.error(f"模板重新加载失败: {template_name}（加载后仍为None）")
            else:
                self.logger.error(f"模板重新加载失败: {template_name}（文件不存在或读取错误）")
        if template is not None:
            self.logger.debug(f"返回模板: {template_name} | 类型: {type(template)} | 形状: {template.shape}")
        else:
            self.logger.debug(f"返回模板: {template_name} | 结果: None")
        return template

    def save_template(self, template_name: str, image: np.ndarray) -> bool:
        """保存图像作为模板（保持不变）"""
        try:
            template_path = os.path.join(self.template_dir, f"{template_name}.png")
            # 确保是灰度图
            if len(image.shape) == 3:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            # 检查图像是否有效
            if image is None:
                self.logger.error("无法保存模板：输入图像为None")
                return False
            cv2.imwrite(template_path, image)
            # 立即加载新模板
            self.load_template(template_name, template_path)
            self.logger.info(f"模板保存成功: {template_name} -> {template_path} | 尺寸: {image.shape[:2]}")
            return True
        except Exception as e:
            self.logger.error(f"保存模板失败: {str(e)}", exc_info=True)
            return False

    def remove_template(self, template_name: str) -> bool:
        """删除模板（保持不变）"""
        if template_name in self.templates:
            del self.templates[template_name]
            # 删除文件
            template_path = os.path.join(self.template_dir, f"{template_name}.png")
            if os.path.exists(template_path):
                os.remove(template_path)
                self.logger.info(f"模板文件已删除: {template_path}")
            self.logger.info(f"模板已移除: {template_name}")
            return True
        self.logger.warning(f"无法删除模板: {template_name}（不存在）")
        return False

    def _scale_template_to_current_size(self, template: np.ndarray) -> Optional[np.ndarray]:
        """
        核心修复：将1920×1080的模板缩放到“当前窗口逻辑尺寸”（与截图尺寸一致）
        :param template: 原始模板（1920×1080基准）
        :return: 缩放后的模板（与当前截图尺寸同比例）
        """
        if not self.coord_transformer:
            self.logger.warning("无坐标转换器，无法缩放模板，使用原始尺寸")
            return template
        
        # 获取当前窗口逻辑尺寸（截图尺寸）和原始基准尺寸
        curr_client_size = self.coord_transformer._current_client_size  # (宽, 高)
        orig_base_w, orig_base_h = self.original_base_res
        curr_w, curr_h = curr_client_size
        
        # 校验尺寸有效性
        if orig_base_w <= 0 or orig_base_h <= 0 or curr_w <= 0 or curr_h <= 0:
            self.logger.error(
                f"无效尺寸，无法缩放模板 | 原始基准: {orig_base_w}x{orig_base_h} | "
                f"当前客户区: {curr_w}x{curr_h}"
            )
            return template
        
        # 计算缩放比例（按原始基准与当前窗口的比例，保持宽高比）
        scale_ratio = min(curr_w / orig_base_w, curr_h / orig_base_h)
        # 计算缩放后的模板尺寸（确保为整数）
        scaled_template_w = int(round(template.shape[1] * scale_ratio))
        scaled_template_h = int(round(template.shape[0] * scale_ratio))
        
        # 避免缩放后尺寸为0
        scaled_template_w = max(10, scaled_template_w)  # 最小10px宽
        scaled_template_h = max(10, scaled_template_h)  # 最小10px高
        
        # 缩放模板（缩小用INTER_AREA，放大用INTER_CUBIC，保持清晰度）
        if scale_ratio < 1.0:
            interpolation = cv2.INTER_AREA  # 缩小用区域插值，更清晰
        else:
            interpolation = cv2.INTER_CUBIC  # 放大用立方插值，更清晰
        
        scaled_template = cv2.resize(
            template,
            (scaled_template_w, scaled_template_h),
            interpolation=interpolation
        )
        
        self.logger.debug(
            f"模板缩放完成 | 原始尺寸: {template.shape[:2]} | "
            f"缩放比例: {scale_ratio:.2f} | "
            f"缩放后尺寸: {scaled_template.shape[:2]} | "
            f"当前窗口逻辑尺寸: {curr_w}x{curr_h}"
        )
        return scaled_template

    def match_template(
        self,
        image: np.ndarray,
        template: Union[str, np.ndarray],
        threshold: float = 0.6,
        is_base_template: bool = True,  # 是否为1920×1080基准模板
        preprocess_params: Optional[Dict] = None
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        修复模板匹配：先缩放模板到当前窗口尺寸，再匹配（解决窗口化不匹配问题）
        """
        try:
            # 1. 获取并验证模板图像
            if isinstance(template, str):
                template_img = self.get_template(template)
                if template_img is None:
                    self.logger.error(f"模板匹配失败：模板 {template} 不存在或加载错误")
                    return None
            else:
                template_img = template
                if len(template_img.shape) == 3:
                    template_img = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
                if template_img is None:
                    self.logger.error("模板匹配失败：传入的模板图像为None")
                    return None
            
            # 2. 核心修复：如果是基础模板（1920×1080），先缩放到当前窗口尺寸
            if is_base_template:
                template_img = self._scale_template_to_current_size(template_img)
                if template_img is None:
                    self.logger.error("模板缩放失败，终止匹配")
                    return None
            
            # 3. 验证待匹配图像（截图）
            if image is None:
                self.logger.error("模板匹配失败：待匹配图像为None")
                return None
            # 转为灰度图（与模板一致）
            if len(image.shape) == 3:
                gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray_image = image
            
            # 4. 校验模板尺寸是否小于等于截图尺寸（匹配前提）
            img_h, img_w = gray_image.shape
            templ_h, templ_w = template_img.shape
            if templ_w > img_w or templ_h > img_h:
                self.logger.error(
                    f"模板尺寸超过截图尺寸，无法匹配 | "
                    f"模板: {templ_w}x{templ_h} | 截图: {img_w}x{img_h}"
                )
                return None
            
            # 5. 预处理（原图和模板执行相同处理，确保一致性）
            # 默认预处理参数（适合游戏场景）
            default_preprocess = {
                "blur": True,
                "blur_ksize": (3, 3),
                "threshold": True,
                "adaptive_threshold": True,
                "block_size": 11,
                "c": 2
            }
            # 合并用户传入的参数（覆盖默认）
            preprocess_cfg = {**default_preprocess, **(preprocess_params or {})}
            
            processed_image = self.preprocess_image(gray_image, **preprocess_cfg)
            processed_template = self.preprocess_image(template_img, **preprocess_cfg)
            
            # 6. 执行模板匹配
            result = cv2.matchTemplate(processed_image, processed_template, cv2.TM_CCOEFF_NORMED)
            
            # 打印最大匹配度（调试用）
            max_val = np.max(result) if result.size > 0 else 0.0
            self.logger.debug(
                f"模板匹配 | 名称: {template if isinstance(template, str) else '自定义'} | "
                f"最大匹配度: {max_val:.4f} | 阈值: {threshold} | "
                f"使用模板尺寸: {templ_w}x{templ_h}"
            )

            # 7. 筛选匹配结果（高于阈值）
            locations = np.where(result >= threshold)
            if locations[0].size == 0:
                self.logger.debug(f"未找到匹配（匹配度低于阈值 {threshold}）")
                return None
            
            # 8. 找到最佳匹配（最大匹配度对应的位置）
            max_loc = np.unravel_index(np.argmax(result), result.shape)
            x, y = max_loc[1], max_loc[0]  # 注意：result的坐标是(y,x)，需转(x,y)
            self.logger.debug(
                f"匹配成功 | 截图内坐标: ({x},{y}) | 模板尺寸: ({templ_w},{templ_h}) | "
                f"匹配度: {max_val:.4f}"
            )
            
            # 9. 无需再转换坐标（模板已缩放，坐标直接是当前窗口逻辑尺寸的坐标）
            return (x, y, templ_w, templ_h)
        except Exception as e:
            self.logger.error(f"模板匹配失败: {str(e)}", exc_info=True)
            return None

    def get_roi_region(
        self,
        image: np.ndarray,
        roi: Tuple[int, int, int, int],
        is_base_roi: bool = False
    ) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        """
        修复ROI转换方法名错误：convert_base_roi_to_client → convert_original_rect_to_current_client
        """
        try:
            # 验证输入图像
            if image is None:
                self.logger.error("获取ROI失败：输入图像为None")
                raise ValueError("Input image cannot be None")
            
            x, y, w, h = roi
            
            # 如果是基准ROI（1920×1080），转换为当前客户区坐标
            if is_base_roi and self.coord_transformer:
                try:
                    # 修复：调用正确的矩形转换方法
                    converted_roi = self.coord_transformer.convert_original_rect_to_current_client(roi)
                    x, y, w, h = converted_roi
                    self.logger.debug(f"ROI转换成功: 基准ROI {roi} -> 当前ROI ({x},{y},{w},{h})")
                except Exception as e:
                    self.logger.warning(f"ROI转换失败，使用原始ROI: {str(e)}")
            
            # 确保ROI在图像范围内（防止越界）
            img_h, img_w = image.shape[:2]
            x = max(0, min(x, img_w - 1))
            y = max(0, min(y, img_h - 1))
            w = max(1, min(w, img_w - x))
            h = max(1, min(h, img_h - y))
            
            # 提取ROI
            roi_image = image[y:y+h, x:x+w]
            self.logger.debug(f"获取ROI成功 | 最终ROI: ({x},{y},{w},{h}) | ROI尺寸: {roi_image.shape[:2]}")
            return (roi_image, (x, y, w, h))
        except Exception as e:
            self.logger.error(f"获取ROI失败: {str(e)}", exc_info=True)
            # 异常时返回原图和全图ROI（避免后续报错）
            if image is not None:
                full_roi = (0, 0, image.shape[1], image.shape[0])
                return (image, full_roi)
            else:
                raise ValueError("Cannot return ROI: input image is None")

    def find_multiple_matches(
        self,
        image: np.ndarray,
        template: Union[str, np.ndarray],
        threshold: float = 0.8,
        max_matches: int = 10,
        is_base_template: bool = True
    ) -> List[Tuple[int, int, int, int]]:
        """
        修复多模板匹配：先缩放模板再匹配（与match_template逻辑一致）
        """
        matches = []
        try:
            # 1. 获取并验证模板图像
            if isinstance(template, str):
                template_img = self.get_template(template)
                if template_img is None:
                    self.logger.error(f"多模板匹配失败：模板 {template} 不存在或加载错误")
                    return matches
            else:
                template_img = template
                if len(template_img.shape) == 3:
                    template_img = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
                if template_img is None:
                    self.logger.error("多模板匹配失败：传入的模板图像为None")
                    return matches
            
            # 2. 核心修复：如果是基础模板，先缩放到当前窗口尺寸
            if is_base_template:
                template_img = self._scale_template_to_current_size(template_img)
                if template_img is None:
                    self.logger.error("模板缩放失败，终止多匹配")
                    return matches
            
            # 3. 验证待匹配图像
            if image is None:
                self.logger.error("多模板匹配失败：待匹配图像为None")
                return matches
            # 转为灰度图
            if len(image.shape) == 3:
                gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray_image = image
            
            # 4. 校验模板尺寸是否小于等于截图尺寸
            img_h, img_w = gray_image.shape
            templ_h, templ_w = template_img.shape
            if templ_w > img_w or templ_h > img_h:
                self.logger.error(
                    f"模板尺寸超过截图尺寸，无法多匹配 | "
                    f"模板: {templ_w}x{templ_h} | 截图: {img_w}x{img_h}"
                )
                return matches
            
            # 5. 执行模板匹配
            result = cv2.matchTemplate(gray_image, template_img, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)
            
            # 6. 收集匹配位置（转换为(x, y)格式）
            match_points = list(zip(*locations[::-1]))  # 从(y,x)转为(x,y)
            if len(match_points) == 0:
                self.logger.debug(
                    f"未找到多匹配区域 | 模板: {template if isinstance(template, str) else '自定义图像'} | "
                    f"阈值: {threshold} | 模板尺寸: {templ_w}x{templ_h}"
                )
                return matches
            
            # 7. 去重（避免重叠区域）
            used = set()
            for (x, y) in match_points:
                # 检查是否与已添加的匹配重叠（基于模板尺寸的1/2作为阈值）
                overlap = False
                for (ux, uy, uw, uh) in matches:
                    if (abs(x - ux) < templ_w // 2) and (abs(y - uy) < templ_h // 2):
                        overlap = True
                        break
                if not overlap:
                    # 无需转换坐标（模板已缩放，坐标直接可用）
                    matches.append((x, y, templ_w, templ_h))
                    self.logger.debug(
                        f"多匹配添加成功 | 坐标: ({x},{y}) | 尺寸: ({templ_w},{templ_h}) | "
                        f"当前匹配数: {len(matches)}/{max_matches}"
                    )
                    # 达到最大匹配数则停止
                    if len(matches) >= max_matches:
                        break
            
            self.logger.debug(
                f"多模板匹配完成 | 找到{len(matches)}个非重叠区域 | "
                f"模板: {template if isinstance(template, str) else '自定义图像'} | "
                f"模板尺寸: {templ_w}x{templ_h}"
            )
            return matches
        except Exception as e:
            self.logger.error(f"多模板匹配失败: {str(e)}", exc_info=True)
            return matches

    def preprocess_image(
        self,
        image: np.ndarray,
        gray: bool = True,
        blur: bool = True,
        blur_ksize: Tuple[int, int] = (3, 3),
        threshold: bool = True,
        adaptive_threshold: bool = True,
        block_size: int = 11,
        c: int = 2
    ) -> np.ndarray:
        """图像预处理（保持不变，确保与模板处理一致）"""
        try:
            if image is None:
                self.logger.error("图像预处理失败：输入图像为None")
                raise ValueError("Input image cannot be None")
            
            result = image.copy()
            
            # 1. 转为灰度图
            if gray and len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
                self.logger.debug("预处理：已转为灰度图")
            
            # 2. 高斯模糊去噪
            if blur and blur_ksize[0] > 1 and blur_ksize[1] > 1:
                # 确保核大小为奇数
                ksize = (
                    blur_ksize[0] if blur_ksize[0] % 2 == 1 else blur_ksize[0] + 1,
                    blur_ksize[1] if blur_ksize[1] % 2 == 1 else blur_ksize[1] + 1
                )
                result = cv2.GaussianBlur(result, ksize, 0)
                self.logger.debug(f"预处理：已高斯模糊（核大小: {ksize}）")
            
            # 3. 二值化（增强对比度）
            if threshold:
                if adaptive_threshold:
                    # 自适应阈值（适合明暗不均的游戏画面）
                    result = cv2.adaptiveThreshold(
                        result, 255,
                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY,
                        block_size if block_size % 2 == 1 else block_size + 1,
                        c
                    )
                    self.logger.debug(f"预处理：已自适应二值化（块大小: {block_size}, C: {c}）")
                else:
                    # 固定阈值（备用选项）
                    _, result = cv2.threshold(result, 127, 255, cv2.THRESH_BINARY)
                    self.logger.debug("预处理：已固定二值化")
            
            return result
        except Exception as e:
            self.logger.error(f"图像预处理失败: {str(e)}", exc_info=True)
            return image if image is not None else np.array([])

    def get_center(self, rect: Union[Tuple[int, int, int, int], np.ndarray]) -> Tuple[int, int]:
        """计算矩形区域的中心坐标（保持不变）"""
        if rect is None:
            self.logger.warning("无效的矩形坐标: None，无法计算中心")
            return (0, 0)
        
        # 若为numpy数组，先转换为Python元组
        if isinstance(rect, np.ndarray):
            rect = tuple(rect.tolist())
        
        # 校验是否为4元素的序列
        if not isinstance(rect, (tuple, list)) or len(rect) != 4:
            self.logger.warning(f"无效的矩形坐标: {rect}（需4元素元组/列表），无法计算中心")
            return (0, 0)
        
        # 校验每个元素是否为数字
        try:
            x, y, w, h = map(int, rect)  # 强制转换为整数
            center_x = x + w // 2
            center_y = y + h // 2
            self.logger.debug(f"计算矩形中心: {rect} -> ({center_x},{center_y})")
            return (center_x, center_y)
        except (ValueError, TypeError):
            self.logger.warning(f"矩形坐标包含非数字值: {rect}，无法计算中心")
            return (0, 0)

    def __len__(self) -> int:
        """返回已加载的模板数量（保持不变）"""
        return len(self.templates)