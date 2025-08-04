import logging
import time
from typing import Optional,Tuple

import cv2
import numpy as np

# 导入配置文件
from .config.control__config import *
from .device_manager import DeviceManager
from .image_processor import ImageProcessor
from .logger import Logger
from .ocr_processor import OCRProcessor

class Auto:
    def __init__(
        self,
        base_resolution: tuple = None,
        ocr_engine: str = DEFAULT_OCR_ENGINE,
        device_uri: str = DEFAULT_DEVICE_URI
    ):
        self.device_manager = DeviceManager()
        self.ocr_processor = OCRProcessor(engine=ocr_engine)
        self.running = False
        self.last_error: Optional[str] = None
        self.logger = Logger(
            task_name="System",
            base_log_dir=LOG_CONFIG["BASE_LOG_DIR"],
            log_file_prefix="system"
        )
        # 设置默认设备URI
        self.default_device_uri = device_uri

        # 确定最终使用的分辨率
        resolution = None
        if base_resolution is None and DEFAULT_RESOLUTION_UPDATE:
            device = self.device_manager.get_device(
                device_uri) if device_uri else self.device_manager.get_active_device()
            if device and device.connected:
                resolution = device.get_resolution()

        self.image_processor = ImageProcessor(
            resolution or base_resolution or DEFAULT_BASE_RESOLUTION
        )
        
        # 存储最后操作结果
        self.last_result = None

    def _get_device(self, device_uri: Optional[str] = None):
        """获取设备实例，使用默认设备URI如果未提供"""
        # 使用实例的default_device_uri作为默认值
        uri = device_uri or self.default_device_uri
        # 优先获取指定URI的设备
        device = self.device_manager.get_device(uri)
        # 如果未找到设备，尝试获取活动设备
        if not device:
            device = self.device_manager.get_active_device()
        return device

    def _apply_delay(self, delay: float):
        """应用任务延迟"""
        if delay > 0:
            self.sleep(delay)

    def sleep(self, secs: float = 1.0) -> bool:
        """设备睡眠"""
        device = self._get_device()
        if device:
            return device.sleep(secs)
        else:
            time.sleep(secs)
            return True

    # ======================== 设备管理方法 ========================

    def add_device(self, device_uri: str = DEFAULT_DEVICE_URI, timeout: float = 10.0) -> bool:
        """添加设备并自动更新分辨率"""
        try:
            if success := self.device_manager.add_device(device_uri, timeout=timeout):
                if not self._update_resolution_from_device():
                    self.last_error = f"设备 {device_uri} 添加成功，但分辨率更新失败"
                return success
            self.last_error = f"设备 {device_uri} 添加失败"
            return False
        except Exception as e:
            self.last_error = f"添加设备异常: {str(e)}"
            return False

    def set_active_device(self, device_uri: str) -> bool:
        """设置活动设备"""
        return self.device_manager.set_active_device(device_uri)

    def _update_resolution_from_device(self) -> bool:
        """从活动设备获取分辨率并更新image_processor"""
        device = self.device_manager.get_active_device()
        if not device or not device.connected:
            self.last_error = "无法更新分辨率: 设备未连接"
            return False
        if resolution := device.get_resolution():
            self.image_processor.update_resolution(resolution)
            return True
        self.last_error = "获取分辨率失败"
        return False

    def get_task_logger(self, task_name: str) -> logging.Logger:
        """获取任务专用日志记录器"""
        return self.logger.create_task_logger(task_name)

    # ======================== 系统控制方法 ========================

    def start(self) -> None:
        """启动自动化系统"""
        if self.running:
            return
        self.running = True
        print("BD2-AUTO 已启动")

    def stop(self) -> None:
        """停止自动化系统"""
        if not self.running:
            return
        self.running = False
        print("BD2-AUTO 已停止")

    def get_status(self) -> dict:
        """获取详细系统状态"""
        active_device = self.device_manager.get_active_device()
        return {
            "running": self.running,
            "active_device": active_device.device_uri if active_device else None,
            "devices": list(self.device_manager.devices.keys()),
            "templates": len(self.image_processor.templates),
            "last_error": self.last_error,
        }

    # ======================== 任务执行方法 ========================

    def click(
        self,
        pos: tuple,
        time: int = 1,
        is_relative: bool = False,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        convert_relative: bool = False
    ) -> bool:
        """执行点击操作"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.connected:
            print("[ERROR] 点击失败: 设备未连接")
            self.last_result = False
            return False

        resolution = device.get_resolution()
        if not resolution:
            print("[ERROR] 无法获取设备分辨率")
            self.last_result = False
            return False

        # 坐标转换逻辑
        if is_relative:
            abs_pos = (int(pos[0] * resolution[0]),
                       int(pos[1] * resolution[1]))
        else:
            abs_pos = (round(pos[0]), round(pos[1]))

        # 坐标边界检查
        if (abs_pos[0] < 0 or abs_pos[0] >= resolution[0] or
                abs_pos[1] < 0 or abs_pos[1] >= resolution[1]):
            print(f"[ERROR] 坐标超出屏幕范围: {abs_pos}, 屏幕分辨率: {resolution}")
            self.last_result = False
            return False

        self.last_result = device.click(abs_pos,time=time,convert_relative=convert_relative)
        return self.last_result

    def key_press(
        self,
        key: str,
        duration: float = DEFAULT_KEY_DURATION,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """执行按键操作"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.connected:
            self.last_result = False
            return False
        
        self.last_result = device.key_press(key, duration)
        return self.last_result

    def template_click(
        self,
        template_name: str,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        duration: float = 0.1,  # 新增参数
        time: int = 1,           # 新增参数
        right_click: bool = False  # 新增参数
    ) -> bool:
        """执行模板点击操作"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.connected or device.is_minimized():
            print("[ERROR] 模板点击失败: 设备不可用")
            self.last_result = False
            return False

        template = self.image_processor.get_template(template_name)
        if template is None:
            self.last_result = False
            return False
            
        self.last_result = device.click(template, duration, time, right_click)
        return self.last_result

    def text_click(
        self,
        target_text: str,
        click: bool = True,
        lang: str = DEFAULT_OCR_LANG,
        roi: Optional[tuple] = None,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        duration: float = 0.1,
        time: int = 1,
        right_click: bool = False
    ) -> Optional[Tuple[int, int]]:
        """执行文本点击操作"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = None
        
        if not device or not device.connected:
            print("[ERROR] 文本点击失败: 设备未连接")
            return None

        screen = device.capture_screen()
        if screen is None:
            print("[WARNING] 屏幕捕获失败")
            return None

        roi_screen = self.image_processor.get_roi_region(
            screen, roi) if roi else screen
        text_pos = self.ocr_processor.find_text_position(
            roi_screen, target_text, lang=lang, fuzzy_match=DEFAULT_TEXT_FUZZY_MATCH
        )

        if not text_pos:
            return None

        x, y, w, h = text_pos
        center_x, center_y = x + w // 2, y + h // 2

        if roi and len(roi) >= 4:
            screen_h, screen_w = screen.shape[:2]
            roi_x1 = int(screen_w * roi[0])
            roi_y1 = int(screen_h * roi[1])
            center_x += roi_x1
            center_y += roi_y1

        if click:
            self.last_result = device.click((int(center_x), int(center_y)), duration, time, right_click)
            return self.last_result
        else:
            self.last_result = (int(center_x), int(center_y))
            return self.last_result

    def ocr(
        self,
        lang: str = DEFAULT_OCR_LANG,
        roi: Optional[tuple] = None,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> Optional[str]:
        """执行OCR任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = None
        
        if not device or not device.connected:
            return None

        if not (screen := device.capture_screen()):
            return None

        if roi:
            screen = self.image_processor.get_roi_region(screen, roi)

        self.last_result = self.ocr_processor.recognize_text(screen, lang=lang)
        return self.last_result

    def minimize_window(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """最小化窗口"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = False
        
        if not device:
            return False
            
        self.last_result = device.minimize_window()
        return self.last_result

    def maximize_window(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """最大化窗口"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = False
        
        if not device:
            return False
            
        self.last_result = device.maximize_window()
        return self.last_result

    def restore_window(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """恢复窗口"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = False
        
        if not device:
            return False
            
        self.last_result = device.restore_window()
        return self.last_result

    def resize_window(
        self,
        width: int,
        height: int,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """调整窗口大小"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = False
        
        if not device:
            return False
            
        self.last_result = device.resize_window(width, height)
        return self.last_result

    def check_element_exist(
        self,
        template_name: str,
        delay: float = DEFAULT_CHECK_ELEMENT_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """检查元素是否存在"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = False
        
        if not device:
            return False

        try:
            template = self.image_processor.get_template(template_name)
            if template is None:
                return False

            self.last_result = device.exists(template)
            return self.last_result
        except Exception as e:
            print(f"检查元素存在失败: {str(e)}")
            return False

    def screenshot(
        self,
        save_path: str = None,
        delay: float = DEFAULT_SCREENSHOT_DELAY,
        device_uri: str = None
    ) -> Optional[np.ndarray]:
        """执行截图任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = None
        
        if not device or not device.connected:
            return None
        try:
            screenshot = device.capture_screen()
            if save_path and screenshot is not None:
                cv2.imwrite(save_path, screenshot)
            self.last_result = screenshot
            return screenshot
        except Exception as e:
            print(f"截图任务执行失败: {str(e)}")
            return None

    def wait_element(
        self,
        template_name: str,
        timeout: float = DEFAULT_TASK_TIMEOUT,
        delay: float = DEFAULT_CHECK_ELEMENT_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """等待元素出现"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = False
        
        if not device:
            return False

        template = self.image_processor.get_template(template_name)
        if not template:
            print(f"模板 {template_name} 未找到")
            return False

        self.last_result = device.wait(template, timeout=timeout)
        return self.last_result

    def swipe(
        self,
        start_pos: tuple,
        end_pos: tuple,
        duration: float = 3,
        steps: int = 1,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None,
        convert_relative: bool = False
    ) -> bool:
        """执行滑动操作"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = False
        
        if not device or not device.connected:
            return False
            
        self.last_result = device.swipe(
            start_pos[0], start_pos[1], 
            end_pos[0], end_pos[1], 
            duration,
            steps,
            convert_relative=convert_relative
        )
        return self.last_result

    def text_input(
        self,
        text: str,
        interval: float = 0.05,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """执行文本输入"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = False
        
        if not device or not device.connected:
            return False
            
        self.last_result = device.text_input(text, interval)
        return self.last_result

    def move_window(
        self,
        x: int,
        y: int,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """移动窗口"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = False
        
        if not device:
            return False
            
        self.last_result = device.move_window(x, y)
        return self.last_result

    def reset_window(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """重置窗口"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        self.last_result = False
        
        if not device:
            return False
            
        self.last_result = device.reset_window()
        return self.last_result