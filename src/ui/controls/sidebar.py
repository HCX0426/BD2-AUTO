from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QButtonGroup, QFrame, QPushButton, QToolTip, QVBoxLayout, QWidget


class Sidebar(QFrame):
    """侧边栏组件，实现可折叠和拖动调整宽度功能"""

    def __init__(self, settings_manager, stacked_widget, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.stacked_widget = stacked_widget  # 关联的堆叠窗口
        self.sidebar_hidden = False
        self.sidebar_dragging = False
        self.sidebar_hovered = False

        self.init_ui()
        self.load_settings()
        self.connect_signals()

    def init_ui(self):
        """初始化侧边栏UI"""
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(50)
        self.setMaximumWidth(300)

        # 启用鼠标跟踪
        self.setMouseTracking(True)
        self.installEventFilter(self)

        # 侧边栏布局
        sidebar_layout = QVBoxLayout(self)
        sidebar_layout.setContentsMargins(5, 5, 5, 5)
        sidebar_layout.setSpacing(5)

        # 1. 主界面按钮 (放在顶部)
        self.main_btn = QPushButton()
        self.main_btn.setCheckable(True)
        self.main_btn.setChecked(True)
        self.main_btn.setIcon(QIcon.fromTheme("go-home"))
        self.main_btn.setToolTip("主界面")
        self.main_btn.setStyleSheet("padding: 5px; min-width: 30px; min-height: 30px;")

        # 2. 添加弹性空间 (将设置按钮推到最下面)
        sidebar_layout.addWidget(self.main_btn)
        sidebar_layout.addStretch(1)

        # 3. 设置按钮 (放在最底部)
        self.settings_btn = QPushButton()
        self.settings_btn.setCheckable(True)

        # 使用齿轮符号作为备选
        if QIcon.hasThemeIcon("preferences-system"):
            self.settings_btn.setIcon(QIcon.fromTheme("preferences-system"))
        else:
            # 使用QPixmap创建齿轮图标，避免被setText("")清除
            from PyQt6.QtCore import Qt
            from PyQt6.QtGui import QFont, QPainter, QPixmap

            # 创建一个简单的QPixmap，绘制齿轮符号
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setFont(QFont("Segoe UI Symbol", 24))
            painter.drawText(0, 0, 32, 32, Qt.AlignmentFlag.AlignCenter, "⚙")
            painter.end()

            # 设置为图标
            self.settings_btn.setIcon(QIcon(pixmap))

        self.settings_btn.setToolTip("设置")
        self.settings_btn.setStyleSheet("padding: 5px; min-width: 30px; min-height: 30px;")

        # 按钮组
        self.button_group = QButtonGroup()
        self.button_group.addButton(self.main_btn, 0)
        self.button_group.addButton(self.settings_btn, 1)

        sidebar_layout.addWidget(self.settings_btn)

    def connect_signals(self):
        """连接信号槽"""
        self.button_group.buttonClicked.connect(self.on_sidebar_button_clicked)

        # 获取信号总线实例
        from src.ui.core.signals import get_signal_bus
        signal_bus = get_signal_bus()

        # 连接侧边栏宽度变更信号
        signal_bus.sidebar_width_changed.connect(self.update_sidebar_width)

    def load_settings(self):
        """加载侧边栏设置"""
        sidebar_visible = self.settings_manager.get_setting("sidebar_visible", True)
        if not sidebar_visible:
            self.collapse_sidebar()
        else:
            self.expand_sidebar()

    def eventFilter(self, obj, event):
        """处理侧边栏的事件"""
        if obj == self:
            # 移除鼠标悬停展开/收缩逻辑，保持固定宽度
            if event.type() == QEvent.Type.Enter:
                self.sidebar_hovered = True
                return True
            elif event.type() == QEvent.Type.Leave:
                self.sidebar_hovered = False
                return True
        return super().eventFilter(obj, event)

    def expand_sidebar(self):
        """展开侧边栏 - 保持固定宽度"""
        # 保持固定宽度，不再展开
        width = self.settings_manager.get_setting("sidebar_width", 60)
        self.setFixedWidth(width)
        # 始终只显示图标，不显示文字
        self.main_btn.setText("")
        self.settings_btn.setText("")
        self.sidebar_hidden = False

    def collapse_sidebar(self):
        """收缩侧边栏 - 保持固定宽度"""
        # 不再收缩，保持固定宽度
        width = self.settings_manager.get_setting("sidebar_width", 60)
        self.setFixedWidth(width)
        # 始终只显示图标，不显示文字
        self.main_btn.setText("")
        self.settings_btn.setText("")
        self.sidebar_hidden = False

    def on_sidebar_button_clicked(self, button):
        """侧边栏按钮点击事件"""
        if button == self.main_btn:
            self.stacked_widget.setCurrentIndex(0)
            # 不再收缩，保持固定宽度
        elif button == self.settings_btn:
            self.stacked_widget.setCurrentIndex(1)
            # 不再展开，保持固定宽度

    def update_sidebar_width(self, width):
        """更新侧边栏宽度"""
        # 接受外部宽度更新，应用到侧边栏
        if width >= 50 and width <= 300:
            self.setFixedWidth(width)
            self.settings_manager.set_setting("sidebar_width", width)
