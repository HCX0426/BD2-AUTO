# style_loader.py
from PyQt6.QtWidgets import QWidget, QMessageBox  # 修复：导入QMessageBox
import os
from typing import List

class StyleLoader:
    """样式加载工具类，负责加载和管理QSS样式文件"""
    
    @staticmethod
    def load_styles(widget: QWidget, style_files: List[str]) -> None:
        """加载多个样式文件并应用到指定组件（修复：添加用户反馈）"""
        style_sheet = ""
        failed_files = []  # 记录加载失败的文件
        
        for file_path in style_files:
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        style_sheet += f.read() + "\n"
                except Exception as e:
                    failed_files.append(f"{file_path}（错误：{str(e)}）")
            else:
                failed_files.append(f"{file_path}（错误：文件不存在）")
        
        # 修复：加载失败时提示用户
        if failed_files:
            QMessageBox.warning(
                widget,
                "样式加载失败",
                f"以下样式文件加载失败，界面可能异常：\n{chr(10).join(failed_files)}"
            )
        
        if style_sheet:
            widget.setStyleSheet(style_sheet)
    
    @staticmethod
    def get_common_style_path() -> str:
        """获取公用样式文件路径"""
        from auto_control.config.auto_config import PROJECT_ROOT
        return os.path.join(PROJECT_ROOT, 'ui', 'styles', 'common.qss')
    
    @staticmethod
    def get_theme_style_path(theme: str = "light") -> str:
        """获取主题样式文件路径"""
        from auto_control.config.auto_config import PROJECT_ROOT
        return os.path.join(PROJECT_ROOT, 'ui', 'styles', f'{theme}.qss')
    
    @staticmethod
    def load_common_styles(widget: QWidget, theme: str = "light") -> None:
        """加载公用样式+主题样式"""
        style_files = [
            StyleLoader.get_common_style_path(),
            StyleLoader.get_theme_style_path(theme)
        ]
        StyleLoader.load_styles(widget, style_files)