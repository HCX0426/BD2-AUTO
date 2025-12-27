import gzip
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional, Union

# 导入 path_manager（保持原有依赖）
from src.core.path_manager import path_manager

# 全局共享：系统统一日志的文件处理器（供所有日志器同步日志到 system.log）
_global_system_file_handler: Optional[TimedRotatingFileHandler] = None


class CompressedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """支持日志轮转、旧日志压缩、超期日志清理的文件处理器"""

    def __init__(self, *args, compress: bool = True, **kwargs):
        """
        初始化处理器
        :param args: 继承父类的位置参数
        :param compress: 是否压缩旧日志（.log -> .log.gz）
        :param kwargs: 继承父类的关键字参数
        """
        self.compress = compress
        super().__init__(*args, **kwargs)

    def doRollover(self) -> None:
        """日志轮转触发：先执行父类轮转逻辑，再压缩旧日志、清理超期日志"""
        super().doRollover()
        if self.compress:
            self._compress_old_logs()
        self._clean_expired_logs()

    def _compress_old_logs(self) -> None:
        """压缩轮转后的旧日志文件"""
        log_dir = Path(self.baseFilename).parent
        # 匹配所有轮转日志（排除.gz压缩文件和.lock文件）
        for log_file in log_dir.glob(f"{Path(self.baseFilename).name}.*"):
            if log_file.suffix not in (".gz", ".lock") and "current" not in log_file.name:
                gz_file = log_file.with_suffix(f"{log_file.suffix}.gz")
                try:
                    with open(log_file, "rb") as f_in, gzip.open(gz_file, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                    os.remove(log_file)  # 压缩后删除原文件
                except Exception as e:
                    logging.warning(f"[日志工具] 压缩日志失败: {log_file} -> {gz_file}, 错误: {str(e)}")

    def _clean_expired_logs(self) -> None:
        """清理超过备份天数的压缩日志"""
        log_dir = Path(self.baseFilename).parent
        now = datetime.now()
        # 匹配所有压缩日志
        for gz_file in log_dir.glob(f"{Path(self.baseFilename).name}.*.gz"):
            try:
                # 从文件名提取日期（格式：prefix.log.2025-01-01.gz）
                date_str = gz_file.name.split(".")[-2]
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                # 超过备份天数则删除
                if (now - file_date).days > self.backupCount:
                    os.remove(gz_file)
            except Exception as e:
                logging.warning(f"[日志工具] 清理旧日志失败: {gz_file}, 错误: {str(e)}")


class AsyncLogHandler:
    """异步日志处理器，使用单线程池避免日志写入竞争"""

    def __init__(self, logger: logging.Logger):
        """
        初始化异步处理器
        :param logger: 要包装的日志器实例
        """
        self.logger = logger
        self.executor = ThreadPoolExecutor(max_workers=1)  # 单线程确保日志顺序

    def log(self, level: str, message: str, exc_info: bool = False) -> None:
        """
        提交日志任务到线程池
        :param level: 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
        :param message: 日志内容
        :param exc_info: 是否记录异常堆栈
        """
        self.executor.submit(self._log_sync, level, message, exc_info)

    def _log_sync(self, level: str, message: str, exc_info: bool) -> None:
        """
        同步执行日志记录（线程池内部调用）
        :param level: 日志级别
        :param message: 日志内容
        :param exc_info: 是否记录异常堆栈
        """
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

    def shutdown(self) -> None:
        """关闭线程池，等待所有日志任务完成"""
        self.executor.shutdown(wait=True)


class Logger:
    """
    支持日志多播的日志管理器：
    - 系统日志器：创建全局统一日志文件（system.log），接收所有组件/任务的日志
    - 组件日志器：日志同时写入组件专属文件和全局统一文件
    - 任务日志器：日志同时写入任务专属文件、全局统一文件和控制台
    """

    # 整合默认日志配置（添加BASE_LOG_DIR默认值，从path_manager获取）
    DEFAULT_LOG_CONFIG: Dict[str, Any] = {
        "BASE_LOG_DIR": path_manager.get("log"),  # 日志根目录
        "LOG_FILE_PREFIX": "task",  # 日志文件前缀
        "FILE_LOG_LEVEL": "DEBUG",  # 文件日志级别
        "CONSOLE_LOG_LEVEL": "INFO",  # 控制台日志级别
        "WHEN": "midnight",  # 按天轮转
        "INTERVAL": 1,  # 每天轮转一次
        "BACKUP_COUNT": 1,  # 保留固定天数的日志（压缩后）
        "ASYNC_LOGGING": True,  # 是否启用异步日志
        "COMPRESS_OLD_LOGS": True,  # 是否压缩旧日志
    }

    def __init__(
        self,
        name: str,
        base_log_dir: Optional[str] = None,
        log_file_prefix: Optional[str] = None,
        file_log_level: Optional[Union[str, int]] = None,
        console_log_level: Optional[Union[str, int]] = None,
        when: Optional[str] = None,
        interval: Optional[int] = None,
        backup_count: Optional[int] = None,
        async_logging: Optional[bool] = None,
        compress_old_logs: Optional[bool] = None,
        is_task_logger: bool = False,
        is_system_logger: bool = False,
        test_mode: bool = False,  # 测试模式开关（默认关闭）
    ):
        """
        初始化日志器
        :param name: 日志器名称（组件名/任务名/System），将显示在日志中
        :param base_log_dir: 基础日志目录（默认使用 DEFAULT_LOG_CONFIG 配置）
        :param log_file_prefix: 日志文件前缀（默认使用 DEFAULT_LOG_CONFIG 配置）
        :param file_log_level: 文件日志级别（字符串/整数，默认使用 DEFAULT_LOG_CONFIG 配置）
        :param console_log_level: 控制台日志级别（字符串/整数，默认使用 DEFAULT_LOG_CONFIG 配置）
        :param when: 日志轮转周期（默认使用 DEFAULT_LOG_CONFIG 配置）
        :param interval: 轮转间隔（默认使用 DEFAULT_LOG_CONFIG 配置）
        :param backup_count: 日志保留天数（默认使用 DEFAULT_LOG_CONFIG 配置）
        :param async_logging: 是否启用异步日志（默认使用 DEFAULT_LOG_CONFIG 配置）
        :param compress_old_logs: 是否压缩旧日志（默认使用 DEFAULT_LOG_CONFIG 配置）
        :param is_task_logger: 是否为任务日志器（独立目录+控制台输出）
        :param is_system_logger: 是否为系统日志器（创建全局统一日志文件）
        :param test_mode: 是否启用测试模式（测试模式下初始化时清空当前日志文件，默认False）
        """
        # 加载配置（参数优先，默认配置兜底）
        self.name = name
        self.is_task_logger = is_task_logger
        self.is_system_logger = is_system_logger
        self.test_mode = test_mode

        # 基础配置参数（关键修复：base_log_dir 用默认配置兜底）
        self.base_log_dir = base_log_dir or self.DEFAULT_LOG_CONFIG["BASE_LOG_DIR"]
        self.log_file_prefix = log_file_prefix or self.DEFAULT_LOG_CONFIG["LOG_FILE_PREFIX"]
        # 修正：传入默认配置的字符串级别，确保 _get_log_level 接收正确类型
        self.file_log_level = self._get_log_level(
            file_log_level if file_log_level is not None else self.DEFAULT_LOG_CONFIG["FILE_LOG_LEVEL"]
        )
        self.console_log_level = self._get_log_level(
            console_log_level if console_log_level is not None else self.DEFAULT_LOG_CONFIG["CONSOLE_LOG_LEVEL"]
        )
        self.when = when or self.DEFAULT_LOG_CONFIG["WHEN"]
        self.interval = interval or self.DEFAULT_LOG_CONFIG["INTERVAL"]
        self.backup_count = backup_count or self.DEFAULT_LOG_CONFIG["BACKUP_COUNT"]
        self.async_logging = async_logging if async_logging is not None else self.DEFAULT_LOG_CONFIG["ASYNC_LOGGING"]
        self.compress_old_logs = (
            compress_old_logs if compress_old_logs is not None else self.DEFAULT_LOG_CONFIG["COMPRESS_OLD_LOGS"]
        )

        # 日志格式（包含时间、日志器名称、级别、内容）
        self.formatter = logging.Formatter(
            "%(asctime)s - [%(name)s] - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        # 日志目录和文件路径规划
        self.log_dir, self.log_file_path = self._get_log_path()
        self.log_dir.mkdir(parents=True, exist_ok=True)  # 确保目录存在

        # 测试模式下清空当前日志文件
        if self.test_mode:
            self._clear_current_log_file()

        # 初始化日志器核心（禁止向上传播，避免重复输出）
        self.logger = self._init_logger_core()

        # 添加日志处理器（独立文件+统一文件+控制台）
        self._add_handlers()

        # 异步日志初始化
        self.async_handler: Optional[AsyncLogHandler] = None
        if self.async_logging:
            self.async_handler = AsyncLogHandler(self.logger)

    @staticmethod
    def _get_log_level(level: Union[str, int]) -> int:
        """
        将日志级别转换为 logging 模块对应的整数常量
        :param level: 日志级别（字符串如 "DEBUG" 或整数如 logging.DEBUG）
        :return: 对应的整数日志级别
        """
        # 若已是整数（如 logging.DEBUG），直接返回
        if isinstance(level, int):
            return level
        # 字符串级别转换为大写后映射
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        return level_map.get(level.upper(), logging.INFO)  # 默认 INFO 级别

    @staticmethod
    def _get_log_dir(base_dir: str, task_name: Optional[str] = None) -> str:
        """
        整合原 get_log_dir 函数：获取日志目录（支持动态任务名子目录）
        :param base_dir: 基础日志目录
        :param task_name: 任务名称（可选，为空则返回基础目录）
        :return: 日志目录的绝对路径字符串
        """
        log_dir = Path(base_dir)
        if task_name:
            log_dir = log_dir / str(task_name)
        log_dir.mkdir(parents=True, exist_ok=True)
        return str(log_dir.absolute())

    def _get_log_path(self) -> tuple[Path, Path]:
        """
        计算日志目录和文件路径
        :return: (日志目录Path, 日志文件Path)
        """
        if self.is_task_logger:
            # 任务日志：base_dir/tasks/任务名/task.log
            log_dir = Path(self.base_log_dir) / "tasks" / self.name
            log_file = log_dir / "task.log"
        elif self.is_system_logger:
            # 系统日志：使用 _get_log_dir 生成目录
            log_dir_str = self._get_log_dir(self.base_log_dir, task_name=self.name)
            log_dir = Path(log_dir_str)
            log_file = log_dir / f"{self.log_file_prefix}.log"
        else:
            # 组件日志：base_dir/组件名小写/system.log
            log_dir = Path(self.base_log_dir) / self.name.lower()
            log_file = log_dir / f"{self.log_file_prefix}.log"
        return log_dir, log_file

    def _clear_current_log_file(self) -> None:
        """
        测试模式专用：清空当前日志文件（仅主.log文件）
        仅清空文件内容，不删除文件本身，不影响轮转后的压缩日志
        """
        try:
            if self.log_file_path.exists():
                # 以写模式打开文件并立即关闭，快速清空内容
                with open(self.log_file_path, "w", encoding="utf-8") as f:
                    f.write("")
                logging.warning(f"[测试模式] 已清空日志文件: {self.log_file_path}")
        except Exception as e:
            logging.warning(f"[测试模式] 清空日志文件失败: {self.log_file_path}, 错误: {str(e)}")

    def _init_logger_core(self) -> logging.Logger:
        """
        初始化日志器核心实例
        :return: 配置后的logging.Logger实例
        """
        logger = logging.getLogger(self.name)
        logger.setLevel(logging.DEBUG)  # 日志器本身设为DEBUG，由处理器控制级别
        logger.propagate = False  # 禁止传播到root logger，避免重复输出
        return logger

    def _add_handlers(self) -> None:
        """添加日志处理器（独立文件+统一文件+控制台）"""
        if not self.logger.handlers:  # 避免重复添加处理器
            # 1. 添加独立文件处理器（组件/任务专属日志）
            self._add_independent_file_handler()

            # 2. 添加全局统一文件处理器（同步到system.log，系统日志器跳过）
            if not self.is_system_logger:
                self._add_system_unified_handler()

            # 3. 添加控制台处理器（仅系统日志和任务日志需要）
            if self.is_system_logger or self.is_task_logger:
                self._add_console_handler()

    def _add_independent_file_handler(self) -> None:
        """添加组件/任务专属的独立文件处理器"""
        handler = CompressedTimedRotatingFileHandler(
            str(self.log_file_path),
            when=self.when,
            interval=self.interval,
            backupCount=self.backup_count,
            encoding="utf-8",
            compress=self.compress_old_logs,
        )
        handler.setLevel(self.file_log_level)
        handler.setFormatter(self.formatter)
        self.logger.addHandler(handler)

        # 系统日志器的处理器需要全局共享，供其他日志器同步
        if self.is_system_logger:
            global _global_system_file_handler
            _global_system_file_handler = handler

    def _add_system_unified_handler(self) -> None:
        """添加全局统一文件处理器（同步日志到system.log）"""
        global _global_system_file_handler
        if _global_system_file_handler:
            # 复用系统日志器的处理器，实现日志多播
            self.logger.addHandler(_global_system_file_handler)
        else:
            logging.warning(f"[{self.name}] 系统统一日志处理器未初始化，无法同步到system.log")

    def _add_console_handler(self) -> None:
        """添加控制台处理器（输出到终端）"""
        handler = logging.StreamHandler()
        handler.setLevel(self.console_log_level)
        handler.setFormatter(self.formatter)
        self.logger.addHandler(handler)

    def create_component_logger(self, component_name: str) -> "Logger":
        """
        创建组件日志器（自动多播到组件专属文件和system.log）
        :param component_name: 组件名称（如"ImageProcessor"）
        :return: 配置好的组件Logger实例
        """
        return Logger(
            name=component_name,
            base_log_dir=self.base_log_dir,
            file_log_level=logging.DEBUG,
            console_log_level=logging.WARNING,
            async_logging=self.async_logging,
            is_task_logger=False,
            test_mode=self.test_mode,
        )

    def create_task_logger(self, task_name: str) -> "Logger":
        """
        创建任务日志器（自动多播到任务专属文件、system.log和控制台）
        :param task_name: 任务名称（如"LoginTask"）
        :return: 配置好的任务Logger实例
        """
        return Logger(
            name=task_name,
            base_log_dir=self.base_log_dir,  # 关键修复：继承父日志器的基础日志目录
            console_log_level=logging.INFO,
            async_logging=self.async_logging,
            is_task_logger=True,
            test_mode=self.test_mode,  # 继承测试模式
        )

    def debug(self, message: str) -> None:
        """
        记录DEBUG级别日志
        :param message: 日志内容
        """
        if self.async_logging and self.async_handler:
            self.async_handler.log("DEBUG", message)
        else:
            self.logger.debug(message)

    def info(self, message: str) -> None:
        """
        记录INFO级别日志
        :param message: 日志内容
        """
        if self.async_logging and self.async_handler:
            self.async_handler.log("INFO", message)
        else:
            self.logger.info(message)

    def warning(self, message: str) -> None:
        """
        记录WARNING级别日志
        :param message: 日志内容
        """
        if self.async_logging and self.async_handler:
            self.async_handler.log("WARNING", message)
        else:
            self.logger.warning(message)

    def error(self, message: str, exc_info: bool = False) -> None:
        """
        记录ERROR级别日志
        :param message: 日志内容
        :param exc_info: 是否记录异常堆栈（默认不记录）
        """
        if self.async_logging and self.async_handler:
            self.async_handler.log("ERROR", message, exc_info)
        else:
            self.logger.error(message, exc_info=exc_info)

    def critical(self, message: str, exc_info: bool = False) -> None:
        """
        记录CRITICAL级别日志
        :param message: 日志内容
        :param exc_info: 是否记录异常堆栈（默认不记录）
        """
        if self.async_logging and self.async_handler:
            self.async_handler.log("CRITICAL", message, exc_info)
        else:
            self.logger.critical(message, exc_info=exc_info)

    def exception(self, message: str) -> None:
        """
        记录异常日志（自动包含堆栈信息，级别为ERROR）
        :param message: 异常描述信息
        """
        if self.async_logging and self.async_handler:
            self.async_handler.log("ERROR", message, exc_info=True)
        else:
            self.logger.exception(message)

    def shutdown(self) -> None:
        """关闭异步日志处理器（等待所有日志任务完成）"""
        if self.async_handler:
            self.async_handler.shutdown()
