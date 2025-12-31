# 首先初始化路径，确保所有模块可以被正确导入
import os
import sys

# 获取项目根目录
project_root = os.path.abspath(os.path.dirname(__file__))

# 添加项目根目录到sys.path
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    print(f"项目根目录已添加到sys.path: {project_root}")


def main():
    """
    主函数，启动整个应用程序
    """
    # 2. 初始化非阻塞组件
    from src.core.task_manager import AppSettingsManager, TaskConfigManager, load_task_modules
    settings_manager = AppSettingsManager()  # 应用设置管理器
    config_manager = TaskConfigManager()  # 任务配置管理器
    task_mapping = load_task_modules()  # 加载任务模块映射

    # 3. 启动GUI，Auto实例将在后台线程中初始化
    try:
        print("[DEBUG] 创建QApplication实例...")
        from PyQt6.QtWidgets import QApplication
        app = QApplication(sys.argv)
        app.setApplicationName("BD2-AUTO")
        print("[DEBUG] QApplication实例创建成功")

        # 初始化信号总线（必须在QApplication创建后）
        print("[DEBUG] 初始化信号总线...")
        from src.ui.core.signals import get_signal_bus_instance, init_signal_bus

        bus_instance = init_signal_bus()

        # 确保全局signal_bus变量已经初始化
        global_signal_bus = get_signal_bus_instance()
        print(f"[DEBUG] 信号总线初始化结果: {bus_instance}")
        print(f"[DEBUG] 全局signal_bus变量: {global_signal_bus}")
        print("[DEBUG] 信号总线初始化完成")

        print("[DEBUG] 创建MainWindow实例...")
        from src.entrypoints.main_window import MainWindow
        window = MainWindow(settings_manager=settings_manager, config_manager=config_manager, task_mapping=task_mapping)
        print("[DEBUG] MainWindow实例创建成功")

        print("[DEBUG] 调用window.show()...")
        window.show()
        print("[DEBUG] window.show()调用成功")

        # 在QApplication完全初始化后启动自动初始化线程
        print("[DEBUG] 启动自动初始化线程...")
        window.start_auto_init_thread()
        print("[DEBUG] 自动初始化线程启动成功")

        print("[DEBUG] 启动事件循环...")
        result = app.exec()
        print(f"[DEBUG] 事件循环退出，退出码: {result}")
        sys.exit(result)
    except Exception as e:
        print(f"[ERROR] GUI启动过程中发生异常: {type(e).__name__}: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
