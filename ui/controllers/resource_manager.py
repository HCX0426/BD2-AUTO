# resource_manager.py
import json
import os
from typing import List, Dict, Optional
from PyQt6.QtCore import QObject, pyqtSignal

class ResourceManager(QObject):
    """资源管理器，负责资源的增删改查和持久化存储"""
    resources_updated = pyqtSignal()

    def __init__(self, config_path: str = "resources_config.json"):
        super().__init__()
        self.config_path = config_path
        self.resources: List[Dict] = []
        self.current_index: int = -1
        self.load_resources()

    def load_resources(self) -> None:
        """从配置文件加载资源"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.resources = data.get("resources", [])
                    self.current_index = data.get("current_index", -1)
                    if self.current_index < 0 or self.current_index >= len(self.resources):
                        self.current_index = -1
            except Exception as e:
                print(f"加载资源配置失败: {e}")
                self.resources = []
                self.current_index = -1
        self.resources_updated.emit()

    def save_resources(self) -> None:
        """保存资源配置到文件"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "resources": self.resources,
                    "current_index": self.current_index
                }, f, ensure_ascii=False, indent=2)
            self.resources_updated.emit()
        except Exception as e:
            print(f"保存资源配置失败: {e}")

    def add_resource(self, name: str, path: str) -> bool:
        """添加新资源"""
        if not os.path.exists(path):
            print(f"资源路径不存在: {path}")
            return False
        for res in self.resources:
            if res["path"] == path:
                print(f"资源路径已存在: {path}")
                return False
        self.resources.append({
            "name": name,
            "path": path,
            "enabled": True
        })
        self.save_resources()
        return True

    def remove_resource(self, index: int) -> bool:
        """删除指定索引的资源"""
        if 0 <= index < len(self.resources):
            self.resources.pop(index)
            if self.current_index == index:
                self.current_index = -1
            elif self.current_index > index:
                self.current_index -= 1
            self.save_resources()
            return True
        return False

    def set_current_resource(self, index: int) -> bool:
        """设置当前选中的资源（通过索引）"""
        if 0 <= index < len(self.resources):
            self.current_index = index
            self.save_resources()
            return True
        return False

    def get_current_resource_path(self) -> Optional[str]:
        """获取当前选中资源的路径"""
        if 0 <= self.current_index < len(self.resources):
            return self.resources[self.current_index]["path"]
        return None

    def get_current_resource(self) -> Optional[Dict]:
        """获取当前选中的资源完整信息"""
        if 0 <= self.current_index < len(self.resources):
            return self.resources[self.current_index]
        return None

    # 新增方法
    def get_enabled_resources(self) -> List[Dict]:
        """获取所有启用的资源"""
        return [res for res in self.resources if res.get('enabled', True)]

    def get_resource_by_path(self, path: str) -> Optional[Dict]:
        """根据路径获取资源"""
        for res in self.resources:
            if res["path"] == path:
                return res
        return None