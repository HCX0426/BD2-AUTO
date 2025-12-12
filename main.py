# BD2-AUTO/main.py
import sys
from src.core.path_manager import path_manager  # 路径管理优先初始化
from PyQt6.QtWidgets import QApplication
from src.auto_control.core.auto import Auto  # 核心控制类
from src.core.task_manager import (  # 任务管理相关类
    AppSettingsManager,
    TaskConfigManager,
    load_task_modules
)
from src.entrypoints.main_window import MainWindow  # GUI窗口

def main():
    # 1. 路径初始化（确保所有模块可导入）
    project_root = path_manager.static_base
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        print(f"项目根目录已添加到sys.path: {project_root}")

    # 2. 初始化核心实例（这些实例将传递给GUI）
    auto_instance = Auto()  # 自动化控制核心
    settings_manager = AppSettingsManager()  # 应用设置管理器
    config_manager = TaskConfigManager()  # 任务配置管理器
    task_mapping = load_task_modules()  # 加载任务模块映射

    # 3. 启动GUI，传递核心实例
    app = QApplication(sys.argv)
    # 将核心实例通过构造函数传递给主窗口
    window = MainWindow(
        auto_instance=auto_instance,
        settings_manager=settings_manager,
        config_manager=config_manager,
        task_mapping=task_mapping
    )
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()