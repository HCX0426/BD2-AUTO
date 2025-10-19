from PyQt6.QtWidgets import QWidget, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from ui.utils.widget_builder import WidgetBuilder

class Sidebar(QWidget):
    """侧边栏导航组件，用于切换不同功能视图"""
    item_clicked = pyqtSignal(int)  # 点击项索引信号
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        """初始化侧边栏UI"""
        layout = WidgetBuilder.create_vbox_layout(margin=0, spacing=0)
        
        # 创建导航列表
        self.nav_list = QListWidget()
        self.nav_list.setFrameShape(QListWidget.Shape.NoFrame)
        self.nav_list.setSpacing(2)
        self.nav_list.setStyleSheet("""
            QListWidget {
                background-color: #f0f0f0;
                border-right: 1px solid #e0e0e0;
            }
            QListWidget::item {
                height: 50px;
                border-radius: 4px;
                margin: 2px 5px;
                padding-left: 15px;
                text-align: left;
            }
            QListWidget::item:selected {
                background-color: #e6f7ff;
                color: #1890ff;
            }
        """)
        
        # 添加导航项
        self.add_nav_item("任务列表", 0)
        self.add_nav_item("参数配置", 1)
        self.add_nav_item("执行计划", 2)
        self.add_nav_item("资源管理", 3)
        self.add_nav_item("系统设置", 4)
        
        # 默认选中第一项
        self.nav_list.setCurrentRow(0)
        
        # 绑定点击事件
        self.nav_list.itemClicked.connect(self.on_item_clicked)
        
        layout.addWidget(self.nav_list)
        self.setLayout(layout)
        
    def add_nav_item(self, text, index):
        """添加导航项"""
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, index)  # 存储索引
        self.nav_list.addItem(item)
        
    def on_item_clicked(self, item):
        """导航项点击事件"""
        index = item.data(Qt.ItemDataRole.UserRole)
        self.item_clicked.emit(index)