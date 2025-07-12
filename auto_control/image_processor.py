import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional, Union
from dataclasses import dataclass
from airtest.core.cv import Template
from airtest import aircv
from concurrent.futures import ThreadPoolExecutor
from .config.control__config import (
    ScaleStrategy,
    MatchMethod,
    DEFAULT_RESOLUTION,
    DEFAULT_THRESHOLD,
    DEFAULT_SCALE_STRATEGY,
    DEFAULT_MATCH_METHOD,
    MAX_WORKERS
)

@dataclass
class TemplateInfo:
    """模板信息数据类"""
    name: str
    template: Template
    path: str
    roi: Optional[Tuple[float, float, float, float]] = None
    threshold: float = DEFAULT_THRESHOLD
    scale_strategy: ScaleStrategy = DEFAULT_SCALE_STRATEGY
    scaled_template: Optional[Template] = None
    last_resolution: Optional[Tuple[int, int]] = None

class ImageProcessor:
    def __init__(self, base_resolution: Tuple[int, int] = DEFAULT_RESOLUTION, max_workers: int = MAX_WORKERS):
        """
        初始化图像处理器
        
        Args:
            base_resolution: 设计基准分辨率 (宽, 高)
            max_workers: 线程池最大工作线程数
        """
        self.base_resolution = base_resolution
        self.templates: Dict[str, TemplateInfo] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def update_resolution(self, new_resolution: Tuple[int, int]) -> None:
        """
        更新基准分辨率
        
        Args:
            new_resolution: 新的基准分辨率 (宽, 高)
        """
        self.base_resolution = new_resolution
        # 清除所有已缩放的模板缓存
        for name in self.templates:
            self.templates[name].scaled_template = None
            self.templates[name].last_resolution = None

    def load_template(
        self,
        name: str,
        path: str,
        roi: Optional[Tuple[float, float, float, float]] = None,
        threshold: float = DEFAULT_THRESHOLD,
        scale_strategy: ScaleStrategy = DEFAULT_SCALE_STRATEGY
    ) -> Template:
        """
        加载模板图像 (基于1920x1080分辨率设计的)
        
        Args:
            name: 模板名称
            path: 文件路径
            roi: 基于1920x1080的相对ROI区域 (x1, y1, x2, y2) 0-1范围
            threshold: 匹配阈值 (0-1)
            scale_strategy: 缩放策略
            
        Returns:
            加载的模板对象
        """
        try:
            template = Template(path, threshold=threshold)
            self.templates[name] = TemplateInfo(
                name=name,
                template=template,
                path=path,
                roi=roi,
                threshold=threshold,
                scale_strategy=scale_strategy
            )
            return template
        except Exception as e:
            print(f"加载模板失败: {str(e)}")
            raise

    def _scale_image(
        self,
        image: np.ndarray,
        target_resolution: Tuple[int, int],
        scale_strategy: ScaleStrategy
    ) -> np.ndarray:
        """
        内部方法：根据策略缩放图像 (自动处理不同分辨率适配)
        """
        # 计算从1920x1080到目标分辨率的缩放比例
        base_w, base_h = DEFAULT_RESOLUTION
        target_w, target_h = target_resolution
        
        if scale_strategy == ScaleStrategy.FIT:
            # 保持宽高比，按最小比例缩放
            scale = min(target_w / base_w, target_h / base_h)
            return cv2.resize(image, None, fx=scale, fy=scale)
        elif scale_strategy == ScaleStrategy.STRETCH:
            # 拉伸到目标分辨率
            return cv2.resize(image, (target_w, target_h))
        elif scale_strategy == ScaleStrategy.CROP:
            # 按最大比例缩放后裁剪
            scale = max(target_w / base_w, target_h / base_h)
            scaled_img = cv2.resize(image, None, fx=scale, fy=scale)
            h, w = scaled_img.shape[:2]
            crop_x = max(0, (w - target_w) // 2)
            crop_y = max(0, (h - target_h) // 2)
            return scaled_img[crop_y:crop_y+target_h, crop_x:crop_x+target_w]
        else:
            scale = min(target_w / base_w, target_h / base_h)
            return cv2.resize(image, None, fx=scale, fy=scale)

    def _convert_roi(
        self,
        original_roi: Tuple[float, float, float, float],
        from_resolution: Tuple[int, int],
        to_resolution: Tuple[int, int]
    ) -> Tuple[float, float, float, float]:
        """
        内部方法：转换ROI坐标到新分辨率 (保持相对位置)
        """
        if original_roi is None:
            return None
            
        # 原始ROI的绝对坐标 (基于1920x1080)
        from_w, from_h = from_resolution
        x1, y1, x2, y2 = original_roi
        abs_x1 = x1 * from_w
        abs_y1 = y1 * from_h
        abs_x2 = x2 * from_w
        abs_y2 = y2 * from_h
        
        # 转换到新分辨率的相对坐标
        to_w, to_h = to_resolution
        new_x1 = abs_x1 / to_w
        new_y1 = abs_y1 / to_h
        new_x2 = abs_x2 / to_w
        new_y2 = abs_y2 / to_h
        
        return (new_x1, new_y1, new_x2, new_y2)

    def scale_template(self, name: str, target_resolution: Tuple[int, int]) -> Template:
        """
        根据目标分辨率缩放模板 (自动处理ROI转换)
        """
        if name not in self.templates:
            raise ValueError(f"模板 {name} 未加载")

        template_info = self.templates[name]
        orig_img = cv2.imread(template_info.path, cv2.IMREAD_UNCHANGED)
        
        if orig_img is None:
            raise ValueError(f"无法加载模板图像: {template_info.path}")

        # 缩放图像
        scaled_img = self._scale_image(orig_img, target_resolution, template_info.scale_strategy)
        scaled_template = Template(scaled_img, threshold=template_info.threshold)
        
        # 更新ROI坐标 (自动转换到新分辨率)
        if template_info.roi:
            template_info.roi = self._convert_roi(
                template_info.roi,
                DEFAULT_RESOLUTION,
                target_resolution
            )
        
        # 更新缓存
        template_info.scaled_template = scaled_template
        template_info.last_resolution = target_resolution
        
        return scaled_template

    def get_roi_region(
        self,
        screen: np.ndarray,
        roi: Optional[Tuple[float, float, float, float]]
    ) -> np.ndarray:
        """
        从屏幕截图中提取ROI区域 (自动适配当前分辨率)
        """
        if roi is None:
            return screen

        h, w = screen.shape[:2]
        x1, y1, x2, y2 = roi
        abs_x1 = int(w * x1)
        abs_y1 = int(h * y1)
        abs_x2 = int(w * x2)
        abs_y2 = int(h * y2)

        return screen[abs_y1:abs_y2, abs_x1:abs_x2]

    # ... (其他方法保持与之前相同，只需修改match_template中的roi处理) ...

    def match_template(
        self,
        screen: np.ndarray,
        template_name: str,
        target_resolution: Tuple[int, int],
        method: MatchMethod = DEFAULT_MATCH_METHOD
    ) -> Tuple[Optional[Tuple[int, int]], float]:
        """
        模板匹配 (自动处理不同分辨率适配)
        """
        if template_name not in self.templates:
            print(f"模板 {template_name} 未加载")
            return None, 0.0

        template_info = self.templates[template_name]
        
        # 自动缩放模板到目标分辨率
        if (template_info.scaled_template is None or 
            template_info.last_resolution != target_resolution):
            try:
                self.scale_template(template_name, target_resolution)
            except Exception as e:
                print(f"缩放模板失败: {str(e)}")
                return None, 0.0

        # 获取已转换的ROI区域
        roi_img = self.get_roi_region(screen, template_info.roi)
        template_img = template_info.scaled_template.image
        
        # ... (其余匹配逻辑与之前相同) ...