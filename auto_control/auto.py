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

        # 核心模块初始化
        self.device_manager = DeviceManager()
        self.ocr_processor = OCRProcessor(engine=ocr_engine)
        self.logger = Logger(
            task_name="System",
            base_log_dir=LOG_CONFIG["BASE_LOG_DIR"],
            log_file_prefix="system"
        )

        # 设备配置
        self.default_device_uri = device_uri
        self.base_resolution = None
        
        # 图像处理器
        self.image_processor = ImageProcessor()

        # 结果与错误追踪
        self.last_result = None    # 最后操作结果
        self.last_error = None     # 最后错误信息

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
            # 调用DeviceManager添加设备
            result = self.device_manager.add_device(device_uri, timeout=timeout)
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
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

    def set_active_device(self, device_uri: str) -> bool:
        """设置活动设备（仅允许已连接设备）"""
        result = self.device_manager.set_active_device(device_uri)
        self.last_result = result

        if not result:
            self.last_error = f"设置活动设备失败: {device_uri}"
            self.logger.error(f"错误: {self.last_error}")
        
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
        for uri, device in self.device_manager.get_all_devices().items():
            if device.is_connected:
                device.disconnect()
                self.logger.info(f"设备 {uri} 已断开连接")

        # 关闭日志线程池
        self.logger.shutdown()
        self.logger.info("BD2-AUTO 自动化系统已停止")
        print("BD2-AUTO 已停止")

    def get_status(self) -> dict:
        """获取系统完整状态"""
        active_device = self.device_manager.get_active_device()
        return {
            "system_running": self.running,
            "task_should_stop": self.check_should_stop(),
            "active_device": active_device.device_uri if active_device else None,
            "active_device_state": active_device.get_state().name if active_device else None,
            "total_devices": len(self.device_manager.devices),
            "device_list": list(self.device_manager.devices.keys()),
            "device_states": {
                uri: dev.get_state().name for uri, dev in self.device_manager.devices.items()
            },
            "base_resolution": self.base_resolution,
            "loaded_templates": len(self.image_processor.templates),
            "last_error": self.last_error,
            "last_result": self.last_result
        }

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
            self.logger.info(f"点击成功: 坐标({abs_x},{abs_y}) | 次数{click_time}")
        
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
        roi: Optional[tuple] = None,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        duration: float = 0.1,
        click_time: int = 1,
        right_click: bool = False
    ) -> Optional[Tuple[int, int]]:
        """OCR文本识别并点击（自动适配窗口大小）"""
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

        # 1. 获取窗口信息
        window_w, window_h = device.resolution
        if window_w == 0 or window_h == 0:
            self.last_error = "文本点击失败: 窗口分辨率无效"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = None
            return None

        # 2. 截图
        screen = device.capture_screen()
        if screen is None:
            self.last_error = "文本点击失败: 截图失败"
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = None
            return None

        # 3. OCR识别
        screen_h, screen_w = screen.shape[:2]
        # 处理ROI区域
        roi_screen = self.image_processor.get_roi_region(screen, roi) if roi else screen
        text_pos = self.ocr_processor.find_text_position(
            roi_screen, target_text, lang=lang, fuzzy_match=DEFAULT_TEXT_FUZZY_MATCH
        )

        if not text_pos:
            self.last_error = f"文本点击失败: 未识别到文本 '{target_text}'"
            self.logger.warning(f"警告: {self.last_error}")
            self.last_result = None
            return None

        # 4. 计算点击坐标（中心位置）
        x, y, w, h = text_pos
        center_x, center_y = x + w // 2, y + h // 2

        # 修正ROI偏移
        if roi and len(roi) >= 4:
            roi_x1 = int(screen_w * roi[0])
            roi_y1 = int(screen_h * roi[1])
            center_x += roi_x1
            center_y += roi_y1

        # 5. 执行点击（如果需要）
        final_x, final_y = int(center_x), int(center_y)
        self.logger.info(f"识别到文本 '{target_text}' 坐标: ({final_x},{final_y})")

        if click:
            # 校验设备可操作性
            if not device.is_operable:
                self.last_error = f"文本点击失败: 设备状态为 {device.get_state().name}"
                self.logger.error(f"错误: {self.last_error}")
                self.last_result = None
                return None

            # 执行点击
            self.last_result = device.click((final_x, final_y), duration=duration, click_time=click_time, right_click=right_click)
            if not self.last_result:
                self.last_error = device.last_error or "文本点击执行失败"
                self.logger.error(f"错误: {self.last_error}")
                return None
            return (final_x, final_y)
        else:
            self.last_result = (final_x, final_y)
            return (final_x, final_y)

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
            self.logger.info(f"OCR识别成功: {self.last_result}")
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
            self.logger.error(f"错误: {self.last_error}")
            self.last_result = False
            return False

    def screenshot(
        self,
        save_path: str = None,
        delay: float = DEFAULT_SCREENSHOT_DELAY,
        device_uri: str = None
    ) -> Optional[np.ndarray]:
        """截图并可选保存"""
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
            # 执行截图（适配改进后的device.capture_screen）
            screen = device.capture_screen()
            self.last_result = screen

            if screen is None:
                self.last_error = "截图失败: 未获取到图像数据"
                self.logger.error(f"错误: {self.last_error}")
                return None

            # 保存截图（如果指定路径）
            if save_path:
                cv2.imwrite(save_path, screen)
                self.logger.info(f"截图保存成功: {save_path}")
            else:
                self.logger.info("截图成功（未保存）")
            
            return screen
        except Exception as e:
            self.last_error = f"截图异常: {str(e)}"
            self.logger.error(f"错误: {self.last_error}")
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

        # 执行滑动（适配改进后的device.swipe）
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
