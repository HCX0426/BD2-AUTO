import re

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

    def update_resolution(self, new_resolution):
        """更新基准分辨率"""
        self.base_resolution = new_resolution
        # 清除所有已缩放的模板，下次使用时重新缩放
        for name in self.templates:
            if 'scaled_template' in self.templates[name]:
                del self.templates[name]['scaled_template']

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
        scaled_template = Template(
            scaled_img, threshold=template_info['template'].threshold)
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
        """修改后的匹配方法"""
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

        # 直接使用OpenCV进行模板匹配
        try:
            # 获取模板图像数据
            template_img = cv2.imread(
                template_info['path'], cv2.IMREAD_UNCHANGED)

            # 执行模板匹配
            result = cv2.matchTemplate(
                roi_img, template_img, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            # 检查匹配阈值
            if max_val >= template.threshold:
                # 转换到全局坐标
                if roi:
                    h, w = screen.shape[:2]
                    x1, y1, _, _ = roi
                    return (
                        int(max_loc[0] + w * x1),
                        int(max_loc[1] + h * y1)
                    )
                return (int(max_loc[0]), int(max_loc[1]))
        except Exception as e:
            print(f"模板匹配错误: {str(e)}")
        return None

    def preprocess_for_ocr(self, image):
        """
        为OCR优化图像预处理
        :return: 处理后的图像
        """
        # 转换为灰度图
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 应用CLAHE增强对比度
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 自适应阈值二值化
        binary = cv2.adaptiveThreshold(
            enhanced, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        # 降噪
        denoised = cv2.fastNlMeansDenoising(binary, None, 10, 7, 21)

        return denoised

    def crop_image(self, image, region):
        """
        使用airtest方法裁剪图像
        :param image: 输入图像 (OpenCV格式)
        :param region: 裁剪区域 (x1, y1, width, height)
        :return: 裁剪后的图像
        """
        from airtest import aircv
        return aircv.crop_image(image, region)

    def find_color(self, image, color, threshold=0.9):
        """
        在图像中查找指定颜色
        :param image: 输入图像 (OpenCV格式)
        :param color: 目标颜色 (B, G, R)
        :param threshold: 颜色匹配阈值
        :return: 颜色区域的中心点坐标 (x, y) 或 None
        """
        from airtest import aircv
        from airtest.core.cv import loop_find

        # 创建颜色模板
        color_template = aircv.create_color_template(color)

        # 在图像中查找颜色
        try:
            pos = loop_find(
                color_template,
                image,
                threshold=threshold,
                timeout=0.5,
                interval=0.1
            )
            return (int(pos[0]), int(pos[1]))
        except Exception:
            return None

    def match_multiple_templates(self, screen, template_names, target_resolution, threshold=0.8):
        """
        同时匹配多个模板并返回最佳结果
        : param screen: 屏幕截图(OpenCV格式)
        : param template_names: 模板名称列表
        : param target_resolution: 目标分辨率(宽, 高)
        : param threshold: 匹配阈值
        : return: (模板名称, 坐标) 元组或(None, None)
        """
        best_score = threshold
        best_result = (None, None)

        for name in template_names:
            if name not in self.templates:
                continue

            template_info = self.templates[name]

            # 获取或创建缩放模板
            if 'scaled_template' not in template_info:
                self.scale_template(name, target_resolution)

            template = template_info['scaled_template']
            roi = template_info['roi']

            # 提取ROI区域
            roi_img = self.get_roi_region(screen, roi)

            # 获取匹配结果和置信度
            try:
                match_result = template.match_in(roi_img)
                if match_result and hasattr(template, 'get_score'):
                    score = template.get_score()
                    if score > best_score:
                        best_score = score
                        # 转换到全局坐标
                        if roi:
                            h, w = screen.shape[:2]
                            x1, y1, _, _ = roi
                            global_x = int(match_result[0] + w * x1)
                            global_y = int(match_result[1] + h * y1)
                            best_result = (name, (global_x, global_y))
                        else:
                            best_result = (
                                name, (int(match_result[0]), int(match_result[1])))
            except Exception:
                continue

        return best_result
