import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional, Union
from dataclasses import dataclass
from airtest.core.cv import Template
from airtest import aircv
from concurrent.futures import ThreadPoolExecutor, as_completed
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
class MatchResult:
    """匹配结果数据类"""
    name: str
    position: Optional[Tuple[int, int]]
    confidence: float
    template: Optional[Template] = None

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

    def __del__(self):
        """析构函数"""
        self.executor.shutdown()

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
            
        Raises:
            ValueError: 当图像加载失败时抛出
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
            print(f"[ERROR] 加载模板失败: {str(e)}")
            raise ValueError(f"无法加载模板图像: {path}")

    def _scale_image(
        self,
        image: np.ndarray,
        target_resolution: Tuple[int, int],
        scale_strategy: ScaleStrategy
    ) -> np.ndarray:
        """
        内部方法：根据策略缩放图像 (自动处理不同分辨率适配)
        
        Args:
            image: 原始图像 (OpenCV格式)
            target_resolution: 目标分辨率 (宽, 高)
            scale_strategy: 缩放策略
            
        Returns:
            缩放后的图像
        """
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
        original_roi: Optional[Tuple[float, float, float, float]],
        from_resolution: Tuple[int, int],
        to_resolution: Tuple[int, int]
    ) -> Optional[Tuple[float, float, float, float]]:
        """
        内部方法：转换ROI坐标到新分辨率 (保持相对位置)
        
        Args:
            original_roi: 原始ROI区域 (x1, y1, x2, y2) 0-1范围
            from_resolution: 原始分辨率 (宽, 高)
            to_resolution: 目标分辨率 (宽, 高)
            
        Returns:
            转换后的ROI区域
        """
        if original_roi is None:
            return None
            
        from_w, from_h = from_resolution
        x1, y1, x2, y2 = original_roi
        
        # 计算绝对坐标
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
        
        Args:
            name: 模板名称
            target_resolution: 目标分辨率 (宽, 高)
            
        Returns:
            缩放后的模板对象
            
        Raises:
            ValueError: 当模板不存在或图像加载失败时抛出
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
        
        Args:
            screen: 屏幕截图 (OpenCV格式)
            roi: ROI区域 (x1, y1, x2, y2) 0-1范围
            
        Returns:
            ROI区域图像
        """
        if roi is None:
            return screen

        h, w = screen.shape[:2]
        x1, y1, x2, y2 = roi
        abs_x1 = int(w * x1)
        abs_y1 = int(h * y1)
        abs_x2 = int(w * x2)
        abs_y2 = int(h * y2)

        # 确保不越界
        abs_x1 = max(0, min(abs_x1, w-1))
        abs_y1 = max(0, min(abs_y1, h-1))
        abs_x2 = max(0, min(abs_x2, w))
        abs_y2 = max(0, min(abs_y2, h))
        
        return screen[abs_y1:abs_y2, abs_x1:abs_x2]

    def match_template(
        self,
        screen: np.ndarray,
        template_name: str,
        target_resolution: Tuple[int, int],
        method: MatchMethod = DEFAULT_MATCH_METHOD
    ) -> MatchResult:
        """
        模板匹配 (自动处理不同分辨率适配)
        
        Args:
            screen: 屏幕截图 (OpenCV格式)
            template_name: 模板名称
            target_resolution: 目标分辨率 (宽, 高)
            method: 匹配方法
            
        Returns:
            MatchResult对象包含匹配结果
        """
        if template_name not in self.templates:
            print(f"[WARN] 模板 {template_name} 未加载")
            return MatchResult(name=template_name, position=None, confidence=0.0)

        template_info = self.templates[template_name]
        
        # 自动缩放模板到目标分辨率
        if (template_info.scaled_template is None or 
            template_info.last_resolution != target_resolution):
            try:
                self.scale_template(template_name, target_resolution)
            except Exception as e:
                print(f"[ERROR] 缩放模板失败: {str(e)}")
                return MatchResult(
                    name=template_name,
                    position=None,
                    confidence=0.0,
                    template=template_info.template
                )

        # 获取已转换的ROI区域
        roi_img = self.get_roi_region(screen, template_info.roi)
        template_img = template_info.scaled_template.image
        
        # 处理多通道图像
        if len(template_img.shape) == 3 and len(roi_img.shape) == 2:
            template_img = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
        
        try:
            result = cv2.matchTemplate(roi_img, template_img, method.value)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            if max_val >= template_info.threshold:
                h, w = template_img.shape[:2]
                center_x = max_loc[0] + w // 2
                center_y = max_loc[1] + h // 2
                
                # 转换到全局坐标
                if template_info.roi:
                    scr_h, scr_w = screen.shape[:2]
                    roi_x1, roi_y1, _, _ = template_info.roi
                    center_x += int(scr_w * roi_x1)
                    center_y += int(scr_h * roi_y1)
                
                return MatchResult(
                    name=template_name,
                    position=(center_x, center_y),
                    confidence=float(max_val),
                    template=template_info.scaled_template
                )
        except Exception as e:
            print(f"[ERROR] 模板匹配错误: {str(e)}")
        
        return MatchResult(
            name=template_name,
            position=None,
            confidence=0.0,
            template=template_info.scaled_template
        )

    def preprocess_for_ocr(
        self, 
        image: np.ndarray,
        denoise: bool = True,
        clahe_clip: float = 2.0,
        clahe_grid: Tuple[int, int] = (8, 8)
    ) -> np.ndarray:
        """
        为OCR优化图像预处理
        
        Args:
            image: 输入图像 (OpenCV格式)
            denoise: 是否启用降噪
            clahe_clip: CLAHE对比度限制
            clahe_grid: CLAHE网格大小
            
        Returns:
            处理后的图像
        """
        # 转换为灰度图
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # 应用CLAHE增强对比度
        clahe = cv2.createCLAHE(
            clipLimit=clahe_clip,
            tileGridSize=clahe_grid
        )
        enhanced = clahe.apply(gray)

        # 自适应阈值二值化
        binary = cv2.adaptiveThreshold(
            enhanced, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        # 降噪
        if denoise:
            binary = cv2.fastNlMeansDenoising(binary, None, 10, 7, 21)

        return binary

    def crop_image(
        self, 
        image: np.ndarray, 
        region: Tuple[int, int, int, int]
    ) -> np.ndarray:
        """
        裁剪图像
        
        Args:
            image: 输入图像 (OpenCV格式)
            region: 裁剪区域 (x, y, width, height)
            
        Returns:
            裁剪后的图像
        """
        return aircv.crop_image(image, region)

    def find_color(
        self,
        image: np.ndarray,
        color: Tuple[int, int, int],
        threshold: float = 0.9,
        color_range: Optional[Tuple[int, int, int]] = None
    ) -> Optional[Tuple[int, int]]:
        """
        在图像中查找指定颜色
        
        Args:
            image: 输入图像 (OpenCV格式)
            color: 目标颜色 (B, G, R)
            threshold: 颜色匹配阈值 (0-1)
            color_range: 颜色范围容差 (B_range, G_range, R_range)
            
        Returns:
            颜色区域的中心点坐标 (x, y) 或 None
        """
        try:
            if color_range is not None:
                # 使用颜色范围匹配
                lower = np.array([
                    max(0, color[0]-color_range[0]),
                    max(0, color[1]-color_range[1]),
                    max(0, color[2]-color_range[2])
                ])
                upper = np.array([
                    min(255, color[0]+color_range[0]),
                    min(255, color[1]+color_range[1]),
                    min(255, color[2]+color_range[2])
                ])
                mask = cv2.inRange(image, lower, upper)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                if contours:
                    # 返回最大轮廓的中心点
                    max_contour = max(contours, key=cv2.contourArea)
                    M = cv2.moments(max_contour)
                    if M["m00"] > 0:
                        cX = int(M["m10"] / M["m00"])
                        cY = int(M["m01"] / M["m00"])
                        return (cX, cY)
            else:
                # 使用airtest方法
                color_template = aircv.create_color_template(color)
                pos = color_template.match_in(image)
                if pos and color_template.get_score() >= threshold:
                    return (int(pos[0]), int(pos[1]))
        except Exception as e:
            print(f"[ERROR] 颜色匹配错误: {str(e)}")
        
        return None

    def match_multiple_templates(
        self,
        screen: np.ndarray,
        template_names: List[str],
        target_resolution: Tuple[int, int],
        threshold: float = 0.8,
        method: MatchMethod = DEFAULT_MATCH_METHOD,
        parallel: bool = True
    ) -> MatchResult:
        """
        同时匹配多个模板并返回最佳结果
        
        Args:
            screen: 屏幕截图 (OpenCV格式)
            template_names: 模板名称列表
            target_resolution: 目标分辨率 (宽, 高)
            threshold: 匹配阈值 (0-1)
            method: 匹配方法
            parallel: 是否并行匹配
            
        Returns:
            最佳匹配结果 (MatchResult对象)
        """
        best_match = MatchResult(name="", position=None, confidence=0.0)
        
        if parallel:
            # 并行匹配
            futures = {}
            for name in template_names:
                future = self.executor.submit(
                    self.match_template,
                    screen.copy(),  # 避免多线程数据竞争
                    name,
                    target_resolution,
                    method
                )
                futures[future] = name
            
            for future in as_completed(futures):
                result = future.result()
                if result.confidence > best_match.confidence:
                    best_match = result
        else:
            # 串行匹配
            for name in template_names:
                result = self.match_template(screen, name, target_resolution, method)
                if result.confidence > best_match.confidence:
                    best_match = result
        
        return best_match if best_match.confidence >= threshold else MatchResult(
            name="",
            position=None,
            confidence=0.0
        )

    def find_shapes(
        self,
        image: np.ndarray,
        shape_type: str = "rectangle",
        min_area: int = 100,
        max_results: int = 10,
        canny_threshold1: int = 50,
        canny_threshold2: int = 150
    ) -> List[Union[Tuple[int, int, int, int], Tuple[int, int, int]]]:
        """
        查找图像中的形状
        
        Args:
            image: 输入图像 (OpenCV格式)
            shape_type: 形状类型 ("rectangle", "circle")
            min_area: 最小区域面积
            max_results: 最大返回结果数
            canny_threshold1: Canny边缘检测阈值1
            canny_threshold2: Canny边缘检测阈值2
            
        Returns:
            形状位置列表:
            - 矩形: (x, y, w, h)
            - 圆形: (x, y, radius)
        """
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()
            
            # 边缘检测
            edges = cv2.Canny(gray, canny_threshold1, canny_threshold2)
            
            # 查找轮廓
            contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            
            results = []
            for cnt in sorted(contours, key=cv2.contourArea, reverse=True):
                area = cv2.contourArea(cnt)
                if area < min_area:
                    continue
                
                if shape_type == "rectangle":
                    x, y, w, h = cv2.boundingRect(cnt)
                    results.append((x, y, w, h))
                elif shape_type == "circle":
                    (x, y), radius = cv2.minEnclosingCircle(cnt)
                    results.append((int(x), int(y), int(radius)))
                
                if len(results) >= max_results:
                    break
            
            return results
        except Exception as e:
            print(f"[ERROR] 形状查找错误: {str(e)}")
            return []

    def close(self):
        """释放资源"""
        self.executor.shutdown()