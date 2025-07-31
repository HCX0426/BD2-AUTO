import logging
import time
from functools import wraps
from typing import Any, Callable, Optional

import cv2

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
        

    def chainable(func: Callable) -> Callable:
        """链式调用装饰器"""
        @wraps(func)
        def wrapper(self, *args, **kwargs) -> "Auto":
            try:
                # 执行原始方法
                func(self, *args, **kwargs)
                return self
            except Exception as e:
                print(f"[ERROR] 方法调用失败 {func.__name__}: {str(e)}")
                return self
        return wrapper

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
            time.sleep(delay)

    def _handle_task_exception(self, e: Exception, task_name: str):
        """统一处理任务异常"""
        self.last_error = f"{task_name}执行失败: {str(e)}"
        print(self.last_error)
        return False

    def _execute_with_retry(
        self,
        func: Callable,
        task_name: str,
        max_retry: int = DEFAULT_MAX_RETRY,
        retry_interval: float = DEFAULT_RETRY_INTERVAL,
        **kwargs
    ) -> Any:
        """内部重试机制封装"""
        for attempt in range(max_retry):
            try:
                result = func(**kwargs)
                if result is not None and result is not False:
                    return result
                print(f"[重试 {attempt+1}/{max_retry}] {task_name}")
            except Exception as e:
                print(f"[重试 {attempt+1}/{max_retry}] {task_name}异常: {str(e)}")

            if attempt < max_retry - 1:
                time.sleep(retry_interval)

        print(f"[ERROR] {task_name}超过最大重试次数")
        return None

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

    @chainable
    def add_click_task(
        self,
        pos: tuple,
        is_relative: bool = False,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加点击任务"""
        self._execute_with_retry(
            func=self._perform_click,
            task_name="点击操作",
            max_retry=DEFAULT_MAX_RETRY,
            retry_interval=DEFAULT_RETRY_INTERVAL,
            pos=pos,
            is_relative=is_relative,
            delay=delay,
            device_uri=device_uri
        )

    def _perform_click(self, pos, is_relative, delay, device_uri):
        """实际执行点击操作"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.connected:
            print("[ERROR] 点击失败: 设备未连接")
            return False

        resolution = device.get_resolution()
        if not resolution:
            print("[ERROR] 无法获取设备分辨率")
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
            return False

        return device.click(abs_pos)

    @chainable
    def add_key_task(
        self,
        key: str,
        duration: float = DEFAULT_KEY_DURATION,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加按键任务"""
        self._execute_with_retry(
            func=self._perform_key_press,
            task_name=f"按键[{key}]",
            max_retry=DEFAULT_MAX_RETRY,
            retry_interval=DEFAULT_RETRY_INTERVAL,
            key=key,
            duration=duration,
            delay=delay,
            device_uri=device_uri
        )

    def _perform_key_press(self, key, duration, delay, device_uri):
        """实际执行按键操作"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.connected:
            return False
        return device.key_press(key, duration)

    @chainable
    def add_template_click_task(
        self,
        template_name: str,
        delay: float = DEFAULT_CLICK_DELAY,
        max_retry: int = DEFAULT_MAX_RETRY,
        retry_interval: float = DEFAULT_RETRY_INTERVAL,
        device_uri: Optional[str] = None
    ) -> None:
        """添加模板点击任务"""
        self._execute_with_retry(
            func=self._perform_template_click,
            task_name=f"模板点击[{template_name}]",
            max_retry=max_retry,
            retry_interval=retry_interval,
            template_name=template_name,
            delay=delay,
            device_uri=device_uri
        )

    def _perform_template_click(self, template_name, delay, device_uri):
        """实际执行模板点击操作"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.connected or device.is_minimized():
            print("[ERROR] 模板点击失败: 设备不可用")
            return False

        template = self.image_processor.get_template(template_name)
        if template is None:
            return False
        return device.click(template)

    @chainable
    def add_text_click_task(
        self,
        target_text: str,
        click: bool = True,
        lang: str = DEFAULT_OCR_LANG,
        roi: Optional[tuple] = None,
        max_retry: int = DEFAULT_MAX_RETRY,
        retry_interval: float = DEFAULT_RETRY_INTERVAL,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加点击文本任务"""
        self._execute_with_retry(
            func=self._perform_text_click,
            task_name=f"文本点击[{target_text}]",
            max_retry=max_retry,
            retry_interval=retry_interval,
            target_text=target_text,
            click=click,
            lang=lang,
            roi=roi,
            delay=delay,
            device_uri=device_uri,
        )

    def _perform_text_click(self, target_text, click, lang, roi, delay, device_uri):
        """实际执行文本点击操作"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.connected:
            print("[ERROR] 文本点击失败: 设备未连接")
            return False

        screen = device.capture_screen()
        if screen is None:
            print("[WARNING] 屏幕捕获失败")
            return False

        roi_screen = self.image_processor.get_roi_region(
            screen, roi) if roi else screen
        text_pos = self.ocr_processor.find_text_position(
            roi_screen, target_text, lang=lang, fuzzy_match=DEFAULT_TEXT_FUZZY_MATCH
        )

        if not text_pos:
            return False

        x, y, w, h = text_pos
        center_x, center_y = x + w // 2, y + h // 2

        if roi and len(roi) >= 4:
            h, w = screen.shape[:2]
            center_x += int(w * roi[0])
            center_y += int(h * roi[1])

        if click:
            return device.click((int(center_x), int(center_y)))
        else:
            return (int(center_x), int(center_y))

    @chainable
    def add_ocr_task(
        self,
        lang: str = DEFAULT_OCR_LANG,
        roi: Optional[tuple] = None,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加OCR任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.connected:
            return False

        if not (screen := device.capture_screen()):
            return False

        if roi:
            screen = self.image_processor.get_roi_region(screen, roi)

        return self.ocr_processor.recognize_text(screen, lang=lang)

    @chainable
    def add_minimize_window_task(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加最小化窗口任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device:
            return False
        return device.minimize_window()

    @chainable
    def add_maximize_window_task(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加最大化窗口任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device:
            return False
        return device.maximize_window()

    @chainable
    def add_restore_window_task(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加恢复窗口任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device:
            return False
        return device.restore_window()

    @chainable
    def add_resize_window_task(
        self,
        width: int,
        height: int,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加调整窗口大小任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device:
            return False
        return device.resize_window(width, height)

    @chainable
    def add_check_element_exist_task(
        self,
        template_name: str,
        delay: float = DEFAULT_CHECK_ELEMENT_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """添加检查元素是否存在的任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device:
            return False
        try:
            template = self.image_processor.get_template(template_name)
            if template is None:
                return False
            return device.exists(template)
        except Exception as e:
            return self._handle_task_exception(e, "检查元素存在")

    @chainable
    def add_screenshot_task(
        self,
        save_path: str = None,
        delay: float = DEFAULT_SCREENSHOT_DELAY,
        device_uri: str = None
    ) -> None:
        """添加截图任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.connected:
            return None
        try:
            screenshot = device.capture_screen()
            if save_path and screenshot is not None:
                cv2.imwrite(save_path, screenshot)
            return screenshot
        except Exception as e:
            print(f"截图任务执行失败: {str(e)}")
            return None

    @chainable
    def add_wait_task(self, seconds: float) -> None:
        """添加等待任务"""
        time.sleep(seconds)

    @chainable
    def add_custom_task(self, func: Callable, *args, **kwargs) -> None:
        """添加自定义任务"""
        func(*args, **kwargs)

    # ======================== 高级任务方法 ========================

    def add_wait_element_task(
        self,
        template_name: str,
        timeout: float = DEFAULT_TASK_TIMEOUT,
        delay: float = DEFAULT_CHECK_ELEMENT_DELAY,
        device_uri: Optional[str] = None
    ) -> bool:
        """添加等待元素出现的任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device:
            return False

        template = self.image_processor.get_template(template_name)
        if not template:
            print(f"模板 {template_name} 未找到")
            return False

        return self._execute_with_retry(
            func=device.wait,
            task_name=f"等待元素[{template_name}]",
            max_retry=1,
            retry_interval=0,
            template=template,
            timeout=timeout
        )

    @chainable
    def add_swipe_task(
        self,
        start_pos: tuple,
        end_pos: tuple,
        duration: float = 0.5,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加滑动操作任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.connected:
            return False
        return device.swipe(start_pos[0], start_pos[1], end_pos[0], end_pos[1], duration)

    @chainable
    def add_text_input_task(
        self,
        text: str,
        interval: float = 0.05,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加文本输入任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device or not device.connected:
            return False
        return device.text_input(text, interval)

    @chainable
    def add_move_window_task(
        self,
        x: int,
        y: int,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加移动窗口任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device:
            return False
        return device.move_window(x, y)

    @chainable
    def add_reset_window_task(
        self,
        delay: float = DEFAULT_WINDOW_OPERATION_DELAY,
        device_uri: Optional[str] = None
    ) -> None:
        """添加重置窗口任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device:
            return False
        return device.reset_window()

    @chainable
    def add_sleep_task(
        self,
        secs: float = 1.0
    ) -> None:
        """添加睡眠任务"""
        time.sleep(secs)