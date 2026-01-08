"""Auto核心类：整合所有模块，对外提供统一接口"""

import logging
import threading
import time
from typing import Any, Dict, Tuple

from src.auto_control.devices.device_manager import DeviceManager
from src.auto_control.image.image_processor import ImageProcessor
from src.auto_control.ocr.ocr_processor import OCRProcessor
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.display_context import RuntimeDisplayContext
from src.auto_control.utils.logger import Logger

# 外部依赖导入
from src.core import config_manager
from src.core.path_manager import PathManager
from src.core.path_manager import path_manager as global_path_manager

from ..utils.resource_manager import ResourceManager

# 内部模块导入
from .auto_base import AutoBaseError, AutoConfig, AutoResult
from .auto_chain import ChainManager
from .auto_devices import DeviceHandler
from .auto_operations import OperationHandler
from .auto_utils import DelayManager, LockManager
from .auto_verify import VerifyHandler


class Auto:
    """
    自动化系统调用层：对外提供统一操作接口，衔接业务逻辑与底层工具（设备/图像/OCR）

    坐标体系说明：
    - 客户区逻辑坐标（默认）：当前窗口客户区的相对坐标（与窗口实际分辨率无关）
    - 客户区物理坐标：当前窗口客户区的物理像素坐标（考虑DPI缩放）
    - 基准坐标：全屏场景下采集的原始坐标（基于默认基准分辨率1920x1080）
    - ROI格式：(x, y, width, height)，默认传递基准ROI，自动转换为客户区逻辑坐标
    """

    def __init__(
        self,
        ocr_engine: str = None,
        device_type: str = "windows",
        device_uri: str = None,
        original_base_res: Tuple[int, int] = None,
        path_manager: PathManager = None,
        config: AutoConfig = None,
        settings_manager=None,
    ):
        """
        初始化自动化系统核心实例

        :param ocr_engine: OCR引擎类型，默认使用配置中的DEFAULT_OCR_ENGINE
        :param device_type: 设备类型，支持"windows"和"adb"，默认"windows"
        :param device_uri: 设备URI，默认根据设备类型自动生成
        :param original_base_res: 原始基准分辨率，默认使用配置中的BASE_RESOLUTION
        :param path_manager: 路径管理器实例，默认使用全局单例
        :param config: 自动化配置实例，默认创建新实例
        :param settings_manager: 设置管理器实例，用于获取永久置顶等设置
        """
        # 记录总初始化开始时间
        total_init_start = time.time()

        # 配置初始化
        self.config = config or AutoConfig()

        # 保存settings_manager引用，用于装饰器中获取重试次数
        self.settings_manager = settings_manager

        original_base_res = original_base_res or self.config.BASE_RESOLUTION
        ocr_engine = ocr_engine or self.config.DEFAULT_OCR_ENGINE
        self.test_mode: bool = config_manager.config.get("debug", False)

        # 状态变量初始化
        self.lock_manager = LockManager()
        self.stop_event = threading.Event()
        self.running = False
        self.start_time = None

        # 初始化Logger模块
        logger_start = time.time()

        # 使用全局单例path_manager获取正确的日志路径
        log_path = path_manager.get("log") if path_manager else global_path_manager.get("log")
        self.logger = Logger(
            name="System",
            base_log_dir=log_path,
            log_file_prefix="system",
            file_log_level=getattr(logging, self.config.LOG_LEVEL),
            console_log_level=getattr(logging, self.config.LOG_LEVEL),
            is_system_logger=True,
            test_mode=self.test_mode,
        )
        logger_time = round(time.time() - logger_start, 3)

        # 初始化DisplayContext模块
        display_start = time.time()
        self.display_context: RuntimeDisplayContext = RuntimeDisplayContext(
            original_base_width=original_base_res[0], original_base_height=original_base_res[1]
        )
        display_time = round(time.time() - display_start, 3)

        # 创建各组件日志器
        self.coord_transformer_logger = self.logger.create_component_logger("CoordinateTransformer")
        self.image_processor_logger = self.logger.create_component_logger("ImageProcessor")
        self.device_manager_logger = self.logger.create_component_logger("DeviceManager")
        self.ocr_processor_logger = self.logger.create_component_logger("OCRProcessor")

        # 初始化CoordinateTransformer模块
        coord_start = time.time()
        self.coord_transformer: CoordinateTransformer = CoordinateTransformer(
            logger=self.coord_transformer_logger, display_context=self.display_context
        )
        coord_time = round(time.time() - coord_start, 3)

        # 初始化ImageProcessor模块
        image_start = time.time()
        self.image_processor: ImageProcessor = ImageProcessor(
            original_base_res=original_base_res,
            logger=self.image_processor_logger,
            coord_transformer=self.coord_transformer,
            display_context=self.display_context,
            test_mode=self.test_mode,
            config=self.config,
        )
        image_time = round(time.time() - image_start, 3)

        # 初始化DeviceManager模块
        device_start = time.time()
        self.device_manager: DeviceManager = DeviceManager(
            logger=self.device_manager_logger,
            image_processor=self.image_processor,
            coord_transformer=self.coord_transformer,
            display_context=self.display_context,
            stop_event=self.stop_event,
            config=self.config,
            settings_manager=settings_manager,
        )
        device_time = round(time.time() - device_start, 3)

        # 初始化OCRProcessor模块
        ocr_start = time.time()
        self.ocr_processor: OCRProcessor = OCRProcessor(
            engine=ocr_engine,
            logger=self.ocr_processor_logger,
            coord_transformer=self.coord_transformer,
            display_context=self.display_context,
            test_mode=self.test_mode,
            stop_event=self.stop_event,
            fuzzy_match=self.config.DEFAULT_TEXT_FUZZY_MATCH,
        )
        ocr_time = round(time.time() - ocr_start, 3)

        # 根据设备类型设置默认device_uri
        if device_uri is None:
            if device_type == "adb":
                self.default_device_uri = "adb://default"
            else:  # windows
                self.default_device_uri = self.config.DEFAULT_DEVICE_URI
        else:
            self.default_device_uri = device_uri

        # 初始化子模块处理器
        self.delay_manager = DelayManager()
        self.device_handler = DeviceHandler(self, self.config)
        self.operation_handler = OperationHandler(self, self.config)
        self.verify_handler = VerifyHandler(self, self.config)

        # 初始化资源管理器
        self.resource_manager = ResourceManager(
            logger=self.logger, test_mode=self.test_mode, path_manager=global_path_manager
        )

        # 系统启动时的资源清理
        self.resource_manager.cleanup_on_start()

        # 计算总初始化时间
        total_init_time = round(time.time() - total_init_start, 3)
        total_minutes = int(total_init_time // 60)
        total_seconds = round(total_init_time % 60, 3)

        # 记录各模块初始化用时和总用时
        self.logger.debug(f"=== Auto初始化时间统计 ===")
        self.logger.debug(f"Logger模块初始化用时: {logger_time}秒")
        self.logger.debug(f"DisplayContext模块初始化用时: {display_time}秒")
        self.logger.debug(f"CoordinateTransformer模块初始化用时: {coord_time}秒")
        self.logger.debug(f"ImageProcessor模块初始化用时: {image_time}秒")
        self.logger.debug(f"DeviceManager模块初始化用时: {device_time}秒")
        self.logger.debug(f"OCRProcessor模块初始化用时: {ocr_time}秒")
        self.logger.debug(f"Auto总初始化用时: {total_minutes}分{total_seconds}秒")
        self.logger.debug("========================")
        self.logger.info("自动化系统初始化完成")

    # ======================== 上下文管理器（自动启停） ========================
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        if exc_val:
            self.logger.error(f"Auto上下文异常: {exc_val}", exc_info=True)

    # ======================== 链式调用入口 ========================
    def chain(self) -> ChainManager:
        """创建链式调用管理器"""
        return ChainManager(self)

    # ======================== 系统控制方法 ========================
    def check_should_stop(self) -> bool:
        """线程安全检查任务中断标志"""
        return self.stop_event.is_set()

    def set_should_stop(self, value: bool) -> None:
        """线程安全设置任务中断标志"""
        with self.lock_manager:
            current_state = self.stop_event.is_set()
            if value and not current_state:
                self.stop_event.set()
                self.logger.info("任务停止完成")
            elif not value and current_state:
                self.stop_event.clear()
                self.logger.info("任务已恢复运行")

    def start(self) -> AutoResult:
        """
        启动自动化系统（初始化设备+标记运行状态）

        :return: AutoResult对象，包含启动结果
        - success: 布尔值，表示启动是否成功
        - data: 布尔值，始终为True
        - error_msg: 错误信息，仅在失败时提供
        - elapsed_time: 启动耗时（秒）
        """
        start_time = time.time()
        with self.lock_manager:
            if self.running:
                self.logger.warning("自动化系统已处于运行状态，无需重复启动")
                return AutoResult.success_result(data=True, elapsed_time=0.0)

            # 初始化设备
            try:
                self.logger.info(f"启动自动化系统，默认设备URI: {self.default_device_uri}")
                device_result = self.device_handler.add_device(self.default_device_uri)
                if not device_result.success:
                    raise AutoBaseError(f"默认设备初始化失败: {device_result.error_msg}")

                self.running = True
                self.start_time = time.time()
                elapsed = time.time() - start_time
                self.logger.info(f"自动化系统启动成功，耗时: {elapsed:.2f}秒")
                return AutoResult.success_result(data=True, elapsed_time=elapsed)
            except AutoBaseError as e:
                elapsed = time.time() - start_time
                self.logger.error(f"自动化系统启动失败: {str(e)}", exc_info=True)
                return AutoResult.fail_result(error_msg=str(e), elapsed_time=elapsed)

    def stop(self) -> AutoResult:
        """
        停止自动化系统（释放设备+清理资源）

        :return: AutoResult对象，包含停止结果
        - success: 布尔值，表示停止是否成功
        - data: 布尔值，始终为True
        - error_msg: 错误信息，仅在失败时提供
        - elapsed_time: 停止耗时（秒）
        """
        start_time = time.time()
        with self.lock_manager:
            if not self.running:
                self.logger.warning("自动化系统已处于停止状态，无需重复停止")
                return AutoResult.success_result(data=True, elapsed_time=0.0)

            try:
                self.logger.info("停止自动化系统，释放资源...")
                # 设置中断标志
                self.set_should_stop(True)

                # 释放设备资源
                self.device_manager.disconnect_all()

                # 使用统一资源管理器清理资源
                self.resource_manager.cleanup_on_stop()

                # 清理图像处理器缓存
                self.image_processor.clear_screenshot_cache()

                # 重置运行状态
                self.running = False
                self.start_time = None

                elapsed = time.time() - start_time
                self.logger.info(f"自动化系统停止成功，耗时: {elapsed:.2f}秒")
                return AutoResult.success_result(data=True, elapsed_time=elapsed)
            except Exception as e:
                elapsed = time.time() - start_time
                self.logger.error(f"自动化系统停止异常: {str(e)}", exc_info=True)
                return AutoResult.fail_result(error_msg=str(e), elapsed_time=elapsed)

    # ======================== 设备管理代理方法（对外暴露） ========================
    def add_device(self, device_uri: str = "", timeout: float = None) -> AutoResult:
        """
        代理调用设备处理器的添加设备方法

        :param device_uri: 设备URI，默认使用初始化时设置的默认设备URI
        :param timeout: 设备连接超时时间（秒），默认使用配置中的DEFAULT_DEVICE_TIMEOUT
        :return: AutoResult对象，包含添加设备的结果
        """
        device_uri = device_uri or self.default_device_uri
        return self.device_handler.add_device(device_uri, timeout)

    def set_active_device(self, device_uri: str) -> AutoResult:
        """
        代理调用设备处理器的设置活动设备方法

        :param device_uri: 要设置为活动设备的URI
        :return: AutoResult对象，包含设置结果
        """
        return self.device_handler.set_active_device(device_uri)

    # ======================== 验证方法代理（对外暴露） ========================
    def check_element_exist(self, *args, **kwargs) -> AutoResult:
        """代理调用验证处理器的检查元素存在方法"""
        return self.verify_handler.check_element_exist(*args, **kwargs)

    def wait_element(self, *args, **kwargs) -> AutoResult:
        """代理调用验证处理器的等待元素方法"""
        return self.verify_handler.wait_element(*args, **kwargs)

    def wait_text(self, *args, **kwargs) -> AutoResult:
        """代理调用验证处理器的等待文本方法"""
        return self.verify_handler.wait_text(*args, **kwargs)

    def verify(self, *args, **kwargs) -> AutoResult:
        """代理调用验证处理器的统一验证方法"""
        return self.verify_handler.verify(*args, **kwargs)

    # ======================== 操作方法代理（对外暴露） ========================
    def click(self, *args, **kwargs) -> AutoResult:
        """代理调用操作处理器的坐标点击方法"""
        return self.operation_handler.click(*args, **kwargs)

    def template_click(self, *args, **kwargs) -> AutoResult:
        """代理调用操作处理器的模板点击方法"""
        return self.operation_handler.template_click(*args, **kwargs)

    def text_click(self, *args, **kwargs) -> AutoResult:
        """代理调用操作处理器的文本点击方法"""
        return self.operation_handler.text_click(*args, **kwargs)

    def swipe(self, *args, **kwargs) -> AutoResult:
        """代理调用操作处理器的滑动方法"""
        return self.operation_handler.swipe(*args, **kwargs)

    def text_input(self, *args, **kwargs) -> AutoResult:
        """代理调用操作处理器的文本输入方法"""
        return self.operation_handler.text_input(*args, **kwargs)

    def key_press(self, *args, **kwargs) -> AutoResult:
        """代理调用操作处理器的按键方法"""
        return self.operation_handler.key_press(*args, **kwargs)

    def sleep(self, *args, **kwargs) -> AutoResult:
        """代理调用操作处理器的睡眠方法"""
        return self.operation_handler.sleep(*args, **kwargs)

    # ======================== 状态查询方法 ========================
    @property
    def is_running(self) -> bool:
        """查询系统运行状态"""
        return self.running

    @property
    def uptime(self) -> float:
        """查询系统运行时长（秒）"""
        if not self.start_time:
            return 0.0
        return time.time() - self.start_time

    def get_device_info(self, device_uri: str = None) -> Dict[str, Any]:
        """获取设备详细信息"""
        device_uri = device_uri or self.default_device_uri
        try:
            device = self.device_handler.get_device(device_uri)
            if not device:
                return {"success": False, "error": f"设备 {device_uri} 不存在"}

            return {
                "success": True,
                "device_uri": device.device_uri,
                "device_type": device.device_type,
                "resolution": device.resolution,
                "status": device.status,
                "last_error": device.last_error,
                "connect_time": device.connect_time,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_task_logger(self, task_name: str) -> "Logger":
        """
        获取任务日志器（向后兼容方法）

        :param task_name: 任务名称
        :return: 配置好的任务Logger实例
        """
        return self.logger.create_task_logger(task_name)
