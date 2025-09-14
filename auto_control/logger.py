import os
import gzip
import logging
import shutil
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from .config import LOG_CONFIG, get_log_dir

class CompressedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """支持压缩旧日志 + 自动清理超期日志的 Handler"""
    def __init__(self, *args, compress=True, **kwargs):
        self.compress = compress
        super().__init__(*args, **kwargs)

    def doRollover(self):
        """重写轮转逻辑：压缩旧日志 + 清理超期日志"""
        super().doRollover()  # 先让父类处理轮转

        if self.compress:
            self.compress_old_logs()

        self.clean_expired_logs()

    def compress_old_logs(self):
        """压缩旧日志（.log -> .log.gz）"""
        log_dir = Path(self.baseFilename).parent
        for file in log_dir.glob(f"{Path(self.baseFilename).name}.*"):
            if file.suffix not in (".gz", ".lock") and "current" not in file.name:
                gz_file = file.with_suffix(file.suffix + ".gz")
                try:
                    with open(file, "rb") as f_in:
                        with gzip.open(gz_file, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.remove(file)  # 删除原文件
                except Exception as e:
                    logging.warning(f"压缩日志失败: {file} -> {gz_file}, 错误: {e}")

    def clean_expired_logs(self):
        """清理超过 BACKUP_COUNT 天的旧日志"""
        log_dir = Path(self.baseFilename).parent
        now = datetime.now()
        for file in log_dir.glob(f"{Path(self.baseFilename).name}.*.gz"):
            try:
                # 提取日志日期（假设文件名格式是 task.log.2023-01-01.gz）
                date_str = file.name.split(".")[-2]
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                if (now - file_date).days > self.backupCount:
                    os.remove(file)
            except Exception as e:
                logging.warning(f"清理旧日志失败: {file}, 错误: {e}")

class AsyncLogHandler:
    """异步日志处理器（使用线程池）"""
    def __init__(self, logger):
        self.logger = logger
        self.executor = ThreadPoolExecutor(max_workers=1)  # 单线程避免竞争

    def log(self, level, message, exc_info=False):
        """提交日志任务到线程池"""
        self.executor.submit(
            self._log_sync,
            level,
            message,
            exc_info
        )

    def _log_sync(self, level, message, exc_info):
        """同步执行日志记录"""
        if level == "DEBUG":
            self.logger.debug(message)
        elif level == "INFO":
            self.logger.info(message)
        elif level == "WARNING":
            self.logger.warning(message)
        elif level == "ERROR":
            self.logger.error(message, exc_info=exc_info)
        elif level == "CRITICAL":
            self.logger.critical(message, exc_info=exc_info)

    def shutdown(self):
        """关闭线程池"""
        self.executor.shutdown(wait=True)

class Logger:
    def __init__(
        self,
        task_name=None,
        base_log_dir=None,
        log_file_prefix=None,
        file_log_level=None,
        console_log_level=None,
        when=None,
        interval=None,
        backup_count=None,
        async_logging=None,
        compress_old_logs=None,
    ):
        """
        初始化日志记录器（参数为 None 时使用默认配置）
        :param task_name: 任务名（作为日志子目录）
        :param base_log_dir: 基础日志目录（支持相对/绝对路径）
        :param log_file_prefix: 日志文件前缀
        :param file_log_level: 文件日志级别
        :param console_log_level: 控制台日志级别
        :param when: 轮转周期（"midnight"/"D"/"H"/"M"）
        :param interval: 间隔天数
        :param backup_count: 保留的日志文件数量
        :param async_logging: 是否启用异步日志
        :param compress_old_logs: 是否压缩旧日志
        """
        # 从 log_config 加载默认配置
        config = LOG_CONFIG
        
        # 动态计算日志目录（使用 log_config 的辅助函数）
        base_log_dir = base_log_dir or config["BASE_LOG_DIR"]
        self.log_dir = get_log_dir(base_log_dir, task_name)

        # 使用配置值或参数值（优先使用参数）
        log_file_prefix = log_file_prefix or config["LOG_FILE_PREFIX"]
        file_log_level = file_log_level or config["FILE_LOG_LEVEL"]
        console_log_level = console_log_level or config["CONSOLE_LOG_LEVEL"]
        when = when or config["WHEN"]
        interval = interval or config["INTERVAL"]
        backup_count = backup_count or config["BACKUP_COUNT"]
        async_logging = async_logging if async_logging is not None else config["ASYNC_LOGGING"]
        compress_old_logs = compress_old_logs if compress_old_logs is not None else config["COMPRESS_OLD_LOGS"]
        log_format = config["LOG_FORMAT"]

        # 日志文件路径
        log_file_path = Path(self.log_dir) / f"{log_file_prefix}.log"

        # 配置日志记录器
        self.logger = logging.getLogger(f"{__name__}.{task_name}" if task_name else __name__)
        self.logger.setLevel(logging.DEBUG)

        # 防止重复添加handler
        if not self.logger.handlers:
            # 文件处理器（带压缩和清理功能）
            file_handler = CompressedTimedRotatingFileHandler(
                log_file_path,
                when=when,
                interval=interval,
                backupCount=backup_count,
                encoding="utf-8",
                compress=compress_old_logs,
            )
            file_handler.setLevel(file_log_level)

            # 控制台处理器
            console_handler = logging.StreamHandler()
            console_handler.setLevel(console_log_level)

            # 日志格式（从配置获取）
            formatter = logging.Formatter(log_format)
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

        # 异步日志
        self.async_logging = async_logging
        if async_logging:
            self.async_handler = AsyncLogHandler(self.logger)

    def create_task_logger(self, task_name: str) -> logging.Logger:
        """创建带任务名称的子日志"""
        child_logger = self.logger.getChild(task_name)
        # 确保子日志器级别设置为DEBUG
        child_logger.setLevel(logging.DEBUG)
        return child_logger

    # 以下日志方法保持不变...
    def debug(self, message):
        if self.async_logging:
            self.async_handler.log("DEBUG", message)
        else:
            self.logger.debug(message)

    def info(self, message):
        if self.async_logging:
            self.async_handler.log("INFO", message)
        else:
            self.logger.info(message)

    def warning(self, message):
        if self.async_logging:
            self.async_handler.log("WARNING", message)
        else:
            self.logger.warning(message)

    def error(self, message, exc_info=False):
        if self.async_logging:
            self.async_handler.log("ERROR", message, exc_info)
        else:
            self.logger.error(message, exc_info=exc_info)

    def critical(self, message, exc_info=False):
        if self.async_logging:
            self.async_handler.log("CRITICAL", message, exc_info)
        else:
            self.logger.critical(message, exc_info=exc_info)

    def exception(self, message):
        """自动记录异常堆栈"""
        if self.async_logging:
            self.async_handler.log("ERROR", message, exc_info=True)
        else:
            self.logger.exception(message)

    def shutdown(self):
        """关闭异步日志线程池"""
        if hasattr(self, "async_handler"):
            self.async_handler.shutdown()