import sys
import os
import traceback
from PyQt6.QtWidgets import QApplication
from ui.views.launcher import Launcher
from ui.views.main_window import MainWindow
from ui.controllers.main_controller import MainController

# 关键：定义项目根目录（需与 auto_config.py 中的 PROJECT_ROOT 一致）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# 将项目根目录添加到Python路径（避免模块导入错误）
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)
    

# 从 auto_config.py 读取根目录（如果已有该文件，优先用这个）
try:
    from auto_control.config.auto_config import PROJECT_ROOT as CONFIG_PROJECT_ROOT
    PROJECT_ROOT = CONFIG_PROJECT_ROOT
except ImportError:
    pass

print(f"当前PROJECT_ROOT: {PROJECT_ROOT}")
print(f"路径是否存在: {os.path.exists(PROJECT_ROOT)}")
class App:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.launcher = None
        self.main_window = None
        self.main_controller = None

    def start(self):
        print("开始启动程序")
        try:
            self.launcher = Launcher(PROJECT_ROOT)
            print("Launcher实例创建成功")
            self.launcher.center()
            self.launcher.launch_finished.connect(self.launch_main_window)
            self.launcher.show()
            print("Launcher窗口显示成功")
        except Exception as e:
            print(f"启动Launcher失败: {str(e)}")
            traceback.print_exc()
        sys.exit(self.app.exec())

    def launch_main_window(self, managers):
        """启动界面完成后，初始化主窗口和控制器"""
        try:
            print("开始执行 launch_main_window")
            
            # 提取管理器
            resource_manager = managers["resource_manager"]
            settings_manager = managers["settings_manager"]
            print("成功提取 resource_manager 和 settings_manager")

            # 创建主窗口
            self.main_window = MainWindow(resource_manager)
            print("MainWindow 实例创建成功")
            self.main_window.resource_manager = resource_manager
            print("主窗口资源管理器设置完成")

            # 收集视图引用（关键：检查 main_window 的子组件是否存在）
            print("开始收集视图引用...")
            
            # 修复：添加存在性检查，避免访问不存在的组件
            views = {
                "main_window": self.main_window,
            }
            
            # 仅添加存在的组件
            if hasattr(self.main_window, 'sidebar') and self.main_window.sidebar:
                views["sidebar"] = self.main_window.sidebar
            
            if hasattr(self.main_window, 'task_list_view') and self.main_window.task_list_view:
                views["task_list_view"] = self.main_window.task_list_view
            
            if hasattr(self.main_window, 'param_config_view') and self.main_window.param_config_view:
                views["param_config_view"] = self.main_window.param_config_view
            
            if hasattr(self.main_window, 'execution_plan_view') and self.main_window.execution_plan_view:
                views["execution_plan_view"] = self.main_window.execution_plan_view
            
            if hasattr(self.main_window, 'resource_manager_view') and self.main_window.resource_manager_view:
                views["resource_manager_view"] = self.main_window.resource_manager_view
            
            if hasattr(self.main_window, 'settings_panel') and self.main_window.settings_panel:
                views["settings_panel"] = self.main_window.settings_panel
                
            print(f"视图引用收集完成: {list(views.keys())}")

            # 创建主控制器
            self.main_controller = MainController(views)
            print("MainController 实例创建成功")
            self.main_controller.resource_manager = resource_manager
            self.main_controller.settings_manager = settings_manager
            print("控制器管理器设置完成")

            # 显示主窗口
            self.main_window.center()
            self.main_window.show()
            print("主窗口显示成功")

        except Exception as e:
            print(f"\nlaunch_main_window 执行失败: {str(e)}")
            import traceback
            traceback.print_exc()  # 打印详细错误堆栈

if __name__ == "__main__":
    app = App()
    app.start()