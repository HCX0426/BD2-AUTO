"""
ROI区域配置管理器
统一管理所有自动化任务中使用的ROI(Region of Interest)区域
支持全局ROI和任务特定ROI的访问
"""

import json
import os
from typing import Any, Dict, Optional, Tuple

from src.auto_control.utils.logger import Logger
from src.core.path_manager import path_manager

# 初始化日志器
logger = Logger(name="ROIConfig")


class ROIConfig:
    """
    ROI配置管理器
    用于加载和提供ROI配置
    """

    def __init__(self):
        """
        初始化ROI配置管理器
        """
        # 从配置文件加载ROI设置
        self.roi_settings = self._load_roi_config()

        # 分离全局ROI和任务特定ROI
        self.public_rois = self.roi_settings.get("public", {})
        self.task_rois = self.roi_settings.get("tasks", {})

        # 构建所有ROI的字典，供任务类直接使用
        self.all_rois = self._build_all_rois_dict()

    def _build_all_rois_dict(self) -> Dict[str, Any]:
        """
        构建所有ROI的字典，方便直接访问

        将所有任务的ROI和全局ROI整合到一个嵌套字典中
        格式：{public: {roi_name: roi_tuple}, task_name: {roi_name: roi_tuple}}

        Returns:
            所有ROI的嵌套字典
        """
        all_rois = {}

        # 添加全局ROI
        all_rois["public"] = {}
        for roi_name, roi_value in self.public_rois.items():
            all_rois["public"][roi_name] = tuple(roi_value)

        # 添加任务ROI，保持嵌套结构
        for task_name, task_rois in self.task_rois.items():
            all_rois[task_name] = {}
            for roi_name, roi_value in task_rois.items():
                all_rois[task_name][roi_name] = tuple(roi_value)

        return all_rois

    def get_rois(self) -> Dict[str, Any]:
        """
        获取所有ROI配置

        Returns:
            所有ROI配置的嵌套字典
            格式：{public: {roi_name: roi_tuple}, task_name: {roi_name: roi_tuple}}
        """
        return self.all_rois

    def _load_roi_config(self) -> Dict:
        """
        从ROI配置文件加载配置

        Returns:
            ROI配置字典
        """
        roi_config_path = path_manager.get("rois_config")

        if not os.path.exists(roi_config_path):
            logger.warning(f"ROI配置文件不存在 {roi_config_path}，使用默认配置")
            return {"public": {}, "tasks": {}}

        try:
            with open(roi_config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"ROI配置文件 {roi_config_path} 格式错误，使用默认配置")
            return {"public": {}, "tasks": {}}
        except Exception as e:
            logger.error(f"加载ROI配置文件失败 {e}，使用默认配置")
            return {"public": {}, "tasks": {}}

    def get_roi(
        self, roi_name: str, task_name: Optional[str] = None, default: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        获取ROI配置

        Args:
            roi_name: ROI名称
            task_name: 任务名称（可选），如果提供，会先查找任务特定的ROI，再查找全局ROI
            default: 默认值，如果找不到ROI配置则返回

        Returns:
            ROI坐标元组(x, y, w, h)，或None
        """
        # 先查找任务特定的ROI
        if task_name and task_name in self.task_rois:
            if roi_name in self.task_rois[task_name]:
                return tuple(self.task_rois[task_name][roi_name])

        # 再查找全局ROI
        if roi_name in self.public_rois:
            return tuple(self.public_rois[roi_name])

        # 返回默认值
        return default

    def get_task_rois(self, task_name: str) -> Dict[str, Tuple[int, int, int, int]]:
        """
        获取指定任务的所有ROI配置

        Args:
            task_name: 任务名称

        Returns:
            任务所有ROI配置的字典
        """
        if task_name in self.task_rois:
            return {name: tuple(roi) for name, roi in self.task_rois[task_name].items()}
        return {}

    def get_public_rois(self) -> Dict[str, Tuple[int, int, int, int]]:
        """
        获取所有全局ROI配置

        Returns:
            全局所有ROI配置的字典
        """
        return {name: tuple(roi) for name, roi in self.public_rois.items()}

    def get_all_task_rois(self) -> Dict[str, Dict[str, Tuple[int, int, int, int]]]:
        """
        获取所有任务的ROI配置

        Returns:
            所有任务ROI配置的字典，结构为 {task_name: {roi_name: roi_tuple}}
        """
        result = {}
        for task_name, rois in self.task_rois.items():
            result[task_name] = {name: tuple(roi) for name, roi in rois.items()}
        return result


# 创建全局ROI配置实例
roi_config = ROIConfig()
