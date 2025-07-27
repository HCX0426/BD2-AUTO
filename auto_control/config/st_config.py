import os
from airtest.core.settings import Settings as ST
from airtest.core.helper import set_logdir
from .image_config import PROJECT_ROOT  # 使用工程统一配置

# 统一日志路径常量
ST_LOG_DIR = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc', 'log', 'st_log')
ST_REPORT_DIR = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc', 'log', 'st_report')

# 初始化目录结构
os.makedirs(ST_LOG_DIR, exist_ok=True)
os.makedirs(ST_REPORT_DIR, exist_ok=True)

# 配置Airtest日志系统
set_logdir(ST_LOG_DIR)
ST.LOG_FILE = "log.txt"

def generate_report(script_path: str) -> str:
    """生成Airtest测试报告
    Args:
        script_path: 测试脚本路径（通常传__file__）
    Returns:
        生成的报告绝对路径
    """
    from airtest.report.report import simple_report
    
    report_path = os.path.join(ST_REPORT_DIR, 'log.html')
    
    simple_report(
        filepath=script_path,
        logpath=ST_LOG_DIR,
        output=report_path
    )
    return os.path.abspath(report_path)