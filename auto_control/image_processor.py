import cv2
import numpy as np
from airtest.core.cv import Template

class ImageProcessor:
    def __init__(self, base_resolution=(1920, 1080)):
        """
        :param base_resolution: 设计基准分辨率 (宽, 高)
        """
        self.base_resolution = base_resolution
        self.templates = {}
        
    def load_template(self, name, path, roi=None, threshold=0.8, scale_strategy='fit'):
        """
        加载模板图像
        :param name: 模板名称
        :param path: 文件路径
        :param roi: 相对ROI区域 (x1, y1, x2, y2) 0-1范围
        :param threshold: 匹配阈值
        :param scale_strategy: 缩放策略 (fit, stretch, crop)
        """
        template = Template(path, threshold=threshold)
        self.templates[name] = {
            'template': template,
            'roi': roi,
            'path': path,
            'scale_strategy': scale_strategy
        }
        return template
        
    def scale_template(self, name, target_resolution):
        """
        根据目标分辨率缩放模板
        :param name: 模板名称
        :param target_resolution: 目标分辨率 (宽, 高)
        """
        if name not in self.templates:
            raise ValueError(f"模板 {name} 未加载")
            
        template_info = self.templates[name]
        orig_img = cv2.imread(template_info['path'], cv2.IMREAD_UNCHANGED)
        
        # 计算缩放比例
        scale_w = target_resolution[0] / self.base_resolution[0]
        scale_h = target_resolution[1] / self.base_resolution[1]
        
        # 应用缩放策略
        if template_info['scale_strategy'] == 'fit':
            # 保持宽高比，适应目标区域
            scale = min(scale_w, scale_h)
            scaled_img = cv2.resize(orig_img, None, fx=scale, fy=scale)
        elif template_info['scale_strategy'] == 'stretch':
            # 拉伸填充目标区域
            scaled_img = cv2.resize(orig_img, target_resolution)
        elif template_info['scale_strategy'] == 'crop':
            # 裁剪以适应目标区域
            scale = max(scale_w, scale_h)
            scaled_img = cv2.resize(orig_img, None, fx=scale, fy=scale)
            # 居中裁剪
            h, w = scaled_img.shape[:2]
            crop_x = max(0, (w - target_resolution[0]) // 2)
            crop_y = max(0, (h - target_resolution[1]) // 2)
            scaled_img = scaled_img[crop_y:crop_y+target_resolution[1], 
                                   crop_x:crop_x+target_resolution[0]]
        else:
            # 默认使用fit策略
            scale = min(scale_w, scale_h)
            scaled_img = cv2.resize(orig_img, None, fx=scale, fy=scale)
        
        # 创建新模板
        scaled_template = Template(scaled_img, threshold=template_info['template'].threshold)
        self.templates[name]['scaled_template'] = scaled_template
        return scaled_template
        
    def get_roi_region(self, screen, roi):
        """
        从屏幕截图中提取ROI区域
        :param screen: 屏幕截图 (OpenCV格式)
        :param roi: ROI区域 (x1, y1, x2, y2) 0-1范围
        :return: ROI区域图像
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
        
    def match_template(self, screen, template_name, target_resolution):
        """
        在屏幕中匹配模板
        :param screen: 屏幕截图 (OpenCV格式)
        :param template_name: 模板名称
        :param target_resolution: 目标分辨率 (宽, 高)
        :return: 匹配结果 (x, y) 或 None
        """
        if template_name not in self.templates:
            raise ValueError(f"模板 {template_name} 未加载")
            
        template_info = self.templates[template_name]
        
        # 获取或创建缩放模板
        if 'scaled_template' not in template_info:
            self.scale_template(template_name, target_resolution)
            
        template = template_info['scaled_template']
        roi = template_info['roi']
        
        # 提取ROI区域
        roi_img = self.get_roi_region(screen, roi)
        
        # 在ROI区域匹配
        result = template.match_in(roi_img)
        
        # 转换到全局坐标
        if result and roi:
            h, w = screen.shape[:2]
            x1, y1, _, _ = roi
            result = (
                int(result[0] + w * x1),
                int(result[1] + h * y1)
            )
            
        return result