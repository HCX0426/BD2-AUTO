import logging
import threading
import time
from typing import Optional, Tuple, Union

import cv2
import numpy as np

# 导入配置文件
from .config import (
    DEFAULT_OCR_ENGINE,
    DEFAULT_DEVICE_URI,
    DEFAULT_BASE_RESOLUTION,
    DEFAULT_CLICK_DELAY,
    DEFAULT_KEY_DURATION,
    DEFAULT_WINDOW_OPERATION_DELAY,
    DEFAULT_CHECK_ELEMENT_DELAY,
    DEFAULT_SCREENSHOT_DELAY,
    DEFAULT_TASK_TIMEOUT,
    DEFAULT_TEXT_FUZZY_MATCH,
    LOG_CONFIG
)
from .device_manager import DeviceManager
from .image_processor import ImageProcessor
from .logger import Logger
from .ocr_processor import OCRProcessor
from .device_base import BaseDevice, DeviceState
from airtest.core.api import Template


class Auto:
    def __init__(
        self,
        ocr_engine: str = DEFAULT_OCR_ENGINE,
        device_uri: str = DEFAULT_DEVICE_URI
    ):
        # 线程安全控制
        self.lock = threading.Lock()
        self.should_stop = False  # 任务中断标志
        self.running = False      # 系统运行状态

        # 核心模块初始化（传递日志实例）
        self.logger = Logger(
            task_name="System",
            base_log_dir=LOG_CONFIG["BASE_LOG_DIR"],
            log_file_prefix="system"
        )
        # 设备管理器初始化时传递日志实例
        self.device_manager = DeviceManager(logger=self.logger)
        self.ocr_processor = OCRProcessor(engine=ocr_engine, logger=self.logger)
        
        # 设备配置
        self.default_device_uri = device_uri
        self.base_resolution = None
        
        # 图像处理器
        self.image_processor = ImageProcessor(logger=self.logger)

        # 结果与错误追踪
        self.last_result = None    # 最后操作结果
        self.last_error = None     # 最后错误信息
        
        self.logger.info("Auto自动化系统初始化完成")

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
            self.logger.debug(
                f"使用设备: {target_uri or '活动设备'} | 状态: {device.get_state().name}"
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
        """设备睡眠（优先设备原生方法，支持中断）"""
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
            # 传递日志实例给DeviceManager
            result = self.device_manager.add_device(
                device_uri, 
                timeout=timeout,
                logger=self.logger  # 关键：将Auto的日志实例传递下去
            )
            self.last_result = result

            if result:
                # 关键优化：直接获取刚添加的设备，而非依赖活动设备
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
        """设置活动设备（仅允许已连接设备）"""
        result = self.device_manager.set_active_device(device_uri)
        self.last_result = result

        if not result:
            self.last_error = f"设置活动设备失败: {device_uri}"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info(f"活动设备已切换为: {device_uri}")
        
        return result

    def _update_resolution_from_device(self, max_retries: int = 3, retry_delay: float = 0.2) -> bool:
        """从活动设备更新基准分辨率（增加重试机制）"""
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

            # 获取设备分辨率（确保设备状态正常）
            if device.get_state() not in (DeviceState.CONNECTED, DeviceState.IDLE):
                if retry < max_retries - 1:
                    self.logger.debug(f"设备状态为{device.get_state().name}，等待就绪（第{retry+1}次）...")
                    time.sleep(retry_delay)
                    continue

            resolution = device.get_resolution()
            if not resolution or resolution == (0, 0):
                self.last_error = "获取分辨率无效: 分辨率为(0,0)"
                self.logger.error(f"错误: {self.last_error}")
                return False

            # 更新分辨率
            self.base_resolution = resolution
            self.image_processor.update_resolution(resolution)
            self.logger.info(f"基准分辨率已更新为: {resolution}")
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
        """获取系统完整状态"""
        active_device = self.device_manager.get_active_device()
        status = {
            "system_running": self.running,
            "task_should_stop": self.check_should_stop(),
            "active_device": active_device.device_uri if active_device else None,
            "active_device_state": active_device.get_state().name if active_device else None,
            "total_devices": len(self.device_manager),
            "device_list": list(self.device_manager.devices.keys()),
            "device_states": {
                uri: dev.get_state().name for uri, dev in self.device_manager.devices.items()
            },
            "base_resolution": self.base_resolution,
            "loaded_templates": len(self.image_processor.templates),
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
        """点击操作（支持绝对坐标，带状态校验）"""
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

        # 关键校验：设备必须可操作（CONNECTED/IDLE）
        if not device.is_operable:
            self.last_error = f"点击失败: 设备状态为 {device.get_state().name}（不可操作）"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        # 分辨率校验
        resolution = device.get_resolution()
        if not resolution or resolution == (0, 0):
            self.last_error = "点击失败: 无法获取设备分辨率"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False
        
        # 坐标边界检查
        abs_x, abs_y = round(pos[0]), round(pos[1])
        if (abs_x < 0 or abs_x >= resolution[0] or abs_y < 0 or abs_y >= resolution[1]):
            self.last_error = f"点击失败: 坐标({abs_x},{abs_y})超出分辨率{resolution}范围"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        # 执行点击
        self.last_result = device.click((abs_x, abs_y), click_time=click_time, is_base_coord=is_base_coord)
        # 同步错误
        if not self.last_result:
            self.last_error = device.last_error or "点击执行失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            coord_type = "基准坐标" if is_base_coord else "客户区坐标"
            self.logger.info(f"点击成功: {coord_type}({abs_x},{abs_y}) | 次数{click_time}")
        
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
        if not device or not device.is_operable:
            self.last_error = f"按键失败: 设备不可用（状态: {device.get_state().name if device else '无'}）"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

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
        """模板匹配点击（支持右键）"""
        if self.check_should_stop():
            self.logger.info("模板点击任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_operable or device.is_minimized():
            self.last_error = f"模板点击失败: 设备不可用（状态: {device.get_state().name if device else '无'}）"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        # 获取模板
        template = self.image_processor.get_template(template_name)
        if not template:
            self.last_error = f"模板点击失败: 未找到模板 {template_name}"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        # 执行模板点击
        self.last_result = device.click(template, duration=duration, click_time=click_time, right_click=right_click)
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
            roi: Optional[tuple] = None,  # 格式：(x, y, w, h)，基于 BASE_RESOLUTION 的绝对坐标
            delay: float = DEFAULT_CLICK_DELAY,
            device_uri: Optional[str] = None,
            duration: float = 0.1,
            click_time: int = 1,
            right_click: bool = False
        ) -> Optional[Tuple[int, int]]:
        """OCR文本识别并点击（支持基于基准绝对坐标的ROI，自动适配窗口大小）"""
        if self.check_should_stop():
            self.logger.info("文本点击任务被中断")
            self.last_result = None
            return None

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "文本点击失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = None
            return None

        # 1. 确保窗口/客户区信息最新（关键：获取当前客户区尺寸用于缩放）
        device._update_window_info()  # 强制更新客户区大小
        client_width, client_height = device._client_size
        base_width, base_height = device.BASE_RESOLUTION  # 从WindowsDevice获取基准分辨率（如1920x1080）
        
        # 校验客户区和基准分辨率有效性
        if client_width == 0 or client_height == 0:
            self.last_error = "文本点击失败: 客户区尺寸无效"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = None
            return None
        if base_width == 0 or base_height == 0:
            self.last_error = "文本点击失败: 基准分辨率未配置"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = None
            return None

        # 2. 计算缩放比例（当前客户区 / 基准分辨率）
        scale_x = client_width / base_width  # 水平缩放比例
        scale_y = client_height / base_height  # 垂直缩放比例
        self.logger.debug(
            f"ROI缩放参数 | 基准分辨率: {base_width}x{base_height} | "
            f"当前客户区: {client_width}x{client_height} | "
            f"缩放比例(x/y): {scale_x:.2f}/{scale_y:.2f}"
        )

        # 3. 截图（WindowsDevice.capture_screen 已返回客户区截图，无需处理非客户区）
        screen = device.capture_screen()
        if screen is None:
            self.last_error = "文本点击失败: 截图失败"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = None
            return None
        # 校验截图尺寸与客户区一致（避免缩放错误）
        screen_h, screen_w = screen.shape[:2]
        if not (abs(screen_w - client_width) < 2 and abs(screen_h - client_height) < 2):
            self.logger.warning(
                f"截图尺寸与客户区不匹配 | 截图: {screen_w}x{screen_h} | "
                f"客户区: {client_width}x{client_height} | 可能影响ROI精度"
            )

        # 4. 处理ROI：将基准绝对坐标转换为当前客户区的绝对坐标
        region = None  # 最终传给find_text_position的区域（当前客户区绝对坐标）
        if roi:
            try:
                # 步骤1：校验用户传入的roi格式
                if not isinstance(roi, (tuple, list)) or len(roi) != 4:
                    raise ValueError(f"roi必须是4元组/列表（x, y, w, h），当前为{type(roi)}且长度{len(roi)}")
                roi_x, roi_y, roi_w, roi_h = roi

                # 步骤2：校验基准roi的合法性（不超出基准分辨率，尺寸为正）
                if roi_x < 0 or roi_y < 0:
                    raise ValueError(f"roi坐标不能为负数 | 传入: ({roi_x}, {roi_y})")
                if roi_w <= 0 or roi_h <= 0:
                    raise ValueError(f"roi宽高必须为正数 | 传入: ({roi_w}, {roi_h})")
                if roi_x + roi_w > base_width or roi_y + roi_h > base_height:
                    raise ValueError(
                        f"roi超出基准分辨率范围 | 基准: {base_width}x{base_height} | "
                        f"roi终点: ({roi_x+roi_w}, {roi_y+roi_h})"
                    )

                # 步骤3：按当前客户区比例缩放roi（四舍五入为整数像素）
                scaled_x = int(round(roi_x * scale_x))
                scaled_y = int(round(roi_y * scale_y))
                scaled_w = int(round(roi_w * scale_x))
                scaled_h = int(round(roi_h * scale_y))

                # 步骤4：二次校验缩放后的region不超出当前客户区（避免裁剪错误）
                if scaled_x + scaled_w > client_width:
                    scaled_w = client_width - scaled_x  # 调整宽度，避免超出
                    self.logger.warning(f"缩放后roi宽度超出客户区，自动调整为{scaled_w}")
                if scaled_y + scaled_h > client_height:
                    scaled_h = client_height - scaled_y  # 调整高度，避免超出
                    self.logger.warning(f"缩放后roi高度超出客户区，自动调整为{scaled_h}")
                if scaled_w <= 0 or scaled_h <= 0:
                    raise ValueError(f"缩放后roi尺寸无效 | 缩放后: ({scaled_w}, {scaled_h})")

                # 最终region（当前客户区的绝对坐标）
                region = (scaled_x, scaled_y, scaled_w, scaled_h)
                self.logger.debug(
                    f"ROI转换完成 | 基准roi: {roi} → 当前客户区roi: {region}"
                )

            except ValueError as e:
                self.last_error = f"文本点击失败: ROI参数无效 - {str(e)}"
                self.logger.error(f"错误: {self.last_error}")
                self.last_result = None
                return None

        # 5. 调用改造后的find_text_position（传入客户区截图+缩放后的region）
        text_pos = self.ocr_processor.find_text_position(
            image=screen,  # 客户区截图（无标题栏/边框）
            target_text=target_text,
            lang=lang,
            fuzzy_match=DEFAULT_TEXT_FUZZY_MATCH,
            region=region  # 缩放后的当前客户区绝对坐标
        )

        if not text_pos:
            self.last_error = f"文本点击失败: 未识别到文本 '{target_text}'"
            self.logger.warning(f"警告: {self.last_error}")
            self.last_result = None
            return None

        # 6. 计算点击坐标（文本框中心，客户区绝对坐标）
        x, y, w, h = text_pos
        client_center_x = x + w // 2
        client_center_y = y + h // 2
        self.logger.info(
            f"识别到文本 '{target_text}' | 客户区坐标: ({x},{y},{w},{h}) | 中心: ({client_center_x},{client_center_y})"
        )

        # 7. 执行点击（调用WindowsDevice.click，直接传入客户区坐标）
        if click:
            # 校验设备可操作性
            if not device.is_operable:
                self.last_error = f"文本点击失败: 设备状态为 {device.get_state().name}"
                self.logger.error(f"错误: {self.last_error}")
                self.last_result = None
                return None

            # 调用WindowsDevice.click（is_base_coord=False表示传入的是客户区坐标）
            click_result = device.click(
                pos=(client_center_x, client_center_y),
                duration=duration,
                click_time=click_time,
                right_click=right_click,
                is_base_coord=False  # 关键：明确是客户区坐标，无需再转换
            )

            if not click_result:
                self.last_error = device.last_error or "文本点击执行失败"
                self.logger.error(f"错误: {self.last_error}")
                return None
            return (client_center_x, client_center_y)  # 返回客户区坐标
        else:
            self.last_result = (client_center_x, client_center_y)
            return (client_center_x, client_center_y)

    def ocr(
        self,
        lang: str = None,
        roi: Optional[tuple] = None,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> Optional[str]:
        """OCR文本识别"""
        if self.check_should_stop():
            self.logger.info("OCR任务被中断")
            self.last_result = None
            return None

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "OCR失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = None
            return None

        # 截图
        screen = device.capture_screen()
        if screen is None:
            self.last_error = "OCR失败: 截图失败"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = None
            return None

        # 处理ROI
        if roi:
            screen = self.image_processor.get_roi_region(screen, roi)

        # 执行OCR
        self.last_result = self.ocr_processor.recognize_text(screen, lang=lang)
        if self.last_result:
            self.logger.info(f"OCR识别成功: {self.last_result[:50]}...")  # 截断长文本
        else:
            self.last_error = "OCR识别失败: 未识别到文本"
            self.logger.warning(f"警告: {self.last_error}")
        
        return self.last_result

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

    def restore_window(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """恢复窗口（从最小化/最大化）"""
        if self.check_should_stop():
            self.logger.info("恢复窗口任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "恢复窗口失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        self.last_result = device.restore_window()
        if not self.last_result:
            self.last_error = device.last_error or "窗口恢复失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info("窗口恢复成功")
        
        return self.last_result

    def resize_window(
        self,
        width: int,
        height: int,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """调整窗口大小"""
        if self.check_should_stop():
            self.logger.info("调整窗口任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "调整窗口失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        self.last_result = device.resize_window(width, height)
        if not self.last_result:
            self.last_error = device.last_error or f"窗口调整为 {width}x{height} 失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info(f"窗口调整为 {width}x{height} 成功")
        
        return self.last_result

    def move_window(
        self,
        x: int,
        y: int,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """移动窗口到指定坐标"""
        if self.check_should_stop():
            self.logger.info("移动窗口任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "移动窗口失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        self.last_result = device.move_window(x, y)
        if not self.last_result:
            self.last_error = device.last_error or f"窗口移动到 ({x},{y}) 失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info(f"窗口移动到 ({x},{y}) 成功")
        
        return self.last_result

    def reset_window(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """重置窗口到初始位置和大小"""
        if self.check_should_stop():
            self.logger.info("重置窗口任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_connected:
            self.last_error = "重置窗口失败: 设备未连接"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        self.last_result = device.reset_window()
        if not self.last_result:
            self.last_error = device.last_error or "窗口重置失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info("窗口重置成功")
        
        return self.last_result

    # ======================== 图像相关方法 ========================
    def check_element_exist(
        self,
        template_name: str,
        delay: float = DEFAULT_CHECK_ELEMENT_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """检查模板元素是否存在"""
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
            # 获取模板
            template = self.image_processor.get_template(template_name)
            if not template:
                self.last_error = f"检查元素失败: 未找到模板 {template_name}"
                self.logger.error(f"错误: {self.last_error}")
                return False

            # 执行检查（适配改进后的device.exists）
            self.last_result = device.exists(template)
            # 同步错误
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
        """截图并可选保存（添加颜色通道兼容性处理）"""
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
            # 执行截图
            screen = device.capture_screen()
            self.last_result = screen

            if screen is None:
                self.last_error = "截图失败: 底层返回空图像"
                self.logger.error(f"错误: {self.last_error}")
                return None

            # 保存截图（如果指定路径）
            if save_path:
                # 颜色通道转换：RGB -> BGR（兼容cv2.imwrite）
                # 仅对3通道彩色图进行转换，单通道灰度图不处理
                if len(screen.shape) == 3 and screen.shape[2] == 3:
                    screen_bgr = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)
                else:
                    screen_bgr = screen  # 灰度图或其他格式直接保存
                
                # 保存转换后的图像
                cv2.imwrite(save_path, screen_bgr)
                self.logger.info(f"截图保存成功: {save_path}")
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
        """等待模板元素出现"""
        if self.check_should_stop():
            self.logger.info("等待元素任务被中断")
            self.last_result = False
            return False

        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.is_operable:
            self.last_error = f"等待元素失败: 设备不可用（状态: {device.get_state().name if device else '无'}）"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        # 获取模板
        template = self.image_processor.get_template(template_name)
        if not template:
            self.last_error = f"等待元素失败: 未找到模板 {template_name}"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        # 执行等待（适配改进后的device.wait）
        self.last_result = device.wait(template, timeout=timeout)
        if not self.last_result:
            self.last_error = device.last_error or f"等待 {template_name} 超时（{timeout}s）"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info(f"等待 {template_name} 成功（耗时{timeout}s内）")
        
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
        if not device or not device.is_operable:
            self.last_error = f"滑动失败: 设备不可用（状态: {device.get_state().name if device else '无'}）"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        # 执行滑动
        self.last_result = device.swipe(
            start_pos[0], start_pos[1],
            end_pos[0], end_pos[1],
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
        if not device or not device.is_operable:
            self.last_error = f"文本输入失败: 设备不可用（状态: {device.get_state().name if device else '无'}）"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

        # 执行输入（适配改进后的device.text_input）
        self.last_result = device.text_input(text, interval=interval)
        if not self.last_result:
            self.last_error = device.last_error or f"输入文本 '{text}' 失败"
            self.logger.error(f"错误: {self.last_error}")
        else:
            self.logger.info(f"文本输入成功: {text}")
        
        return self.last_result
    