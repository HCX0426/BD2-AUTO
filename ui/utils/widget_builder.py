# widget_builder.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QGroupBox, QFrame,
                             QListWidget, QTableWidget, QTableWidgetItem,
                             QScrollArea, QComboBox, QSpinBox, QDoubleSpinBox,
                             QCheckBox, QRadioButton)
from PyQt6.QtCore import Qt
from typing import Optional, List, Tuple, Dict

class WidgetBuilder:
    """通用组件构建工具类，用于快速创建标准化的UI组件"""
    
    @staticmethod
    def create_vbox_layout(margin: int = 5, spacing: int = 5) -> QVBoxLayout:
        """创建垂直布局"""
        layout = QVBoxLayout()
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(spacing)
        return layout
    
    @staticmethod
    def create_hbox_layout(margin: int = 5, spacing: int = 5) -> QHBoxLayout:
        """创建水平布局"""
        layout = QHBoxLayout()
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(spacing)
        return layout
    
    @staticmethod
    def create_label(text: str, 
                    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
                    bold: bool = False) -> QLabel:
        """创建标签"""
        label = QLabel(text)
        label.setAlignment(alignment)
        if bold:
            font = label.font()
            font.setBold(True)
            label.setFont(font)
        return label
    
    @staticmethod
    def create_button(text: str, 
                     tooltip: str = "",
                     icon: Optional[str] = None) -> QPushButton:
        """创建按钮"""
        button = QPushButton(text)
        if tooltip:
            button.setToolTip(tooltip)
        return button
    
    @staticmethod
    def create_line_edit(placeholder: str = "",
                        text: str = "",
                        read_only: bool = False) -> QLineEdit:
        """创建单行输入框"""
        line_edit = QLineEdit(text)
        if placeholder:
            line_edit.setPlaceholderText(placeholder)
        line_edit.setReadOnly(read_only)
        return line_edit
    
    @staticmethod
    def create_group_box(title: str, 
                        layout: Optional[QVBoxLayout] = None) -> Tuple[QGroupBox, QVBoxLayout]:
        """创建分组框"""
        group_box = QGroupBox(title)
        if not layout:
            layout = WidgetBuilder.create_vbox_layout()
        group_box.setLayout(layout)
        return group_box, layout
    
    @staticmethod
    def create_separator(horizontal: bool = True) -> QFrame:
        """创建分隔线"""
        separator = QFrame()
        if horizontal:
            separator.setFrameShape(QFrame.Shape.HLine)
        else:
            separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        return separator
    
    @staticmethod
    def create_list_widget(items: Optional[List[str]] = None) -> QListWidget:
        """创建列表组件"""
        list_widget = QListWidget()
        if items:
            list_widget.addItems(items)
        return list_widget
    
    @staticmethod
    def create_table_widget(rows: int, 
                           cols: int,
                           headers: Optional[List[str]] = None) -> QTableWidget:
        """创建表格组件"""
        table = QTableWidget(rows, cols)
        if headers:
            table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        return table
    
    @staticmethod
    def create_scroll_area(widget: Optional[QWidget] = None) -> Tuple[QScrollArea, QVBoxLayout]:
        """创建滚动区域"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        
        content_widget = QWidget()
        layout = WidgetBuilder.create_vbox_layout()
        content_widget.setLayout(layout)
        
        if widget:
            layout.addWidget(widget)
            
        scroll_area.setWidget(content_widget)
        return scroll_area, layout
    
    @staticmethod
    def create_combo_box(items: Optional[List[str]] = None,
                        current_index: int = 0) -> QComboBox:
        """创建下拉选择框"""
        combo = QComboBox()
        if items:
            combo.addItems(items)
            if 0 <= current_index < len(items):
                combo.setCurrentIndex(current_index)
        return combo
    
    @staticmethod
    def create_form_row(label_text: str, 
                       widget: QWidget,
                       label_width: int = 100) -> QHBoxLayout:
        """创建表单行（标签+组件）"""
        layout = WidgetBuilder.create_hbox_layout()
        label = WidgetBuilder.create_label(label_text)
        label.setFixedWidth(label_width)
        layout.addWidget(label)
        layout.addWidget(widget)
        layout.addStretch()
        return layout
    
    @staticmethod
    def create_checkbox(text: str, checked: bool = False) -> QCheckBox:
        """创建复选框"""
        checkbox = QCheckBox(text)
        checkbox.setChecked(checked)
        return checkbox
    
    @staticmethod
    def create_radiobutton(text: str, checked: bool = False) -> QRadioButton:
        """创建单选按钮"""
        radiobutton = QRadioButton(text)
        radiobutton.setChecked(checked)
        return radiobutton

    @staticmethod
    def create_spin_box(value: int = 0, min_val: int = 0, max_val: int = 9999) -> QSpinBox:
        """创建整型数值输入框"""
        spin_box = QSpinBox()
        spin_box.setValue(value)
        spin_box.setRange(min_val, max_val)
        return spin_box

    @staticmethod
    def create_double_spin_box(value: float = 0.0, min_val: float = 0.0, max_val: float = 9999.99) -> QDoubleSpinBox:
        """创建双精度数值输入框"""
        double_spin = QDoubleSpinBox()
        double_spin.setValue(value)
        double_spin.setRange(min_val, max_val)
        double_spin.setDecimals(2)
        return double_spin