import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

# 延迟导入 ConfigLoader，避免循环依赖
from ...core.path_manager import PathManager
from ..config import (
    DEFAULT_BASE_RESOLUTION,
    DEFAULT_CHECK_ELEMENT_DELAY,
    DEFAULT_CLICK_DELAY,
    DEFAULT_AFTER_CLICK_DELAY,
    DEFAULT_DEVICE_URI,
    DEFAULT_KEY_DURATION,
    DEFAULT_OCR_ENGINE,
    DEFAULT_WAIT_TIMEOUT,
)
from ..devices.base_device import BaseDevice
from ..devices.device_manager import DeviceManager
from ..devices.windows_device import CoordType
from ..image.image_processor import ImageProcessor
from ..ocr.ocr_processor import OCRProcessor
from ..utils.coordinate_transformer import CoordinateTransformer
from ..utils.display_context import RuntimeDisplayContext
from ..utils.logger import Logger


class Auto:
    """
    自动化系统调用层：对外提供统一操作接口，衔接业务逻辑与底层工具（设备/图像/OCR）

    坐标体系说明：
    - 客户区逻辑坐标（默认）：当前窗口客户区的相对坐标（与窗口实际分辨率无关，0<=x<=客户区宽度，0<=y<=客户区高度）
      当coord_type="LOGICAL"时传入（默认），直接传递给device层执行
    - 客户区物理坐标：当前窗口客户区的物理像素坐标（考虑DPI缩放）
      当coord_type="PHYSICAL"时传入，内部自动转换为客户区逻辑坐标
    - 基准坐标：全屏场景下采集的原始坐标（基于默认基准分辨率1920x1080），适用于窗口缩放适配
      当coord_type="BASE"时传入，内部自动转换为当前窗口的客户区逻辑坐标
    - ROI格式：(x, y, width, height)，默认传递基准ROI，内部自动转换为客户区逻辑坐标
    """

    def __init__(
        self,
        ocr_engine: str = DEFAULT_OCR_ENGINE,
        device_type: str = "windows",
        device_uri: str = None,
        original_base_res: Tuple[int, int] = DEFAULT_BASE_RESOLUTION,
        path_manager: PathManager = None,
        config: "ConfigLoader" = None,
    ):
        """
        初始化自动化系统核心实例

        Args:
            ocr_engine: OCR识别引擎类型，默认使用配置的DEFAULT_OCR_ENGINE
            device_type: 设备类型，支持"windows"或"adb"，默认"windows"
            device_uri: 默认设备标识URI，None则根据设备类型自动生成
            original_base_res: 基准分辨率（宽, 高），默认使用DEFAULT_BASE_RESOLUTION
            path_manager: 路径管理器实例，用于获取项目路径
            config: 配置加载器实例，用于获取配置信息
        """
        # 记录总初始化开始时间
        total_init_start = time.time()

        # 使用传入的依赖或创建默认实例
        from ...core.config_manager import config as default_config
        from ...core.path_manager import path_manager as default_path_manager

        self.path_manager = path_manager or default_path_manager
        self.config = config or default_config
        self.test_mode = self.config.get("debug", False)
        self.lock = threading.RLock()  # 使用可重入锁，解决递归锁问题
        self.stop_event = threading.Event()
        self.running = False
        self.start_time = None

        # 初始化Logger模块
        logger_start = time.time()
        self.logger = Logger(
            name="System",
            base_log_dir=self.path_manager.get("log"),
            log_file_prefix="system",
            file_log_level=logging.DEBUG,
            console_log_level=logging.INFO,
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
        )
        ocr_time = round(time.time() - ocr_start, 3)

        # 根据设备类型设置默认device_uri
        if device_uri is None:
            if device_type == "adb":
                self.default_device_uri = "adb://default"
            else:  # windows
                self.default_device_uri = DEFAULT_DEVICE_URI
        else:
            self.default_device_uri = device_uri

        self.last_result = None
        self.last_error = None

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

    def check_should_stop(self) -> bool:
        """
        线程安全检查任务中断标志

        Returns:
            bool: True表示需要中断任务，False表示继续执行
        """
        return self.stop_event.is_set()

    def set_should_stop(self, value: bool) -> None:
        """
        线程安全设置任务中断标志

        Args:
            value: True设置中断标志，False清除中断标志
        """
        with self.lock:
            current_state = self.stop_event.is_set()
            if value and not current_state:
                self.stop_event.set()
                self.logger.info("任务已接收中断指令")
            elif not value and current_state:
                self.stop_event.clear()
                self.logger.debug("任务中断标志已重置")

    def _get_device(self, device_uri: Optional[str] = None) -> Optional[BaseDevice]:
        """
        内部方法：获取设备实例（优先级：指定URI → 活动设备）

        Args:
            device_uri: 目标设备URI，None则使用默认设备URI

        Returns:
            Optional[BaseDevice]: 设备实例，未找到返回None
        """
        target_uri = device_uri or self.default_device_uri

        device = self.device_manager.get_device(target_uri) or self.device_manager.get_active_device()

        if device:
            dev_uri = getattr(device, "device_uri", "未知URI")
            self.logger.debug(f"使用设备: {dev_uri}")
        else:
            self.last_error = "未找到可用设备"
            self.logger.error(self.last_error)

        return device

    def _apply_delay(self, delay: float) -> None:
        """
        内部方法：带中断检查的延迟（高效等待，减少CPU占用）

        Args:
            delay: 延迟时长（秒）
        """
        if delay <= 0:
            return

        if self.stop_event.wait(timeout=delay):
            self.logger.info(f"延迟 {delay}s 被中断")

    # ======================== 基础工具方法 ========================
    def sleep(self, secs: float = 1.0) -> bool:
        """
        带中断检查的睡眠操作

        Args:
            secs: 睡眠时长（秒），默认1.0秒

        Returns:
            bool: True睡眠完成，False被中断或执行失败
        """
        if self.check_should_stop():
            self.logger.debug("睡眠任务被中断")
            self.last_result = False
            return False

        device = self._get_device()
        try:
            if device:
                result = device.sleep(secs, stop_event=self.stop_event)
            else:
                self._apply_delay(secs)
                result = True

            self.last_result = result
            self.logger.debug(f"睡眠完成: {secs}秒")
            return result
        except Exception as e:
            self.last_error = f"睡眠失败: {str(e)}"
            self.logger.error(self.last_error)
            self.last_result = False
            return False

    # ======================== 等待与验证机制 ========================
    def wait_for(
        self, condition: Callable[[], bool], timeout: int = 30, interval: float = 0.5, desc: str = "条件验证"
    ) -> bool:
        """
        等待条件满足，支持超时和中断检查

        Args:
            condition: 条件验证函数，返回True表示条件满足
            timeout: 最大等待时间（秒），默认30秒
            interval: 检查间隔（秒），默认0.5秒
            desc: 条件描述，用于日志

        Returns:
            bool: 条件满足返回True，超时返回False
        """
        start_time = time.time()
        self.logger.info(f"[等待] {desc}，超时: {timeout}秒")

        while True:
            if self.check_should_stop():
                self.logger.info(f"[等待中断] {desc}")
                return True

            elapsed = time.time() - start_time
            if elapsed >= timeout:
                self.logger.warning(f"[等待超时] {desc}，耗时: {elapsed:.1f}秒")
                return False

            if condition():
                self.logger.info(f"[等待成功] {desc}，耗时: {elapsed:.1f}秒")
                return True

            self.sleep(interval)

    def verify(
        self,
        verify_type: str,
        target: Union[str, List[str]],
        timeout: int = 30,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> bool:
        """
        统一的屏幕验证方法

        Args:
            verify_type: 验证类型，可选值："exist", "disappear", "text"
            target: 验证目标，模板名称或文本
            timeout: 验证超时时间（秒），默认30秒
            roi: 验证区域（基准ROI）

        Returns:
            bool: 验证成功返回True，否则返回False
        """
        self.logger.info(f"[验证] {verify_type} - {target}，超时: {timeout}秒")

        def condition() -> bool:
            if verify_type == "exist":
                return self.check_element_exist(target, roi=roi, wait_timeout=0) is not None
            elif verify_type == "disappear":
                return self.check_element_exist(target, roi=roi, wait_timeout=0) is None
            elif verify_type == "text":
                return self.text_click(target, click=False, roi=roi) is not None
            else:
                self.last_error = f"无效的验证类型: {verify_type}"
                self.logger.error(self.last_error)
                return False

        return self.wait_for(condition, timeout, desc=f"{verify_type} - {target}")

    # ======================== 设备管理方法 ========================
    def add_device(self, device_uri: str = DEFAULT_DEVICE_URI, timeout: float = 10.0) -> bool:
        """
        添加设备（分辨率同步由DeviceManager自动处理）

        Args:
            device_uri: 设备标识URI（如窗口句柄、设备ID等），默认DEFAULT_DEVICE_URI
            timeout: 连接超时时间（秒），默认10.0秒

        Returns:
            bool: 添加请求提交成功返回True，失败返回False
        """
        if self.check_should_stop():
            self.logger.debug("添加设备任务被中断")
            self.last_result = False
            return False

        try:
            result = self.device_manager.add_device(device_uri=device_uri, timeout=timeout)
            self.last_result = result

            if result:
                self.logger.info(f"设备 {device_uri} 添加请求已提交")
            else:
                self.last_error = f"设备 {device_uri} 添加失败"
                self.logger.error(self.last_error)

            return result
        except Exception as e:
            self.last_error = f"添加设备异常: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            self.last_result = False
            return False

    def set_active_device(self, device_uri: str) -> bool:
        """
        设置活动设备（后续操作默认使用该设备，分辨率自动同步）

        Args:
            device_uri: 设备标识URI

        Returns:
            bool: 设置成功返回True，失败返回False
        """
        result = self.device_manager.set_active_device(device_uri)
        self.last_result = result

        if not result:
            self.last_error = f"设置活动设备失败: {device_uri}"
            self.logger.error(self.last_error)
        else:
            self.logger.info(f"活动设备切换为: {device_uri}")

        return result

    def get_task_logger(self, task_name: str) -> Logger:
        """
        获取独立任务日志器（日志多播到任务文件+system.log+控制台）

        Args:
            task_name: 任务名称（作为日志文件前缀）

        Returns:
            Logger: 任务专属Logger实例
        """
        return self.logger.create_task_logger(task_name)

    # ======================== 系统控制方法 ========================
    def start(self) -> None:
        """启动自动化系统（重置中断标志，初始化运行状态）"""
        with self.lock:
            if self.running:
                self.logger.info("系统已处于运行状态")
                return
            self.running = True
            self.set_should_stop(False)
            self.start_time = time.time()

        self.logger.info("自动化系统开始启动")

    def stop(self) -> None:
        """停止自动化系统（中断所有任务，清理设备连接和日志资源）"""
        with self.lock:
            if not self.running:
                self.logger.info("系统已处于停止状态")
                return
            self.running = False
            self.set_should_stop(True)

        success, fail = self.device_manager.disconnect_all()
        self.logger.info(f"设备断开统计: 成功{success}个, 失败{fail}个")

        # 计算系统运行时长
        if self.start_time:
            total_time = round(time.time() - self.start_time, 2)
            minutes = int(total_time // 60)
            seconds = round(total_time % 60, 2)
            self.logger.info(f"系统运行时长: {minutes}分{seconds}秒")
            self.start_time = None

        self.logger.info("BD2-AUTO 自动化系统已停止")
        self.logger.shutdown()

    def get_status(self) -> dict:
        """
        获取系统完整状态（包含设备、运行状态、上下文等信息）

        Returns:
            dict: 系统状态字典，包含以下字段：
                - system_running: 系统是否运行
                - task_should_stop: 是否需要中断任务
                - active_device: 活动设备URI
                - active_device_state: 活动设备状态
                - total_devices: 设备总数
                - device_list: 设备URI列表
                - device_states: 各设备详细状态
                - loaded_templates: 已加载模板数量
                - last_error: 最后一次错误信息
                - last_result: 最后一次操作结果
        """
        active_device = self.device_manager.get_active_device()

        device_states = {}
        for uri, dev in self.device_manager.devices.items():
            device_states[uri] = {
                "state": dev.get_state().name,
                "is_connected": dev.is_connected,
                "client_size": dev.get_resolution() if dev.is_connected else None,
            }

        status = {
            "system_running": self.running,
            "task_should_stop": self.check_should_stop(),
            "active_device": (
                active_device.device_uri if (active_device and hasattr(active_device, "device_uri")) else None
            ),
            "active_device_state": active_device.get_state().name if active_device else None,
            "total_devices": len(self.device_manager),
            "device_list": list(self.device_manager.devices.keys()),
            "device_states": device_states,
            "loaded_templates": len(self.image_processor.templates) if self.image_processor else 0,
            "last_error": self.last_error,
            "last_result": self.last_result,
        }
        self.logger.debug(f"系统状态查询结果: {status}")
        return status

    # ======================== 核心操作方法 ========================
    def click(
        self,
        pos: Tuple[int, int],
        click_time: int = 1,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        coord_type: str = "LOGICAL",
        verify: Optional[dict] = None,
        retry: int = 0,
    ) -> bool:
        """
        坐标点击操作（自动进行坐标转换）

        Args:
            pos: 点击坐标 (x, y)
            click_time: 点击次数，默认1次
            delay: 执行前延迟时间（秒），默认DEFAULT_CLICK_DELAY
            device_uri: 目标设备URI（None使用默认设备）
            coord_type: 坐标类型（默认"LOGICAL"：客户区逻辑坐标；"BASE"：基准分辨率坐标；"PHYSICAL"：客户区物理坐标）
            verify: 验证配置，格式：{"type": "exist", "target": "template_name", "timeout": 10}
            retry: 重试次数，默认0次

        Returns:
            bool: 点击成功返回True，失败返回False
        """
        coord_type_str = (
            "基准坐标" if coord_type == "BASE" else ("客户区物理坐标" if coord_type == "PHYSICAL" else "客户区逻辑坐标")
        )

        for attempt in range(retry + 1):
            if self.check_should_stop():
                self.logger.debug("点击任务被中断")
                self.last_result = False
                return False

            self._apply_delay(delay)
            device = self._get_device(device_uri)
            if not device:
                self.last_result = False
                continue

            # 根据字符串类型转换为CoordType枚举
            if coord_type == "BASE":
                device_coord_type = CoordType.BASE
            elif coord_type == "PHYSICAL":
                device_coord_type = CoordType.PHYSICAL
            else:  # 默认LOGICAL
                device_coord_type = CoordType.LOGICAL

            result = device.click((pos[0], pos[1]), click_time=click_time, coord_type=device_coord_type)

            if not result:
                self.last_error = device.last_error or "点击执行失败"
                self.logger.error(self.last_error)
                continue

            self.logger.info(f"点击成功: {coord_type_str}{pos} | 点击次数{click_time}")

            # 点击后等待画面变化
            self._apply_delay(DEFAULT_AFTER_CLICK_DELAY)

            # 如果不需要验证，直接返回成功
            if not verify:
                self.last_result = True
                return True

            # 执行验证
            if self.verify(
                verify_type=verify.get("type"),
                target=verify.get("target"),
                timeout=verify.get("timeout", DEFAULT_WAIT_TIMEOUT),
                roi=verify.get("roi"),
            ):
                self.last_result = True
                return True

            self.logger.warning(f"[验证失败] 坐标点击 {coord_type_str}{pos}，尝试: {attempt + 1}/{retry + 1}")

        self.logger.error(f"[坐标点击失败] {coord_type_str}{pos}，已达最大重试次数: {retry}")
        self.last_result = False
        return False

    def key_press(
        self,
        key: str,
        duration: float = DEFAULT_KEY_DURATION,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        verify: Optional[dict] = None,
        retry: int = 0,
    ) -> bool:
        """
        按键操作（支持系统按键和普通字符键）

        Args:
            key: 按键标识（如 'enter'、'a'、'ctrl+c' 等）
            duration: 按键按住时长（秒），默认DEFAULT_KEY_DURATION
            delay: 执行前延迟时间（秒），默认DEFAULT_CLICK_DELAY
            device_uri: 目标设备URI（None使用默认设备）
            verify: 验证配置，格式：{"type": "exist", "target": "template_name", "timeout": 10}
            retry: 重试次数，默认0次

        Returns:
            bool: 按键成功返回True，失败返回False
        """
        for attempt in range(retry + 1):
            if self.check_should_stop():
                self.logger.debug("按键任务被中断")
                self.last_result = False
                return False

            self._apply_delay(delay)
            device = self._get_device(device_uri)
            if not device:
                self.last_result = False
                continue

            result = device.key_press(key, duration=duration)
            if not result:
                self.last_error = device.last_error or f"按键 {key} 失败"
                self.logger.error(self.last_error)
                continue

            self.logger.info(f"按键成功: {key} | 按住时长{duration}s")

            # 按键后等待画面变化
            self._apply_delay(DEFAULT_AFTER_CLICK_DELAY)

            # 如果不需要验证，直接返回成功
            if not verify:
                self.last_result = True
                return True

            # 执行验证
            if self.verify(
                verify_type=verify.get("type"),
                target=verify.get("target"),
                timeout=verify.get("timeout", DEFAULT_WAIT_TIMEOUT),
                roi=verify.get("roi"),
            ):
                self.last_result = True
                return True

            self.logger.warning(f"[验证失败] 按键 {key}，尝试: {attempt + 1}/{retry + 1}")

        self.logger.error(f"[按键失败] {key}，已达最大重试次数: {retry}")
        self.last_result = False
        return False

    def template_click(
        self,
        template: Union[str, List[str]],
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        duration: float = 0.1,
        click_time: int = 1,
        right_click: bool = False,
        roi: Optional[Tuple[int, int, int, int]] = None,
        verify: Optional[dict] = None,
        retry: int = 0,
    ) -> bool:
        """
        模板匹配点击（支持多模板、ROI筛选，自动适配分辨率）

        Args:
            template: 模板名称（单个或多个模板列表）
            delay: 执行前延迟时间（秒），默认DEFAULT_CLICK_DELAY
            device_uri: 目标设备URI（None使用默认设备）
            duration: 点击按住时长（秒），默认0.1秒
            click_time: 点击次数，默认1次
            right_click: 是否右键点击（默认False：左键）
            roi: 搜索区域（基准ROI，格式 (x, y, width, height)，None则全屏搜索）
            verify: 验证配置，格式：{"type": "exist", "target": "template_name", "timeout": 10}
            retry: 重试次数，默认0次

        Returns:
            bool: 点击成功返回True，失败返回False
        """
        templates = [template] if isinstance(template, str) else template
        roi_info = f"，ROI: {roi}" if roi else ""
        template_info = f"{templates[0]}等{len(templates)}个模板" if len(templates) > 1 else str(templates[0])

        for attempt in range(retry + 1):
            self.logger.info(f"[模板点击] {template_info}{roi_info}，尝试: {attempt + 1}/{retry + 1}")

            if self.check_should_stop():
                self.logger.debug("[模板点击中断] 任务被中断")
                self.last_result = False
                return False

            self._apply_delay(delay)
            device = self._get_device(device_uri)
            if not device:
                self.last_result = False
                continue

            result = device.click(
                pos=templates, duration=duration, click_time=click_time, right_click=right_click, roi=roi
            )

            if not result:
                self.last_error = device.last_error or f"模板 {templates} 点击失败"
                self.logger.warning(f"[点击失败] {template_info}{roi_info}")
                continue

            self.logger.info(f"[点击成功] {template_info}{roi_info} | 右键={right_click}")

            # 点击后等待画面变化
            self._apply_delay(DEFAULT_AFTER_CLICK_DELAY)

            # 如果不需要验证，直接返回成功
            if not verify:
                self.last_result = True
                return True

            # 执行验证
            if self.verify(
                verify_type=verify.get("type"),
                target=verify.get("target"),
                timeout=verify.get("timeout", DEFAULT_WAIT_TIMEOUT),
                roi=verify.get("roi"),
            ):
                self.last_result = True
                return True

            self.logger.warning(f"[验证失败] {template_info}{roi_info}，尝试: {attempt + 1}/{retry + 1}")

        self.logger.error(f"[模板点击失败] {template_info}{roi_info}，已达最大重试次数: {retry}")
        self.last_result = False
        return False

    def text_click(
        self,
        text: str,
        click: bool = True,
        lang: str = None,
        roi: Optional[tuple] = None,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        duration: float = 0.1,
        click_time: int = 1,
        right_click: bool = False,
        verify: Optional[dict] = None,
        retry: int = 0,
    ) -> Optional[Tuple[int, int]]:
        """
        OCR文本识别并点击（支持ROI筛选，自动坐标适配）

        Args:
            text: 目标识别文本
            click: 是否执行点击（默认True：识别后点击）
            lang: OCR识别语言（默认自动适配）
            roi: 识别区域（基准ROI，格式 (x, y, width, height)，None则全屏识别）
            delay: 执行前延迟时间（秒），默认DEFAULT_CLICK_DELAY
            device_uri: 目标设备URI（None使用默认设备）
            duration: 点击按住时长（秒），默认0.1秒
            click_time: 点击次数，默认1次
            right_click: 是否右键点击（默认False：左键）
            verify: 验证配置，格式：{"type": "exist", "target": "template_name", "timeout": 10}
            retry: 重试次数，默认0次

        Returns:
            Optional[Tuple[int, int]]: 点击坐标（客户区逻辑坐标），未识别到文本或失败返回None
        """
        roi_info = f"，ROI: {roi}" if roi else ""

        for attempt in range(retry + 1):
            self.logger.info(f"[文本点击] '{text}'{roi_info}，尝试: {attempt + 1}/{retry + 1}")

            if self.check_should_stop():
                self.logger.debug("[文本点击中断] 任务被中断")
                self.last_result = None
                return None

            self._apply_delay(delay)
            device = self._get_device(device_uri)
            if not device:
                self.last_result = None
                continue

            screen = device.capture_screen()
            if screen is None:
                self.last_error = "[文本点击] 截图失败"
                self.logger.error(self.last_error)
                self.last_result = None
                continue

            if roi:
                self.logger.debug(f"[文本识别] '{text}' | ROI: {roi}")

            ocr_result = self.ocr_processor.find_text_position(image=screen, target_text=text, lang=lang, region=roi)

            if not ocr_result:
                self.last_error = f"[文本识别失败] 未识别到文本 '{text}'"
                self.logger.warning(self.last_error)
                self.last_result = None
                continue

            text_pos_log = ocr_result
            x_log, y_log, w_log, h_log = text_pos_log
            click_center = (x_log + w_log // 2, y_log + h_log // 2)

            is_fullscreen = self.coord_transformer.is_fullscreen
            self.logger.info(
                f"[识别成功] '{text}' | 模式: {'全屏' if is_fullscreen else '窗口'} | "
                f"坐标: ({x_log},{y_log},{w_log},{h_log}) | 中心点: {click_center}"
            )

            if click:
                click_result = device.click(
                    pos=click_center,
                    duration=duration,
                    click_time=click_time,
                    right_click=right_click,
                    coord_type=CoordType.LOGICAL,  # 标识点击坐标为逻辑坐标
                )
                if not click_result:
                    self.last_error = device.last_error or "[文本点击执行失败]"
                    self.logger.error(self.last_error)
                    continue
            else:
                self.logger.info(f"[识别成功] 未点击: '{text}'")

            # 点击或识别后等待画面变化
            self._apply_delay(DEFAULT_AFTER_CLICK_DELAY)

            # 如果不需要验证，直接返回成功
            if not verify:
                self.last_result = click_center
                return click_center

            # 执行验证
            if self.verify(
                verify_type=verify.get("type"),
                target=verify.get("target"),
                timeout=verify.get("timeout", DEFAULT_WAIT_TIMEOUT),
                roi=verify.get("roi"),
            ):
                self.last_result = click_center
                return click_center

            self.logger.warning(f"[验证失败] '{text}'{roi_info}，尝试: {attempt + 1}/{retry + 1}")

        self.logger.error(f"[文本点击失败] '{text}'{roi_info}，已达最大重试次数: {retry}")
        self.last_result = None
        return None

    # ======================== 图像相关方法 ========================
    def check_element_exist(
        self,
        template_name: Union[str, List[str]],
        delay: float = DEFAULT_CHECK_ELEMENT_DELAY,
        device_uri: Optional[str] = None,
        roi: Optional[Tuple[int, int, int, int]] = None,
        wait_timeout: int = 0,
    ) -> Optional[Tuple[int, int]]:
        """
        检查模板元素是否存在并返回坐标（支持多模板、ROI筛选）

        Args:
            template_name: 模板名称（单个或多个模板列表）
            delay: 执行前延迟时间（秒），默认DEFAULT_CHECK_ELEMENT_DELAY
            device_uri: 目标设备URI（None使用默认设备）
            roi: 检查区域（基准ROI，格式 (x, y, width, height)，None则全屏检查）
            wait_timeout: 等待元素出现的超时时间（秒），0表示不等待

        Returns:
            找到返回元素中心点坐标（客户区逻辑坐标），未找到或失败返回None
        """

        # 内部检查函数，避免重复调用
        def _check_once():
            if self.check_should_stop():
                self.logger.debug("检查元素任务被中断")
                self.last_result = None
                return None

            self._apply_delay(delay)
            device = self._get_device(device_uri)
            if not device or not device.is_connected:
                self.last_error = "检查元素失败: 设备未连接"
                self.logger.error(self.last_error)
                self.last_result = None
                return None

            templates = [template_name] if isinstance(template_name, str) else template_name

            params_info = []
            if roi:
                params_info.append(f"基准ROI: {roi}")
            params_info.append(f"客户区尺寸: {self.display_context.client_logical_res}")
            if len(templates) > 1:
                params_info.append(f"模板数量: {len(templates)}")
            param_log = f" | {', '.join(params_info)}" if params_info else ""

            self.logger.debug(f"检查元素请求: {templates}{param_log}")

            try:
                result = device.exists(templates, roi=roi)
                self.last_result = result

                if device.last_error:
                    self.last_error = f"检查元素异常: {device.last_error}"
                    self.logger.warning(self.last_error)

                if result:
                    self.logger.info(f"找到元素 {templates}{param_log}，中心点: {result}")
                else:
                    self.logger.info(f"未找到元素 {templates}{param_log}")
                return result
            except Exception as e:
                self.last_error = f"检查元素异常: {str(e)}"
                self.logger.error(self.last_error, exc_info=True)
                self.last_result = None
                return None

        # 直接检查或等待检查
        if wait_timeout > 0:
            result = None

            def condition_func():
                nonlocal result
                result = _check_once()
                return result is not None

            if self.wait_for(condition_func, wait_timeout, desc=f"等待元素 {template_name} 出现"):
                return result
            else:
                return None
        else:
            return _check_once()

    def wait_element(
        self, template: Union[str, List[str]], timeout: int = 30, roi: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Tuple[int, int]]:
        """
        等待元素出现并返回坐标

        Args:
            template: 模板名称
            timeout: 超时时间（秒）
            roi: 搜索区域（基准ROI）

        Returns:
            Optional[Tuple[int, int]]: 找到返回元素中心点坐标，超时返回None
        """
        return self.check_element_exist(template, roi=roi, wait_timeout=timeout)

    def wait_text(
        self, text: str, timeout: int = 30, roi: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Tuple[int, int]]:
        """
        等待文本出现并返回坐标

        Args:
            text: 目标文本
            timeout: 超时时间（秒）
            roi: 搜索区域（基准ROI）

        Returns:
            Optional[Tuple[int, int]]: 找到返回文本中心点坐标，超时返回None
        """
        result = None

        def condition_func():
            nonlocal result
            result = self.text_click(text, click=False, roi=roi)
            return result is not None

        if self.wait_for(condition_func, timeout, desc=f"等待文本 '{text}' 出现"):
            return result
        else:
            return None

    def swipe(
        self,
        start_pos: tuple,
        end_pos: tuple,
        duration: float = 3,
        steps: int = 10,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        coord_type: str = "LOGICAL",
        verify: Optional[dict] = None,
        retry: int = 0,
    ) -> bool:
        """
        滑动操作（支持多种坐标类型，自动平滑移动）

        Args:
            start_pos: 滑动起始坐标 (x, y)
            end_pos: 滑动结束坐标 (x, y)
            duration: 滑动总时长（秒），默认3秒
            steps: 滑动步数（步数越多越平滑，默认10步）
            delay: 执行前延迟时间（秒），默认DEFAULT_CLICK_DELAY
            device_uri: 目标设备URI（None使用默认设备）
            coord_type: 坐标类型（默认LOGICAL：客户区逻辑坐标；PHYSICAL：客户区物理坐标；BASE：基准分辨率采集的坐标）
            verify: 验证配置，格式：{"type": "exist", "target": "template_name", "timeout": 10}
            retry: 重试次数，默认0次

        Returns:
            bool: 滑动成功返回True，失败返回False
        """
        coord_type_name = {"LOGICAL": "客户区逻辑坐标", "PHYSICAL": "客户区物理坐标", "BASE": "基准坐标"}.get(
            coord_type.upper(), "未知坐标类型"
        )

        for attempt in range(retry + 1):
            if self.check_should_stop():
                self.logger.debug("滑动任务被中断")
                self.last_result = False
                return False

            self._apply_delay(delay)
            device = self._get_device(device_uri)
            if not device:
                self.last_result = False
                continue

            if not (isinstance(start_pos, (tuple, list)) and len(start_pos) == 2):
                self.last_error = f"滑动失败: 起始坐标格式无效（{start_pos}）"
                self.logger.error(self.last_error)
                self.last_result = False
                continue
            if not (isinstance(end_pos, (tuple, list)) and len(end_pos) == 2):
                self.last_error = f"滑动失败: 结束坐标格式无效（{end_pos}）"
                self.logger.error(self.last_error)
                self.last_result = False
                continue

            # 坐标类型验证
            valid_coord_types = {"LOGICAL", "PHYSICAL", "BASE"}
            if coord_type not in valid_coord_types:
                self.logger.warning(f"无效的坐标类型: {coord_type}，使用默认类型LOGICAL")
                coord_type = "LOGICAL"
                coord_type_name = "客户区逻辑坐标"

            # 坐标范围检查（仅针对逻辑坐标）
            if coord_type == "LOGICAL":
                client_w, client_h = self.display_context.client_logical_res
                sx, sy = start_pos
                ex, ey = end_pos
                if not (0 <= sx <= client_w and 0 <= sy <= client_h):
                    self.logger.warning(f"起始坐标超出客户区范围: {start_pos} | 客户区: {client_w}x{client_h}")
                if not (0 <= ex <= client_w and 0 <= ey <= client_h):
                    self.logger.warning(f"结束坐标超出客户区范围: {end_pos} | 客户区: {client_w}x{client_h}")

            # 转换字符串到CoordType枚举
            coord_type_enum = getattr(CoordType, coord_type.upper())

            result = device.swipe(
                start_x=start_pos[0],
                start_y=start_pos[1],
                end_x=end_pos[0],
                end_y=end_pos[1],
                duration=duration,
                steps=steps,
                coord_type=coord_type_enum,
            )

            if not result:
                self.last_error = device.last_error or "滑动执行失败"
                self.logger.error(self.last_error)
                continue

            self.logger.info(f"滑动成功: 从{start_pos}到{end_pos} | 类型:{coord_type_name} | 时长{duration}s")

            # 如果不需要验证，直接返回成功
            if not verify:
                self.last_result = True
                return True

            # 执行验证
            if self.verify(
                verify_type=verify.get("type"),
                target=verify.get("target"),
                timeout=verify.get("timeout", DEFAULT_WAIT_TIMEOUT),
                roi=verify.get("roi"),
            ):
                self.last_result = True
                return True

            self.logger.warning(f"[验证失败] 滑动从{start_pos}到{end_pos}，尝试: {attempt + 1}/{retry + 1}")

        self.logger.error(f"[滑动失败] 从{start_pos}到{end_pos}，已达最大重试次数: {retry}")
        self.last_result = False
        return False

    def text_input(
        self,
        text: str,
        interval: float = 0.05,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        verify: Optional[dict] = None,
        retry: int = 0,
    ) -> bool:
        """
        文本输入（优先粘贴模式，粘贴失败时自动降级为逐字符输入）

        Args:
            text: 待输入文本
            interval: 逐字符输入时间间隔（秒），默认0.05秒
            delay: 执行前延迟时间（秒），默认DEFAULT_CLICK_DELAY
            device_uri: 目标设备URI（None使用默认设备）
            verify: 验证配置，格式：{"type": "exist", "target": "template_name", "timeout": 10}
            retry: 重试次数，默认0次

        Returns:
            bool: 输入成功返回True，失败返回False
        """
        log_text = text[:30] + "..." if len(text) > 30 else text

        for attempt in range(retry + 1):
            if self.check_should_stop():
                self.logger.debug("文本输入任务被中断")
                self.last_result = False
                return False

            self._apply_delay(delay)
            device = self._get_device(device_uri)
            if not device or not device.is_connected:
                self.last_error = "文本输入失败: 设备未连接"
                self.logger.error(self.last_error)
                self.last_result = False
                continue

            result = device.text_input(text, interval=interval)
            if not result:
                self.last_error = device.last_error or f"输入文本 '{log_text}' 失败"
                self.logger.error(self.last_error)
                continue

            self.logger.info(f"文本输入成功: {log_text}")
            # 清除截图缓存，因为文本输入操作可能改变界面
            self.clear_screenshot_cache()

            # 如果不需要验证，直接返回成功
            if not verify:
                self.last_result = True
                return True

            # 执行验证
            if self.verify(
                verify_type=verify.get("type"),
                target=verify.get("target"),
                timeout=verify.get("timeout", DEFAULT_WAIT_TIMEOUT),
                roi=verify.get("roi"),
            ):
                self.last_result = True
                return True

            self.logger.warning(f"[验证失败] 文本输入 '{log_text}'，尝试: {attempt + 1}/{retry + 1}")

        self.logger.error(f"[文本输入失败] '{log_text}'，已达最大重试次数: {retry}")
        self.last_result = False
        return False
