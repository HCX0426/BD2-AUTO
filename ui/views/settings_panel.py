# settings_panel.py
from PyQt6.QtWidgets import (QWidget, QGroupBox, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QComboBox, QCheckBox, QLineEdit,
                             QFileDialog, QMessageBox, QLabel)
from PyQt6.QtCore import pyqtSignal, Qt
from ui.utils.widget_builder import WidgetBuilder
from ui.utils.style_loader import StyleLoader

class SettingsPanel(QWidget):
    """系统设置面板，用于配置应用程序的全局设置"""
    settings_saved = pyqtSignal(dict)
    theme_changed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_current_settings()
        
    def init_ui(self):
        """初始化UI"""
        main_layout = WidgetBuilder.create_vbox_layout()
        
        # 标题
        main_layout.addWidget(WidgetBuilder.create_label("系统设置", bold=True))
        main_layout.addWidget(WidgetBuilder.create_separator())
        
        # 创建设置分组
        self.create_appearance_group()
        self.create_path_group()
        self.create_logging_group()
        
        # 添加所有分组到主布局
        main_layout.addWidget(self.appearance_group)
        main_layout.addWidget(self.path_group)
        main_layout.addWidget(self.logging_group)
        main_layout.addStretch()
        
        # 操作按钮
        btn_layout = WidgetBuilder.create_hbox_layout()
        self.reset_btn = WidgetBuilder.create_button("恢复默认", "恢复所有设置为默认值")
        self.save_btn = WidgetBuilder.create_button("保存设置", "保存当前配置的设置")
        
        self.reset_btn.clicked.connect(self.reset_settings)
        self.save_btn.clicked.connect(self.save_settings)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addWidget(self.save_btn)
        
        main_layout.addLayout(btn_layout)
        
        self.setLayout(main_layout)
        
    def create_appearance_group(self):
        """创建外观设置分组"""
        self.appearance_group = QGroupBox("外观设置")
        layout = WidgetBuilder.create_vbox_layout()
        
        # 主题选择
        theme_layout = WidgetBuilder.create_form_row("主题:", 
            WidgetBuilder.create_combo_box(["light", "dark"], 0))
        self.theme_combo = theme_layout.itemAt(1).widget()
        layout.addLayout(theme_layout)
        
        # 字体大小（修复：使用正确的SpinBox创建方法）
        font_layout = WidgetBuilder.create_form_row("字体大小:", 
            WidgetBuilder.create_spin_box(value=12, min_val=10, max_val=16))
        self.font_size_spin = font_layout.itemAt(1).widget()
        layout.addLayout(font_layout)
        
        # 紧凑模式
        compact_layout = WidgetBuilder.create_form_row("", 
            WidgetBuilder.create_checkbox("启用紧凑模式"))
        self.compact_checkbox = compact_layout.itemAt(1).widget()
        layout.addLayout(compact_layout)
        
        self.appearance_group.setLayout(layout)
        
    def create_path_group(self):
        """创建路径设置分组"""
        self.path_group = QGroupBox("路径设置")
        layout = WidgetBuilder.create_vbox_layout()
        
        # 日志文件路径
        log_path_layout = QHBoxLayout()
        self.log_path_edit = WidgetBuilder.create_line_edit()
        self.log_path_btn = WidgetBuilder.create_button("浏览...")
        self.log_path_btn.clicked.connect(lambda: self.choose_path(self.log_path_edit))
        
        log_path_layout.addWidget(WidgetBuilder.create_label("日志文件路径:", 
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        log_path_layout.addWidget(self.log_path_edit)
        log_path_layout.addWidget(self.log_path_btn)
        layout.addLayout(log_path_layout)
        
        # 缓存路径
        cache_path_layout = QHBoxLayout()
        self.cache_path_edit = WidgetBuilder.create_line_edit()
        self.cache_path_btn = WidgetBuilder.create_button("浏览...")
        self.cache_path_btn.clicked.connect(lambda: self.choose_path(self.cache_path_edit))
        
        cache_path_layout.addWidget(WidgetBuilder.create_label("缓存文件路径:", 
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        cache_path_layout.addWidget(self.cache_path_edit)
        cache_path_layout.addWidget(self.cache_path_btn)
        layout.addLayout(cache_path_layout)
        
        self.path_group.setLayout(layout)
        
    def create_logging_group(self):
        """创建日志设置分组"""
        self.logging_group = QGroupBox("日志设置")
        layout = WidgetBuilder.create_vbox_layout()
        
        # 日志级别
        log_level_layout = WidgetBuilder.create_form_row("日志级别:", 
            WidgetBuilder.create_combo_box(["DEBUG", "INFO", "WARNING", "ERROR"], 1))
        self.log_level_combo = log_level_layout.itemAt(1).widget()
        layout.addLayout(log_level_layout)
        
        # 日志保存天数
        log_days_layout = WidgetBuilder.create_form_row("日志保存天数:", 
            WidgetBuilder.create_spin_box(value=7, min_val=1, max_val=30))
        self.log_days_spin = log_days_layout.itemAt(1).widget()
        layout.addLayout(log_days_layout)
        
        # 启用日志文件
        log_file_layout = WidgetBuilder.create_form_row("", 
            WidgetBuilder.create_checkbox("同时保存日志到文件", checked=True))
        self.log_file_checkbox = log_file_layout.itemAt(1).widget()
        layout.addLayout(log_file_layout)
        
        self.logging_group.setLayout(layout)
        
    def choose_path(self, line_edit: QLineEdit):
        """选择文件路径"""
        path = QFileDialog.getExistingDirectory(self, "选择目录")
        if path:
            line_edit.setText(path)
            
    def load_current_settings(self):
        """加载当前设置"""
        # 使用默认值
        self.theme_combo.setCurrentText("light")
        self.font_size_spin.setValue(12)
        self.compact_checkbox.setChecked(False)
        
        # 路径设置
        from auto_control.config.auto_config import PROJECT_ROOT
        import os
        self.log_path_edit.setText(os.path.join(PROJECT_ROOT, "logs"))
        self.cache_path_edit.setText(os.path.join(PROJECT_ROOT, "cache"))
        
        # 日志设置
        self.log_level_combo.setCurrentText("INFO")
        self.log_days_spin.setValue(7)
        self.log_file_checkbox.setChecked(True)
        
    def get_current_settings(self) -> dict:
        """获取当前设置"""
        return {
            "appearance": {
                "theme": self.theme_combo.currentText(),
                "font_size": self.font_size_spin.value(),
                "compact_mode": self.compact_checkbox.isChecked()
            },
            "paths": {
                "log": self.log_path_edit.text(),
                "cache": self.cache_path_edit.text()
            },
            "logging": {
                "level": self.log_level_combo.currentText(),
                "save_days": self.log_days_spin.value(),
                "save_to_file": self.log_file_checkbox.isChecked()
            }
        }
        
    def reset_settings(self):
        """恢复默认设置"""
        if QMessageBox.question(self, "确认", "确定要恢复默认设置吗？",
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.load_current_settings()
            QMessageBox.information(self, "提示", "已恢复默认设置")
            
    def save_settings(self):
        """保存设置"""
        settings = self.get_current_settings()
        self.settings_saved.emit(settings)
        
        # 如果主题变更，发送主题变更信号
        self.theme_changed.emit(settings["appearance"]["theme"])
        
        QMessageBox.information(self, "成功", "设置已保存，部分设置需要重启应用生效")