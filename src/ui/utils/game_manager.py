import os
import subprocess
from PyQt6.QtWidgets import QMessageBox


class GameManager:
    """游戏管理类，负责游戏启动等功能"""
    
    def __init__(self, settings_manager):
        """初始化游戏管理器
        
        Args:
            settings_manager: 应用设置管理器
        """
        self.settings_manager = settings_manager
    
    def launch_game(self):
        """启动游戏
        
        从设置中获取游戏路径，检查路径是否存在，然后启动游戏
        """
        from src.ui.core.signals import get_signal_bus
        signal_bus = get_signal_bus()
        
        pc_game_path = self.settings_manager.get_setting("pc_game_path", "")
        if not pc_game_path:
            QMessageBox.warning(None, "警告", "请先在设置中配置PC游戏路径")
            signal_bus.emit_log("警告：未配置PC游戏路径")
            return
        
        try:
            # 检查路径是否存在
            if not os.path.exists(pc_game_path):
                QMessageBox.critical(None, "错误", f"游戏路径不存在: {pc_game_path}")
                signal_bus.emit_log(f"错误：游戏路径不存在: {pc_game_path}")
                return
            
            # 启动游戏
            subprocess.Popen(pc_game_path)
            signal_bus.emit_log(f"已启动游戏: {pc_game_path}")
            
        except Exception as e:
            signal_bus.emit_log(f"启动游戏失败: {str(e)}")
            QMessageBox.critical(None, "错误", f"启动游戏失败: {str(e)}")
