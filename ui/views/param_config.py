# param_config.py
from PyQt6.QtWidgets import (QWidget, QFormLayout, QLineEdit, QSpinBox, 
                             QDoubleSpinBox, QComboBox, QCheckBox, QTextEdit,
                             QPushButton, QMessageBox)
from PyQt6.QtCore import pyqtSignal, Qt
from ui.utils.widget_builder import WidgetBuilder

class ParamConfigView(QWidget):
    """任务参数配置视图，用于设置当前选中任务的运行参数"""
    params_saved = pyqtSignal(dict)  # 参数保存信号，传递参数字典
    
    def __init__(self):
        super().__init__()
        self.current_task_id = None
        self.current_task_info = None
        self.param_widgets = {}
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        main_layout = WidgetBuilder.create_vbox_layout()
        
        # 标题和说明
        main_layout.addWidget(WidgetBuilder.create_label("参数配置", bold=True))
        main_layout.addWidget(WidgetBuilder.create_label("配置当前选中任务的运行参数，不同任务可能有不同的参数项"))
        main_layout.addWidget(WidgetBuilder.create_separator())
        
        # 任务信息
        self.task_info_label = WidgetBuilder.create_label("请在任务列表中选择一个任务")
        main_layout.addWidget(self.task_info_label)
        
        # 参数表单区域
        self.scroll_area, self.form_layout = self.create_param_scroll_area()
        main_layout.addWidget(self.scroll_area, 1)
        
        # 操作按钮
        btn_layout = WidgetBuilder.create_hbox_layout()
        self.reset_btn = WidgetBuilder.create_button("重置", "恢复默认参数")
        self.save_btn = WidgetBuilder.create_button("保存参数", "保存当前配置的参数")
        
        self.reset_btn.clicked.connect(self.reset_params)
        self.save_btn.clicked.connect(self.save_params)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addWidget(self.save_btn)
        
        main_layout.addLayout(btn_layout)
        
        self.setLayout(main_layout)
        
    def create_param_scroll_area(self) -> tuple:
        """创建参数表单的滚动区域"""
        scroll_area, layout = WidgetBuilder.create_scroll_area()
        
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_layout.setSpacing(10)
        
        layout.addWidget(form_widget)
        layout.addStretch()
        
        return scroll_area, form_layout
        
    def load_task_params(self, task_id: str, task_info: dict):
        """加载指定任务的参数配置"""
        self.current_task_id = task_id
        self.current_task_info = task_info
        self.param_widgets.clear()
        
        # 清空现有表单
        while self.form_layout.rowCount() > 0:
            self.form_layout.removeRow(0)
            
        self.task_info_label.setText(f"当前配置: {task_info.get('name', task_id)}")
        
        params = task_info.get('params', {})
        if not params:
            self.form_layout.addRow(WidgetBuilder.create_label("该任务没有可配置的参数"))
            return
            
        for param_name, param_meta in params.items():
            widget = self.create_param_widget(param_meta)
            if widget:
                self.param_widgets[param_name] = widget
                label = WidgetBuilder.create_label(f"{param_name}:")
                label.setToolTip(param_meta.get('desc', ''))
                self.form_layout.addRow(label, widget)
                
    def create_param_widget(self, param_meta: dict):
        """根据参数类型创建对应的输入组件（修复：Range异常防护）"""
        param_type = param_meta.get('type', 'str')
        default_val = param_meta.get('default', None)
        options = param_meta.get('options', [])
        
        if param_type == 'int':
            widget = WidgetBuilder.create_spin_box()
            if default_val is not None:
                widget.setValue(int(default_val))
            # 修复：添加Range异常防护
            if 'range' in param_meta:
                try:
                    min_val, max_val = param_meta['range']
                    widget.setRange(int(min_val), int(max_val))
                except (ValueError, TypeError):
                    QMessageBox.warning(self, "参数错误", f"参数范围格式无效: {param_meta['range']}")
                    
        elif param_type == 'float':
            widget = WidgetBuilder.create_double_spin_box()
            if default_val is not None:
                widget.setValue(float(default_val))
            # 修复：添加Range异常防护
            if 'range' in param_meta:
                try:
                    min_val, max_val = param_meta['range']
                    widget.setRange(float(min_val), float(max_val))
                except (ValueError, TypeError):
                    QMessageBox.warning(self, "参数错误", f"参数范围格式无效: {param_meta['range']}")
            
        elif param_type == 'bool':
            widget = QCheckBox()
            if default_val is not None:
                widget.setChecked(bool(default_val))
                
        elif param_type == 'str' and options:
            widget = QComboBox()
            widget.addItems(options)
            if default_val is not None and default_val in options:
                widget.setCurrentText(default_val)
                
        elif param_type == 'text':
            widget = QTextEdit()
            if default_val is not None:
                widget.setText(str(default_val))
            widget.setMinimumHeight(60)
            
        else:  # 默认字符串类型
            widget = QLineEdit()
            if default_val is not None:
                widget.setText(str(default_val))
                
        return widget
        
    def get_current_params(self) -> dict:
        """获取当前配置的参数值"""
        params = {}
        for param_name, widget in self.param_widgets.items():
            if isinstance(widget, QSpinBox) or isinstance(widget, QDoubleSpinBox):
                params[param_name] = widget.value()
            elif isinstance(widget, QCheckBox):
                params[param_name] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                params[param_name] = widget.currentText()
            elif isinstance(widget, QTextEdit):
                params[param_name] = widget.toPlainText()
            else:  # QLineEdit
                params[param_name] = widget.text()
        return params
        
    def reset_params(self):
        """重置参数为默认值"""
        if not self.current_task_id or not self.current_task_info:
            QMessageBox.warning(self, "警告", "无当前配置的任务")
            return
        self.load_task_params(self.current_task_id, self.current_task_info)
        QMessageBox.information(self, "提示", "参数已重置为默认值")
        
    def save_params(self):
        """保存当前配置的参数"""
        if not self.current_task_id:
            QMessageBox.warning(self, "警告", "请先选择一个任务")
            return
            
        params = self.get_current_params()
        self.params_saved.emit({
            'task_id': self.current_task_id,
            'params': params
        })
        QMessageBox.information(self, "成功", "参数保存成功")