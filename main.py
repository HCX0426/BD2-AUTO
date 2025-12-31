# BD2-AUTO/main.py
import sys

from PyQt6.QtWidgets import QApplication

from src.auto_control.core.auto import Auto  # 核心控制类
from src.core.path_manager import path_manager  # 路径管理优先初始化
from src.core.task_manager import AppSettingsManager, TaskConfigManager, load_task_modules  # 任务管理相关类
from src.entrypoints.main_window import MainWindow  # GUI窗口


def main():
    # 全局异常捕获设置
    def handle_exception(exc_type, exc_value, exc_traceback):
        """全局异常处理器"""
        if issubclass(exc_type, KeyboardInterrupt):
            # 处理键盘中断
            print("[INFO] 程序被用户中断")
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        # 记录异常信息
        error_msg = f"[CRITICAL] 未捕获的全局异常: {type(exc_value).__name__}: {str(exc_value)}"
        print(error_msg)
        import traceback

        traceback.print_exc()

    # 设置全局异常钩子
    sys.excepthook = handle_exception

    # 1. 路径初始化（确保所有模块可导入）
    project_root = path_manager.static_base
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        print(f"项目根目录已添加到sys.path: {project_root}")

    # 2. 初始化非阻塞组件
    try:
        settings_manager = AppSettingsManager()  # 应用设置管理器
        config_manager = TaskConfigManager()  # 任务配置管理器
        task_mapping = load_task_modules()  # 加载任务模块映射
    except Exception as e:
        print(f"[ERROR] 初始化组件失败: {type(e).__name__}: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # 3. 启动GUI，Auto实例将在后台线程中初始化
    try:
        print("[DEBUG] 创建QApplication实例...")
        app = QApplication(sys.argv)
        print("[DEBUG] QApplication实例创建成功")

        print("[DEBUG] 创建MainWindow实例...")
        window = MainWindow(
            auto_instance=None,  # Auto实例将在后台初始化
            settings_manager=settings_manager,
            config_manager=config_manager,
            task_mapping=task_mapping,
        )
        print("[DEBUG] MainWindow实例创建成功")

        print("[DEBUG] 调用window.show()...")
        window.show()
        print("[DEBUG] window.show()调用成功")

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
