# main_window.py
import traceback
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QApplication
from PyQt6.QtCore import Qt
from ui.views.sidebar import Sidebar
from ui.views.task_list import TaskListView
from ui.views.param_config import ParamConfigView
from ui.views.execution_plan import ExecutionPlanView
from ui.views.resource_manager_view import ResourceManagerView
from ui.views.settings_panel import SettingsPanel
from ui.utils.style_loader import StyleLoader
from ui.controllers.resource_manager import ResourceManager
from ui.controllers.settings_manager import SettingsManager

class MainWindow(QMainWindow):
    """主窗口容器，仅负责UI组件的创建和组装"""
    def __init__(self, resource_manager, settings_manager=None):  # 新增settings_manager参数
        super().__init__()
        self.resource_manager = resource_manager
        self.settings_manager = settings_manager or SettingsManager()  # 确保有设置管理器
        try:
            self.init_ui()
            # 验证关键子组件是否存在
            assert hasattr(self, 'sidebar'), "MainWindow 未创建 sidebar"
            assert hasattr(self, 'task_list_view'), "MainWindow 未创建 task_list_view"
            assert hasattr(self, 'param_config_view'), "MainWindow 未创建 param_config_view"
            assert hasattr(self, 'execution_plan_view'), "MainWindow 未创建 execution_plan_view"
            assert hasattr(self, 'resource_manager_view'), "MainWindow 未创建 resource_manager_view"
            assert hasattr(self, 'settings_panel'), "MainWindow 未创建 settings_panel"
            
            print("MainWindow 子组件初始化验证通过")
        except Exception as e:
            print(f"MainWindow 初始化失败: {str(e)}")
            traceback.print_exc()
            # 确保即使出错也有默认的空组件
            self.sidebar = None
            self.task_list_view = None
            self.param_config_view = None
            self.execution_plan_view = None
            self.resource_manager_view = None
            self.settings_panel = None
        
    def init_ui(self):
        """初始化窗口布局和组件"""
        self.setWindowTitle("游戏任务自动化工具")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建主容器
        main_container = QWidget()
        self.setCentralWidget(main_container)
        main_layout = QHBoxLayout(main_container)
        
        # 创建侧边栏
        self.sidebar = Sidebar()
        main_layout.addWidget(self.sidebar, 1)
        
        # 创建视图容器
        self.view_stack = QStackedWidget()
        main_layout.addWidget(self.view_stack, 5)
        
        # 初始化各视图
        self.init_views()
        
    def init_views(self):
        """初始化所有子视图"""
        self.task_list_view = TaskListView(self.resource_manager)
        self.param_config_view = ParamConfigView()
        self.execution_plan_view = ExecutionPlanView(self.resource_manager)
        self.resource_manager_view = ResourceManagerView(self.resource_manager)
        self.settings_panel = SettingsPanel()
        
        # 添加到堆叠窗口
        self.view_stack.addWidget(self.task_list_view)
        self.view_stack.addWidget(self.param_config_view)
        self.view_stack.addWidget(self.execution_plan_view)
        self.view_stack.addWidget(self.resource_manager_view)
        self.view_stack.addWidget(self.settings_panel)
        
    def switch_view(self, index):
        """切换视图"""
        if 0 <= index < self.view_stack.count():
            self.view_stack.setCurrentIndex(index)
            
    def load_styles(self):
        """加载窗口样式（修复：从设置管理器获取主题）"""
        theme = self.settings_manager.get_setting("appearance.theme", "light")
        StyleLoader.load_common_styles(self, theme)
        
    def closeEvent(self, event):
        """窗口关闭时保存资源配置"""
        self.resource_manager.save_resources()
        event.accept()
        
    def center(self):
        """主窗口居中显示"""
        qr = self.frameGeometry()
        cp = QApplication.primaryScreen().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())