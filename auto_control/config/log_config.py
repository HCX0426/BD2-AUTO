import os
from pathlib import Path

from auto_control.config.auto_config import PROJECT_ROOT



TASK_LOG_DIR = os.path.join(PROJECT_ROOT, 'auto_tasks', 'pc', 'log', 'task_log')
os.makedirs(TASK_LOG_DIR, exist_ok=True)

# 默认日志配置（集中管理所有配置）
LOG_CONFIG = {
    "BASE_LOG_DIR": TASK_LOG_DIR,  # 基础日志目录（支持相对/绝对路径）
    "LOG_FILE_PREFIX": "task",  # 日志文件前缀
    "FILE_LOG_LEVEL": "DEBUG",  # 文件日志级别
    "CONSOLE_LOG_LEVEL": "INFO",  # 控制台日志级别
    "WHEN": "midnight",  # 按天轮转
    "INTERVAL": 1,  # 每天轮转一次
    "BACKUP_COUNT": 30,  # 保留30天的日志（压缩后）
    "LOG_FORMAT": "%(asctime)s - %(name)s - %(levelname)s - %(threadName)s - %(message)s",
    "ASYNC_LOGGING": True,  # 是否启用异步日志
    "COMPRESS_OLD_LOGS": True,  # 是否压缩旧日志
}

def get_log_dir(base_dir, task_name=None):
    """获取日志目录（支持动态任务名子目录）"""
    log_dir = Path(base_dir)
    if task_name:
        log_dir = log_dir / str(task_name)
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_dir.absolute())