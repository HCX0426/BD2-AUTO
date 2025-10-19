from PyQt6.QtWidgets import (QWidget, QListWidgetItem, QFileDialog, 
                             QMessageBox, QInputDialog, QListWidget)
from PyQt6.QtCore import Qt, pyqtSignal
from ui.utils.widget_builder import WidgetBuilder  # 假设该工具类已实现基础控件创建
from ui.controllers.resource_manager import ResourceManager  # 导入上面的资源管理器

class ResourceManagerView(QWidget):
    """资源管理视图，用于管理多任务资源路径"""
    resource_changed = pyqtSignal(str)  # 资源变更信号，发射资源路径

    def __init__(self, resource_manager: ResourceManager):
        super().__init__()
        self.resource_manager = resource_manager  # 注入资源管理器实例
        self.init_ui()
        self.refresh_resource_list()  # 初始化时刷新列表

    def init_ui(self):
        """初始化UI布局和控件"""
        main_layout = WidgetBuilder.create_vbox_layout()  # 垂直布局

        # 标题和说明
        main_layout.addWidget(WidgetBuilder.create_label("资源管理", bold=True))
        main_layout.addWidget(WidgetBuilder.create_label("管理游戏任务资源路径，支持多资源切换和顺序执行"))
        main_layout.addWidget(WidgetBuilder.create_separator())  # 分隔线

        # 资源列表（核心控件）
        self.resource_list = WidgetBuilder.create_list_widget()  # 创建QListWidget
        self.resource_list.itemClicked.connect(self.on_resource_clicked)  # 绑定点击事件
        main_layout.addWidget(self.resource_list)

        # 操作按钮区
        btn_layout = WidgetBuilder.create_hbox_layout()  # 水平布局

        self.add_btn = WidgetBuilder.create_button("添加资源", "添加新的任务资源路径")
        self.remove_btn = WidgetBuilder.create_button("删除资源", "删除选中的资源路径")
        self.enable_btn = WidgetBuilder.create_button("启用/禁用", "切换资源的启用状态")
        self.up_btn = WidgetBuilder.create_button("上移", "调整资源顺序（影响执行顺序）")
        self.down_btn = WidgetBuilder.create_button("下移", "调整资源顺序（影响执行顺序）")

        # 绑定按钮事件
        self.add_btn.clicked.connect(self.add_resource)
        self.remove_btn.clicked.connect(self.remove_resource)
        self.enable_btn.clicked.connect(self.toggle_resource_status)
        self.up_btn.clicked.connect(self.move_resource_up)
        self.down_btn.clicked.connect(self.move_resource_down)

        # 添加按钮到布局
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addWidget(self.enable_btn)
        btn_layout.addWidget(self.up_btn)
        btn_layout.addWidget(self.down_btn)

        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)
        self.setWindowTitle("资源管理")  # 可选：设置窗口标题

    def refresh_resource_list(self):
        """刷新资源列表显示（同步资源管理器数据）"""
        self.resource_list.clear()  # 清空列表
        for res in self.resource_manager.resources:
            # 显示格式：[状态] 名称 (路径)
            status = "✓" if res["enabled"] else "✗"
            item_text = f"[{status}] {res['name']} ({res['path']})"
            item = QListWidgetItem(item_text)
            # 存储原始资源数据（供后续使用，可选）
            item.setData(Qt.ItemDataRole.UserRole, res)
            self.resource_list.addItem(item)

        # 选中当前资源（保持视觉同步）
        current_index = self.resource_manager.current_index
        if 0 <= current_index < self.resource_list.count():
            self.resource_list.setCurrentRow(current_index)

    def add_resource(self):
        """添加新资源（选择路径+输入名称）"""
        # 选择资源目录
        path = QFileDialog.getExistingDirectory(self, "选择任务资源目录")
        if not path:  # 用户取消选择
            return

        # 输入资源名称（默认自动生成）
        default_name = f"资源_{len(self.resource_manager.resources) + 1}"
        name, ok = QInputDialog.getText(self, "输入名称", "请输入资源名称:", text=default_name)
        if not ok:  # 用户取消输入
            return
        name = name.strip() or default_name  # 处理空名称

        # 调用资源管理器添加并刷新列表
        if self.resource_manager.add_resource(name, path):
            self.refresh_resource_list()
            QMessageBox.information(self, "成功", f"资源 '{name}' 添加成功")
        else:
            QMessageBox.warning(self, "失败", f"资源 '{name}' 添加失败（路径可能不存在或重复）")

    def remove_resource(self):
        """删除选中的资源"""
        current_row = self.resource_list.currentRow()
        if current_row < 0:  # 未选中任何资源
            QMessageBox.warning(self, "警告", "请先选择一个资源")
            return

        # 确认删除
        res = self.resource_manager.resources[current_row]
        confirm = QMessageBox.question(
            self, "确认删除", 
            f"是否删除资源 '{res['name']}'？\n路径: {res['path']}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # 调用资源管理器删除并刷新列表
        if self.resource_manager.remove_resource(current_row):
            self.refresh_resource_list()
            QMessageBox.information(self, "成功", "资源已删除")

    def toggle_resource_status(self):
        """切换资源启用/禁用状态"""
        current_row = self.resource_list.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请先选择一个资源")
            return

        # 切换状态并保存
        self.resource_manager.resources[current_row]["enabled"] = not self.resource_manager.resources[current_row]["enabled"]
        self.resource_manager.save_resources()
        self.refresh_resource_list()  # 刷新显示

    def move_resource_up(self):
        """上移资源（调整执行顺序）"""
        current_row = self.resource_list.currentRow()
        if current_row <= 0:  # 已在顶部
            return

        # 交换位置
        resources = self.resource_manager.resources
        resources[current_row], resources[current_row - 1] = resources[current_row - 1], resources[current_row]
        self.resource_manager.save_resources()
        self.refresh_resource_list()
        self.resource_list.setCurrentRow(current_row - 1)  # 保持选中状态

    def move_resource_down(self):
        """下移资源（调整执行顺序）"""
        current_row = self.resource_list.currentRow()
        max_row = len(self.resource_manager.resources) - 1
        if current_row < 0 or current_row >= max_row:  # 已在底部
            return

        # 交换位置
        resources = self.resource_manager.resources
        resources[current_row], resources[current_row + 1] = resources[current_row + 1], resources[current_row]
        self.resource_manager.save_resources()
        self.refresh_resource_list()
        self.resource_list.setCurrentRow(current_row + 1)  # 保持选中状态

    def on_resource_clicked(self, item: QListWidgetItem):
        """处理资源点击事件（核心修复）"""
        try:
            # 1. 获取点击项的行索引（与资源管理器列表索引一致）
            current_row = self.resource_list.row(item)
            if current_row < 0:
                raise ValueError("无效的资源行索引")

            # 2. 通知资源管理器切换当前资源
            if not self.resource_manager.set_current_resource(current_row):
                raise IndexError(f"资源索引 {current_row} 超出范围（总资源数：{len(self.resource_manager.resources)}）")

            # 3. 获取当前资源路径并发射变更信号（供任务列表加载）
            current_path = self.resource_manager.get_current_resource_path()
            if not current_path:
                raise FileNotFoundError("当前资源路径为空或无效")

            self.resource_changed.emit(current_path)  # 发射路径信号
            print(f"资源切换成功，当前路径：{current_path}")

        except Exception as e:
            # 捕获所有异常，避免界面崩溃
            print(f"\n===== 资源点击错误 =====")
            print(f"错误：{str(e)}")
            import traceback
            traceback.print_exc()
            print("=======================\n")
            QMessageBox.critical(self, "操作失败", f"切换资源时出错：{str(e)}")