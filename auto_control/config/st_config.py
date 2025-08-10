import os
from airtest.core.settings import Settings as ST
from airtest.core.helper import set_logdir
from airtest.report.report import simple_report
from auto_control.config.auto_config import PROJECT_ROOT

# 统一日志路径常量
ST_LOG_DIR = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc', 'log', 'st_log')
ST_REPORT_DIR = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc', 'log', 'st_report')

# 初始化目录结构
os.makedirs(ST_LOG_DIR, exist_ok=True)
os.makedirs(ST_REPORT_DIR, exist_ok=True)

# 配置Airtest日志系统
set_logdir(ST_LOG_DIR)
ST.LOG_FILE = "log.txt"

__author__ = "Airtest"

import logging
logger = logging.getLogger("airtest")
logger.setLevel(logging.ERROR)

DEFAULT_REPORT_PATH = os.path.join(ST_REPORT_DIR, 'log.html')

def generate_report(script_path: str,report_path: str = DEFAULT_REPORT_PATH) -> str:
    """生成Airtest测试报告
    Args:
        script_path: 测试脚本路径（通常传__file__）
    Returns:
        生成的报告绝对路径
    """
    simple_report(
        filepath=script_path,
        logpath=ST_LOG_DIR,
        output=report_path
    )
    return os.path.abspath(report_path)