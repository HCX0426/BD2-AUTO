"""
自动化系统核心模块
对外暴露核心类，保持原有导入路径兼容
"""
# 关键修改：从 .auto_core 改为 .auto
from .auto import Auto
from .auto_base import AutoResult, AutoConfig, AutoBaseError, DeviceError, VerifyError

# 导出常用类型，方便业务层使用
__all__ = [
    "Auto",          # 核心自动化类
    "AutoResult",    # 统一返回值类
    "AutoConfig",    # 配置类
    "AutoBaseError", # 基础异常类
    "DeviceError",   # 设备异常类
    "VerifyError"    # 验证异常类
]