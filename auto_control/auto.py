import logging
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from .config import (DEFAULT_BASE_RESOLUTION, DEFAULT_CHECK_ELEMENT_DELAY,
                     DEFAULT_CLICK_DELAY, DEFAULT_DEVICE_URI,
                     DEFAULT_DPI_SCALE, DEFAULT_KEY_DURATION,
                     DEFAULT_OCR_ENGINE, DEFAULT_SCREENSHOT_DELAY,
                     DEFAULT_TASK_TIMEOUT, DEFAULT_TEXT_FUZZY_MATCH,
                     DEFAULT_WINDOW_OPERATION_DELAY, LOG_CONFIG)
from .coordinate_transformer import CoordinateTransformer
from .device_base import BaseDevice, DeviceState
from .device_manager import DeviceManager
from .image_processor import ImageProcessor
from .logger import Logger
from .ocr_processor import OCRProcessor


# 此层传递均为客户区坐标
class Auto:
    def __init__(
        self,
        ocr_engine: str = DEFAULT_OCR_ENGINE,
        device_uri: str = DEFAULT_DEVICE_URI,
        base_resolution: Tuple[int, int] = DEFAULT_BASE_RESOLUTION,
        dpi_scale: float = DEFAULT_DPI_SCALE
    ):
        # 线程安全控制
        self.lock = threading.Lock()
        self.should_stop = False  # 任务中断标志
        self.running = False      # 系统运行状态

        # 日志初始化
        self.logger = Logger(
            task_name="System",
            base_log_dir=LOG_CONFIG["BASE_LOG_DIR"],
            log_file_prefix="system",
            file_log_level=logging.DEBUG,
            console_log_level=logging.INFO     # 控制台只输出重要信息
        )

        # 坐标转换初始化
        self.coord_transformer = CoordinateTransformer(
            original_base_res=base_resolution,
            original_dpi=dpi_scale,
            logger=self.logger
        )

        # 图像处理器初始化
        self.image_processor = ImageProcessor(
            original_base_res=base_resolution,
            original_dpi=dpi_scale,
            logger=self.logger,
            coord_transformer=self.coord_transformer
        )

        # 设备管理器初始化
        self.device_manager = DeviceManager(
            logger=self.logger,
            image_processor=self.image_processor,
            coord_transformer=self.coord_transformer
        )

        # OCR处理器初始化
        self.ocr_processor = OCRProcessor(
            engine=ocr_engine, logger=self.logger, coord_transformer=self.coord_transformer)

        # 设备配置
        self.default_device_uri = device_uri
        self.base_resolution = base_resolution

        # 结果与错误追踪
        self.last_result = None    # 最后操作结果
        self.last_error = None     # 最后错误信息

        self.logger.info("自动化系统初始化完成")

    def check_should_stop(self) -> bool:
        """线程安全检查任务中断标志"""
        with self.lock:
            return self.should_stop

    def set_should_stop(self, value: bool) -> None:
        """线程安全设置任务中断标志"""
        with self.lock:
            self.should_stop = value
            if value:
                self.logger.info("任务已接收中断指令")

    def _get_device(self, device_uri: Optional[str] = None) -> Optional[BaseDevice]:
        """获取设备实例（优先指定URI→活动设备）"""
        # 确定目标URI
        target_uri = device_uri or self.default_device_uri

        # 1. 优先获取指定URI的设备
        device = self.device_manager.get_device(target_uri)
        # 2. 未找到则获取活动设备
        if not device:
            device = self.device_manager.get_active_device()

        # 日志输出设备状态
        if device:
            dev_uri = device.device_uri if hasattr(
                device, 'device_uri') else "未知URI"
            self.logger.debug(
                f"使用设备: {dev_uri} | 状态: {device.get_state().name}"
            )
        else:
            self.last_error = "未找到可用设备"
            self.logger.error(f"错误: {self.last_error}")

        return device

    def _apply_delay(self, delay: float) -> None:
        """带中断检查的延迟（支持任务中途停止）"""
        if delay <= 0:
            return

        start_time = time.time()
        while time.time() - start_time < delay:
            if self.check_should_stop():
                self.logger.info(f"延迟 {delay}s 被中断")
                break
            time.sleep(0.1)  # 减少CPU占用

    # ======================== 基础工具方法 ========================
    def sleep(self, secs: float = 1.0) -> bool:
        """设备睡眠"""
        if self.check_should_stop():
            self.logger.info("睡眠任务被中断")
            self.last_result = False
            return False

        device = self._get_device()
        try:
            if device:
                result = device.sleep(secs)
            else:
                # 无设备时使用系统睡眠（带中断检查）
                self._apply_delay(secs)
                result = True

            self.last_result = result
            self.logger.debug(f"睡眠完成: {secs}秒")
            return result
        except Exception as e:
            self.last_error = f"睡眠失败: {str(e)}"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

    # ======================== 设备管理方法 ========================
    def add_device(self, device_uri: str = DEFAULT_DEVICE_URI, timeout: float = 10.0) -> bool:
        """添加设备并自动更新分辨率（优化时序）"""
        if self.check_should_stop():
            self.logger.info("添加设备任务被中断")
            self.last_result = False
            return False

        try:
            result = self.device_manager.add_device(
                device_uri=device_uri,
                timeout=timeout,
                logger=self.logger,
                image_processor=self.image_processor,
                coord_transformer=self.coord_transformer
            )
            self.last_result = result

            if result:
                # 直接获取刚添加的设备，而非依赖活动设备
                new_device = self.device_manager.get_device(device_uri)
                if new_device and new_device.is_connected:
                    # 临时将新设备设为活动设备（确保分辨率更新成功）
                    original_active = self.device_manager.active_device
                    self.device_manager.set_active_device(device_uri)

                    # 调用带重试的分辨率更新
                    if self._update_resolution_from_device():
                        self.logger.info(f"设备 {device_uri} 添加并更新分辨率成功")
                    else:
                        self.last_error = f"设备 {device_uri} 添加成功，但分辨率更新失败"
                        self.logger.warning(f"警告: {self.last_error}")

                    # 恢复原始活动设备（如果之前有）
                    if original_active and original_active != device_uri:
                        self.device_manager.set_active_device(original_active)
                else:
                    self.last_error = f"设备 {device_uri} 添加成功，但设备实例无效"
                    self.logger.warning(f"警告: {self.last_error}")
            else:
                self.last_error = f"设备 {device_uri} 添加失败"
                self.logger.error(f"错误: {self.last_error}")

            return result
        except Exception as e:
            self.last_error = f"添加设备异常: {str(e)}"
            self.logger.error(f"错误: {self.last_error}", exc_info=True)
            self.last_result = False
            return False

    def set_active_device(self, device_uri: str) -> bool:
        """设置活动设备（仅允许已连接设备）——删除冗余的坐标更新"""
        result = self.device_manager.set_active_device(device_uri)
        self.last_result = result

        if not result:
            self.last_error = f"设置活动设备失败: {device_uri}"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info(f"活动设备已切换为: {device_uri}")

        return result

    def _update_resolution_from_device(self, max_retries: int = 3, retry_delay: float = 0.2) -> bool:
        """从活动设备更新基准分辨率（重试机制）"""
        for retry in range(max_retries):
            device = self.device_manager.get_active_device()
            # 校验设备是否存在且已连接
            if not device or not device.is_connected:
                if retry < max_retries - 1:
                    self.logger.debug(f"重试获取活动设备（第{retry+1}次）...")
                    time.sleep(retry_delay)
                    continue
                self.last_error = "无法更新分辨率: 活动设备未连接或不存在"
                self.logger.error(f"错误: {self.last_error}")
                return False

            # 获取设备分辨率
            dev_state = device.get_state()
            if dev_state != DeviceState.CONNECTED:
                if retry < max_retries - 1:
                    self.logger.debug(
                        f"设备状态为{dev_state.name}，等待就绪（第{retry+1}次）...")
                    time.sleep(retry_delay)
                    continue

            resolution = device.get_resolution()
            if not resolution or resolution == (0, 0):
                self.last_error = "获取分辨率无效: 分辨率为(0,0)"
                self.logger.error(f"错误: {self.last_error}")
                return False

            # 更新分辨率（同步坐标转换器）
            self.base_resolution = resolution
            device._update_dynamic_window_info()
            self.logger.debug(f"从设备更新基准分辨率: {self.base_resolution}")
            return True

        # 超过最大重试次数
        self.last_error = f"超过{max_retries}次重试，仍无法获取有效设备分辨率"
        self.logger.error(f"错误: {self.last_error}")
        return False

    def get_task_logger(self, task_name: str) -> logging.Logger:
        """获取任务专用日志器"""
        return self.logger.create_task_logger(task_name)

    # ======================== 系统控制方法 ========================
    def start(self) -> None:
        """启动自动化系统"""
        with self.lock:
            if self.running:
                self.logger.info("系统已处于运行状态")
                return
            self.running = True
            self.should_stop = False  # 重置中断标志

        self.logger.info("BD2-AUTO 自动化系统已启动")
        print("BD2-AUTO 已启动")

    def stop(self) -> None:
        """停止自动化系统（清理资源）"""
        with self.lock:
            if not self.running:
                self.logger.info("系统已处于停止状态")
                return
            self.running = False
            self.should_stop = True  # 触发所有任务中断

        # 断开所有设备连接
        success, fail = self.device_manager.disconnect_all()
        self.logger.info(f"设备断开统计: 成功{success}个, 失败{fail}个")

        # 关闭日志线程池
        self.logger.shutdown()
        self.logger.info("BD2-AUTO 自动化系统已停止")
        print("BD2-AUTO 已停止")

    def get_status(self) -> dict:
        """获取系统完整状态——补充坐标转换器状态+修复设备URI显示"""
        active_device = self.device_manager.get_active_device()
        # 获取坐标转换器的当前状态（需CoordinateTransformer实现get_status方法，若未实现则返回基础信息）
        if hasattr(self.coord_transformer, 'get_status'):
            transformer_status = self.coord_transformer.get_status()
        else:
            transformer_status = {
                "original_base_res": self.coord_transformer._original_base_res,
                "current_client_size": self.coord_transformer._current_client_size,
                "current_dpi": self.coord_transformer._current_dpi
            }

        # 构建设备状态列表
        device_states = {}
        for uri, dev in self.device_manager.devices.items():
            device_states[uri] = {
                "state": dev.get_state().name,
                "is_connected": dev.is_connected,
                "client_size": dev.get_resolution() if dev.is_connected else None
            }

        status = {
            "system_running": self.running,
            "task_should_stop": self.check_should_stop(),
            "active_device": active_device.device_uri if (active_device and hasattr(active_device, 'device_uri')) else None,
            "active_device_state": active_device.get_state().name if active_device else None,
            "total_devices": len(self.device_manager),
            "device_list": list(self.device_manager.devices.keys()),
            "device_states": device_states,  # 详细设备状态
            "coordinate_transformer": transformer_status,  # 坐标转换器详细状态
            "base_resolution": self.base_resolution,
            "loaded_templates": len(self.image_processor.templates) if self.image_processor else 0,
            "last_error": self.last_error,
            "last_result": self.last_result
        }
        self.logger.debug(f"系统状态查询: {status}")
        return status

    # ======================== 核心操作方法 ========================
    def click(
        self,
        pos: Tuple[int, int],
        click_time: int = 1,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        is_base_coord: bool = False
    ) -> bool:
        """点击操作"""
        # 中断检查
        if self.check_should_stop():
            self.logger.info("点击任务被中断")
            self.last_result = False
            return False

        # 延迟预处理
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device:
            self.last_result = False
            return False

        # 执行点击（传客户区坐标）
        self.last_result = device.click(
            (pos[0], pos[1]), click_time=click_time, is_base_coord=is_base_coord)
        # 同步错误
        if not self.last_result:
            self.last_error = device.last_error or "点击执行失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            coord_type = "基准坐标" if is_base_coord else "客户区坐标"
            self.logger.info(f"点击成功: {coord_type}{pos} | 次数{click_time}")

        return self.last_result

    def key_press(
        self,
        key: str,
        duration: float = DEFAULT_KEY_DURATION,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """按键操作（带状态校验）"""
        if self.check_should_stop():
            self.logger.info("按键任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)

        # 执行按键
        self.last_result = device.key_press(key, duration=duration)
        if not self.last_result:
            self.last_error = device.last_error or f"按键 {key} 失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info(f"按键成功: {key} | 时长{duration}s")

        return self.last_result

    def template_click(
        self,
        template_name: str,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        duration: float = 0.1,
        click_time: int = 1,
        right_click: bool = False
    ) -> bool:
        """模板匹配点击"""
        if self.check_should_stop():
            self.logger.info("模板点击任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)

        self.last_result = device.click(
            pos=template_name,
            duration=duration,
            click_time=click_time,
            right_click=right_click
        )

        if not self.last_result:
            self.last_error = device.last_error or f"模板 {template_name} 点击失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info(f"模板点击成功: {template_name} | 右键={right_click}")

        return self.last_result

    def text_click(
        self,
        target_text: str,
        click: bool = True,
        lang: str = None,
        # 格式：(x, y, w, h)，基于 BASE_RESOLUTION 的绝对坐标
        roi: Optional[tuple] = None,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        duration: float = 0.1,
        click_time: int = 1,
        right_click: bool = False
    ) -> Optional[Tuple[int, int]]:
        """OCR文本识别并点击（支持ROI）"""
        if self.check_should_stop():
            self.logger.info("文本点击任务被中断")
            self.last_result = None
            return None

        self._apply_delay(delay)
        device = self._get_device(device_uri)

        # 截图（WindowsDevice.capture_screen 已返回客户区截图）
        screen = device.capture_screen()
        if screen is None:
            self.last_error = "文本点击失败: 截图失败"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = None
            return None

        # 处理ROI：调用坐标转换器转换基准ROI到客户区ROI（增强校验）
        region = None  # 最终传给find_text_position的区域（相对于当前客户区绝对坐标）
        if roi:
            try:
                # 步骤1：校验用户传入的roi格式和数值合法性
                if not isinstance(roi, (tuple, list)) or len(roi) != 4:
                    raise ValueError(
                        f"roi必须是4元组/列表（x, y, w, h），当前为{type(roi)}且长度{len(roi)}")
                rx, ry, rw, rh = roi
                if rx < 0 or ry < 0 or rw <= 0 or rh <= 0:
                    raise ValueError(
                        f"roi参数无效：x={rx}, y={ry}（需非负）；w={rw}, h={rh}（需正数）")

                # 步骤2：使用坐标转换器转换ROI
                region = self.coord_transformer.convert_original_rect_to_current_client(
                    roi)
                if not region or len(region) != 4:
                    raise ValueError("ROI转换后无效（可能超出客户区或尺寸为0）")
                rx2, ry2, rw2, rh2 = region
                if rx2 < 0 or ry2 < 0 or rw2 <= 0 or rh2 <= 0:
                    raise ValueError(f"转换后ROI无效：{region}（x/y需非负，w/h需正数）")

                self.logger.debug(
                    f"ROI转换完成 | 基准roi: {roi} → 当前客户区roi: {region}"
                )

            except ValueError as e:
                self.last_error = f"文本点击失败: ROI参数无效 - {str(e)}"
                self.logger.error(f"错误: {self.last_error}")
                self.last_result = None
                return None

        # 调用OCR识别（传入客户区截图+转换后的region，**启用预处理提高识别率**）
        text_pos = self.ocr_processor.find_text_position(
            image=screen,  # 客户区截图（无标题栏/边框）
            target_text=target_text,
            lang=lang,
            fuzzy_match=DEFAULT_TEXT_FUZZY_MATCH,
            region=region,  # 缩放后的当前客户区绝对坐标
            preprocess=False  # 不预处理
        )

        if not text_pos:
            self.last_error = f"文本点击失败: 未识别到文本 '{target_text}'"
            self.logger.warning(f"警告: {self.last_error}")
            self.last_result = None
            return None

        # 计算点击坐标（文本框中心，客户区绝对坐标）
        x, y, w, h = text_pos
        client_center_x = x + w // 2
        client_center_y = y + h // 2
        self.logger.info(
            f"识别到文本 '{target_text}' | 客户区坐标: ({x},{y},{w},{h}) | 中心: ({client_center_x},{client_center_y})"
        )

        if click:
            # 调用WindowsDevice.click（is_base_coord=False表示传入的是客户区坐标）
            click_result = device.click(
                pos=(client_center_x, client_center_y),
                duration=duration,
                click_time=click_time,
                right_click=right_click,
                is_base_coord=False  # 客户区坐标，无需再转换
            )

            if not click_result:
                self.last_error = device.last_error or "文本点击执行失败"
                self.logger.error(f"错误: {self.last_error}")
                return None
            return (client_center_x, client_center_y)  # 返回客户区坐标
        else:
            self.last_result = (client_center_x, client_center_y)
            return (client_center_x, client_center_y)

    # ======================== 窗口管理方法 ========================

    def minimize_window(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """最小化窗口"""
        if self.check_should_stop():
            self.logger.info("最小化窗口任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "最小化失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        self.last_result = device.minimize_window()
        if not self.last_result:
            self.last_error = device.last_error or "窗口最小化失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info("窗口最小化成功")

        return self.last_result

    def maximize_window(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """最大化窗口"""
        if self.check_should_stop():
            self.logger.info("最大化窗口任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "最大化失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        self.last_result = device.maximize_window()
        if not self.last_result:
            self.last_error = device.last_error or "窗口最大化失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info("窗口最大化成功")

        return self.last_result

    # ======================== 图像相关方法 ========================
    def check_element_exist(
        self,
        template_name: str,
        delay: float = DEFAULT_CHECK_ELEMENT_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """检查模板元素是否存在——修复返回值类型"""
        if self.check_should_stop():
            self.logger.info("检查元素任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "检查元素失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        try:
            # device.exists返回：存在则返回中心点坐标（Tuple），不存在则返回None
            result = device.exists(template_name)
            self.last_result = result

            if device.last_error:
                self.last_error = f"检查元素异常: {device.last_error}"
                self.logger.warning(f"警告: {self.last_error}")

            self.logger.info(f"元素 {template_name} 存在: {self.last_result}")
            return self.last_result
        except Exception as e:
            self.last_error = f"检查元素异常: {str(e)}"
            self.logger.error(f"错误: {self.last_error}", exc_info=True)
            self.last_result = False
            return False

    def screenshot(
        self,
        save_path: str = None,
        delay: float = DEFAULT_SCREENSHOT_DELAY,
        device_uri: str = None
    ) -> Optional[np.ndarray]:
        """截图并可选保存（删除冗余颜色转换+补充保存异常捕获）"""
        if self.check_should_stop():
            self.logger.info("截图任务被中断")
            self.last_result = None
            return None

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "截图失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = None
            return None

        try:
            # 执行截图（WindowsDevice.capture_screen 已返回 BGR 格式，无需转换）
            screen = device.capture_screen()
            self.last_result = screen

            if screen is None:
                self.last_error = "截图失败: 底层返回空图像"
                self.logger.error(f"错误: {self.last_error}")
                return None

            # 保存截图（如果指定路径，补充异常捕获）
            if save_path:
                try:
                    # 直接保存（screen 已为 BGR 格式，cv2.imwrite 兼容）
                    cv2.imwrite(save_path, screen)
                    self.logger.info(f"截图保存成功: {save_path}")
                except Exception as save_e:
                    self.last_error = f"截图保存失败: {str(save_e)}"
                    self.logger.error(f"错误: {self.last_error}")
                    # 保存失败不影响截图返回（仍返回图像数据）
            else:
                self.logger.info("截图成功（未保存）")

            return screen
        except Exception as e:
            self.last_error = f"截图异常: {str(e)}"
            self.logger.error(f"错误: {self.last_error}", exc_info=True)
            self.last_result = None
            return None

    def wait_element(
        self,
        template_name: str,
        timeout: float = DEFAULT_TASK_TIMEOUT,
        delay: float = DEFAULT_CHECK_ELEMENT_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """等待模板元素出现—"""
        if self.check_should_stop():
            self.logger.info("等待元素任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "等待元素失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        start_time = time.time()
        # device.wait 返回：超时返回None，成功返回中心点坐标（Tuple）
        center_pos = device.wait(template_name, timeout=timeout)
        self.last_result = center_pos

        if not self.last_result:
            # 同步device的错误信息
            self.last_error = device.last_error or f"等待 {template_name} 超时（{timeout}s）"
            self.logger.error(f"错误: {self.last_error}")
        else:
            # 计算实际等待耗时
            elapsed = time.time() - start_time
            self.logger.info(
                f"等待 {template_name} 成功（耗时{elapsed:.1f}s）| 中心点: {center_pos}"
            )

        return self.last_result

    def swipe(
        self,
        start_pos: tuple,
        end_pos: tuple,
        duration: float = 3,
        steps: int = 10,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        is_base_coord: bool = False
    ) -> bool:
        """滑动操作（支持基准坐标/客户区坐标）"""
        if self.check_should_stop():
            self.logger.info("滑动任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        # 校验坐标合法性
        if not (isinstance(start_pos, (tuple, list)) and len(start_pos) == 2):
            self.last_error = f"滑动失败: 起始坐标格式无效（{start_pos}）"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False
        if not (isinstance(end_pos, (tuple, list)) and len(end_pos) == 2):
            self.last_error = f"滑动失败: 结束坐标格式无效（{end_pos}）"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        # 执行滑动（device.swipe已通过CoordinateTransformer转换坐标）
        self.last_result = device.swipe(
            start_x=start_pos[0], start_y=start_pos[1],
            end_x=end_pos[0], end_y=end_pos[1],
            duration=duration,
            steps=steps,
            is_base_coord=is_base_coord
        )
        if not self.last_result:
            self.last_error = device.last_error or "滑动执行失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            coord_type = "基准坐标" if is_base_coord else "客户区坐标"
            self.logger.info(
                f"滑动成功: 从{start_pos}到{end_pos} | 类型:{coord_type} | 时长{duration}s"
            )

        return self.last_result

    def text_input(
        self,
        text: str,
        interval: float = 0.05,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """文本输入（优先粘贴，兼容逐字符输入）"""
        if self.check_should_stop():
            self.logger.info("文本输入任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "文本输入失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        # 执行输入
        self.last_result = device.text_input(text, interval=interval)
        if not self.last_result:
            self.last_error = device.last_error or f"输入文本 '{text}' 失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            log_text = text[:30] + "..." if len(text) > 30 else text
            self.logger.info(f"文本输入成功: {log_text}")

        return self.last_result
