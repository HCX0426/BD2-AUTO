# 首先初始化路径，确保所有模块可以被正确导入
import os
import sys

# 获取项目根目录
project_root = os.path.abspath(os.path.dirname(__file__))

# 添加项目根目录到sys.path
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def main():
    """
    主函数，启动整个应用程序
    """
    # 2. 初始化非阻塞组件
    from src.core.task_loader import load_task_modules
    from src.ui.core.settings import AppSettingsManager
    from src.ui.core.task_config import TaskConfigManager

    settings_manager = AppSettingsManager()  # 应用设置管理器
    config_manager = TaskConfigManager()  # 任务配置管理器
    task_mapping = load_task_modules()  # 加载任务模块映射

    # 3. 启动GUI，Auto实例将在后台线程中初始化
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication(sys.argv)
        app.setApplicationName("BD2-AUTO")

        # 初始化信号总线（必须在QApplication创建后）
        from src.ui.core.signals import init_signal_bus

        init_signal_bus()

        from src.entrypoints.main_window import MainWindow

        window = MainWindow(settings_manager=settings_manager, config_manager=config_manager, task_mapping=task_mapping)

        window.show()

        # 在QApplication完全初始化后启动自动初始化线程
        window.start_auto_init_thread()

        result = app.exec()
        sys.exit(result)
    except Exception as e:
        print(f"[ERROR] GUI启动过程中发生异常: {type(e).__name__}: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
