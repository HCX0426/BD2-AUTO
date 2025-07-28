import logging
import time
from concurrent.futures import Future
from functools import wraps
from typing import Any, Callable, Optional

import cv2

# 导入配置文件
from .config.control__config import *
from .device_manager import DeviceManager
from .image_processor import ImageProcessor
from .logger import Logger
from .ocr_processor import OCRProcessor
from .task_executor import Task, TaskExecutor


class Auto:
    def __init__(
        self,
        base_resolution: tuple = None,
        ocr_engine: str = DEFAULT_OCR_ENGINE,
        device_uri: str = DEFAULT_DEVICE_URI
    ):
        self.device_manager = DeviceManager()
        self.ocr_processor = OCRProcessor(engine=ocr_engine)
        self.task_executor = TaskExecutor()
        self.running = False
        self.last_error: Optional[str] = None
        self.last_task: Optional[Task] = None
        self.default_device_uri = device_uri
        self.logger = Logger(
            task_name="System",
            base_log_dir=LOG_CONFIG["BASE_LOG_DIR"],
            log_file_prefix="system"
        )

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
                current_task = func(self, *args, **kwargs)
                prev_task = self.last_task
                self.last_task = current_task

                # 如果存在前置任务,添加依赖
                if prev_task and not prev_task.future.done():
                    def chain_tasks(future: Future) -> None:
                        try:
                            if future.exception() is None:
                                # 任务链正常执行
                                pass
                        except Exception as e:
                            print(f"[ERROR] 任务链执行失败: {str(e)}")
                    prev_task.future.add_done_callback(chain_tasks)

                return self
            except Exception as e:
                print(f"[ERROR] 方法调用失败 {func.__name__}: {str(e)}")
                return self
        return wrapper

    def _get_device(self, device_uri: Optional[str] = None):
        """获取设备实例，使用默认设备URI如果未提供"""
        return self.device_manager.get_device(
            device_uri or self.default_device_uri
        ) or self.device_manager.get_active_device()

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
        self.task_executor.start()
        print("BD2-AUTO 已启动")

    def stop(self) -> None:
        """停止自动化系统"""
        if not self.running:
            return
        self.running = False
        self.task_executor.stop()
        print("BD2-AUTO 已停止")

    def pause(self) -> None:
        """暂停自动化"""
        self.task_executor.pause()
        print("自动化已暂停")

    def resume(self) -> None:
        """恢复自动化"""
        self.task_executor.resume()
        print("自动化已恢复")

    def get_status(self) -> dict:
        """获取详细系统状态"""
        active_device = self.device_manager.get_active_device()
        return {
            "running": self.running,
            "active_device": active_device.device_uri if active_device else None,
            "devices": list(self.device_manager.devices.keys()),
            "tasks": self.task_executor.get_queue_size(),
            "templates": len(self.image_processor.templates),
            "last_error": self.last_error,
            "workers": self.task_executor.max_workers
        }

    # ======================== 任务执行方法 ========================

    @chainable
    def add_click_task(
        self,
        pos: tuple,
        is_relative: bool = False,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> Task:
        """添加点击任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_click, pos, is_relative, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_click(self, pos, is_relative, delay, device_uri):
        """执行点击任务（带重试逻辑）"""
        return self._execute_with_retry(
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
    ) -> Task:
        """添加按键任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_key, key, duration, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_key(self, key, duration, delay, device_uri):
        """执行按键任务（带重试）"""
        return self._execute_with_retry(
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
    ) -> Task:
        """添加模板点击任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_template_click, template_name, delay, max_retry, retry_interval, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_template_click(self, template_name, delay, max_retry, retry_interval, device_uri):
        """执行模板点击任务（内部重试）"""
        return self._execute_with_retry(
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

        # 速度快
        template = self.image_processor.get_template(template_name)
        if template is None:
            return False
        return device.click(template)

        # 以下为用CV的匹配
        # screen = device.capture_screen()
        # if screen is None:
        #     print("[ERROR] 屏幕捕获失败")
        #     return False

        # match_result = self.image_processor.match_template(screen, template_name)

        # if not match_result.position:
        #     print(f"[DEBUG] 未找到模板: {template_name}")
        #     return False

        # click_pos = tuple(map(int, match_result.position))

        # return device.click(click_pos)

    @chainable
    def add_text_click_task(
        self,
        target_text: str,
        lang: str = DEFAULT_OCR_LANG,
        roi: Optional[tuple] = None,
        max_retry: int = DEFAULT_MAX_RETRY,
        retry_interval: float = DEFAULT_RETRY_INTERVAL,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> Task:
        """添加点击文本任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_text_click, target_text, lang, roi, max_retry, retry_interval, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_text_click(self, target_text, lang, roi, max_retry, retry_interval, delay, device_uri):
        """执行文本点击任务（内部重试）"""
        return self._execute_with_retry(
            func=self._perform_text_click,
            task_name=f"文本点击[{target_text}]",
            max_retry=max_retry,
            retry_interval=retry_interval,
            target_text=target_text,
            lang=lang,
            roi=roi,
            delay=delay,
            device_uri=device_uri
        )

    def _perform_text_click(self, target_text, lang, roi, delay, device_uri):
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

        return device.click((int(center_x), int(center_y)))

    @chainable
    def add_ocr_task(
        self,
        lang: str = DEFAULT_OCR_LANG,
        roi: Optional[tuple] = None,
        delay: float = DEFAULT_CLICK_DELAY,
        device_uri: Optional[str] = None
    ) -> Task:
        """添加OCR任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_ocr, lang, roi, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_ocr(self, lang, roi, delay, device_uri):
        """执行OCR任务"""
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
    ) -> Task:
        """添加最小化窗口任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_minimize_window, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_minimize_window(self, delay, device_uri):
        """执行最小化窗口任务"""
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
    ) -> Task:
        """添加最大化窗口任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_maximize_window, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_maximize_window(self, delay, device_uri):
        """执行最大化窗口任务"""
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
    ) -> Task:
        """添加恢复窗口任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_restore_window, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_restore_window(self, delay, device_uri):
        """执行恢复窗口任务"""
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
    ) -> Task:
        """添加调整窗口大小任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_resize_window, width, height, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_resize_window(self, width: int, height: int, delay, device_uri):
        """执行调整窗口大小任务"""
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
    ) -> Task:
        """添加检查元素是否存在的任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_check_element_exist, template_name, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_check_element_exist(self, template_name, delay, device_uri):
        """执行检查元素是否存在的任务"""
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
    ) -> Task:
        """添加截图任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_screenshot, save_path, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_screenshot(self, save_path: str, delay: float, device_uri: str):
        """执行截图任务"""
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
    def add_wait_task(self, seconds: float) -> Task:
        """添加等待任务并返回Task对象"""
        return self.task_executor.add_task(
            time.sleep, seconds,
            timeout=seconds + 1  # 设置比等待时间稍长的超时
        )

    @chainable
    def add_custom_task(self, func: Callable, *args, **kwargs) -> Task:
        """添加自定义任务并返回Task对象"""
        return self.task_executor.add_task(
            func, *args, **kwargs,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    # ======================== 任务链控制方法 ========================

    def then(self, callback: Callable[[Any], Any]) -> "Auto":
        """添加任务完成后的回调"""
        if self.last_task and self.last_task.future:
            def wrapper(f: Future):
                if not f.exception():
                    try:
                        callback(f.result())
                    except Exception as e:
                        print(f"Then回调错误: {e}")
            self.last_task.future.add_done_callback(wrapper)
        return self

    def catch(self, error_handler: Callable[[Exception], Any]) -> "Auto":
        """添加错误处理回调"""
        if self.last_task and self.last_task.future:
            def wrapper(f: Future):
                if f.exception():
                    try:
                        error_handler(f.exception())
                    except Exception as e:
                        print(f"Catch处理错误: {e}")
            self.last_task.future.add_done_callback(wrapper)
        return self

    def wait(self, timeout: Optional[float] = None) -> Any:
        """等待任务完成并返回结果"""
        if self.last_task and self.last_task.future:
            try:
                return self.last_task.future.result(timeout=timeout)
            except Exception as e:
                self.last_error = f"等待任务超时: {str(e)}"
                return None
        return None

    def result(self, timeout: Optional[float] = None) -> Any:
        """获取上一个任务的结果（支持等待）"""
        # 确保 last_task 和 future 存在
        if not self.last_task or not self.last_task.future:
            print("[WARNING] 尝试获取结果但无有效任务")
            return None

        try:
            # 如果指定超时，等待任务完成
            if timeout is not None:
                return self.last_task.future.result(timeout=timeout)

            # 不指定超时，只返回已完成任务的结果
            if self.last_task.future.done():
                return self.last_task.future.result()

            print("[WARNING] 任务尚未完成")
            return None
        except TimeoutError:
            print("[WARNING] 获取结果超时")
            return None
        except Exception as e:
            print(f"[ERROR] 获取结果时出错: {str(e)}")
            return None

    def exception(self) -> Optional[Exception]:
        """获取上一个任务的异常"""
        return self.last_task.future.exception() if self.last_task and self.last_task.future.done() else None

    def get_task_id(self, task: Optional[Task] = None) -> Optional[str]:
        """获取任务ID"""
        # 如果没有指定任务，尝试获取最后一个任务
        if task is None:
            if self.last_task:
                return self.last_task.id
            return None

        # 如果指定了任务对象，直接返回其ID
        if isinstance(task, Task):
            return task.id

        # 如果传入的是任务ID字符串，直接返回
        if isinstance(task, str):
            return task

        return None

    def cancel_task(self, task_id: str) -> bool:
        """取消指定任务"""
        return self.task_executor.cancel_task(task_id)

    def adjust_task_priority(self, task_id: str, new_priority: int) -> bool:
        """调整任务优先级"""
        return self.task_executor.adjust_task_priority(task_id, new_priority)

    def get_task(self, task_id: str) -> Optional[Task]:
        """根据ID获取任务"""
        return self.task_executor.get_task(task_id)

    # ======================== 高级任务链方法 ========================

    def strict_sequence(self, *tasks: Callable[[], bool], timeout: Optional[float] = None) -> bool:
        """
        严格顺序执行任务链
        :param tasks: 任务函数列表，每个函数应返回bool表示成功与否
        :param timeout: 可选超时时间（秒）
        :return: 所有任务成功返回True，否则返回False
        """
        start_time = time.time()
        self.last_error = None  # 重置错误信息

        for task in tasks:
            # 检查超时
            if timeout and time.time() - start_time > timeout:
                self.last_error = "任务链执行超时"
                return False

            try:
                # 执行当前任务
                success = task()
                if not success:
                    # 保留已有的错误信息或设置默认错误
                    self.last_error = self.last_error or f"任务返回失败"
                    return False
            except Exception as e:
                self.last_error = f"任务执行异常: {str(e)}"
                return False

        return True

    def create_task(self, func: Callable, *args, **kwargs) -> Callable[[], bool]:
        """
        创建标准化任务函数
        :param func: 实际执行的任务函数
        :return: 返回一个无参数的可调用函数，执行成功返回True，失败返回False
        """
        def task_wrapper():
            try:
                # 执行任务并返回结果
                result = func(*args, **kwargs)

                # 处理不同类型的返回结果
                if isinstance(result, Future):
                    # 等待Future完成
                    try:
                        result = result.result(timeout=10)  # 设置合理的超时
                    except Exception as e:
                        self.last_error = f"任务等待超时或失败: {str(e)}"
                        return False

                # 检查结果是否为布尔值
                if isinstance(result, bool):
                    return result

                # 对于非布尔值的结果，我们将其视为成功
                return True
            except Exception as e:
                self.last_error = f"任务执行异常: {str(e)}"
                return False

        return task_wrapper

    def create_wait_task(self, seconds: float) -> Callable[[], bool]:
        """创建等待任务函数"""
        return self.create_task(lambda: self.add_wait_task(seconds))

    def create_key_task(self, key: str, duration: float = DEFAULT_KEY_DURATION, delay: float = 0,
                        device_uri: Optional[str] = None) -> Callable[[], bool]:
        """创建按键任务函数"""
        return self.create_task(lambda: self.add_key_task(key, duration, delay, device_uri))

    def create_click_task(self, pos: tuple, is_relative: bool = False, delay: float = 0,
                          device_uri: Optional[str] = None) -> Callable[[], bool]:
        """创建点击任务函数"""
        return self.create_task(lambda: self.add_click_task(pos, is_relative, delay, device_uri))

    def create_template_click_task(
        self,
        template_name: str,
        delay: float = 0,
        max_retry: int = DEFAULT_MAX_RETRY,
        retry_interval: float = DEFAULT_RETRY_INTERVAL,
        device_uri: Optional[str] = None
    ) -> Callable[[], bool]:
        """创建模板点击任务函数"""
        return self.create_task(
            lambda: self.add_template_click_task(
                template_name,
                delay=delay,
                max_retry=max_retry,
                retry_interval=retry_interval,
                device_uri=device_uri
            )
        )

    def create_text_click_task(
        self,
        target_text: str,
        lang: str = "ch_sim",
        roi: Optional[tuple] = None,
        max_retry: int = DEFAULT_MAX_RETRY,
        retry_interval: float = DEFAULT_RETRY_INTERVAL,
        delay: float = 0,
        device_uri: Optional[str] = None
    ) -> Callable[[], bool]:
        """创建文本点击任务函数"""
        return self.create_task(
            lambda: self.add_text_click_task(
                target_text,
                lang=lang,
                roi=roi,
                max_retry=max_retry,
                retry_interval=retry_interval,
                delay=delay,
                device_uri=device_uri
            )
        )

    def create_ocr_task(
        self,
        lang: str = "en",
        roi: Optional[tuple] = None,
        delay: float = 0,
        device_uri: Optional[str] = None
    ) -> Callable[[], bool]:
        """创建OCR识别任务函数"""
        return self.create_task(
            lambda: self.add_ocr_task(
                lang=lang,
                roi=roi,
                delay=delay,
                device_uri=device_uri
            )
        )

    def create_window_task(
        self,
        action: str,
        width: int = 0,
        height: int = 0,
        delay: float = 0,
        device_uri: Optional[str] = None
    ) -> Callable[[], bool]:
        """
        创建窗口操作任务函数
        :param action: 操作类型 ("minimize"/"maximize"/"restore"/"resize")
        """
        action_map = {
            "minimize": self.add_minimize_window_task,
            "maximize": self.add_maximize_window_task,
            "restore": self.add_restore_window_task,
            "resize": lambda d=0, du=None: self.add_resize_window_task(width, height, d, du)
        }

        if action not in action_map:
            raise ValueError(f"不支持的窗口操作: {action}")

        return self.create_task(
            lambda: action_map[action](delay=delay, device_uri=device_uri)
        )

    def create_check_element_task(
        self,
        template,
        delay: float = 0,
        device_uri: Optional[str] = None
    ) -> Callable[[], bool]:
        """创建检查元素存在任务函数"""
        return self.create_task(
            lambda: self.add_check_element_exist_task(
                template,
                delay=delay,
                device_uri=device_uri
            )
        )

    def create_screenshot_task(
        self,
        save_path: Optional[str] = None,
        delay: float = 0,
        device_uri: Optional[str] = None
    ) -> Callable[[], bool]:
        """创建截图任务函数"""
        return self.create_task(
            lambda: self.add_screenshot_task(
                save_path=save_path,
                delay=delay,
                device_uri=device_uri
            )
        )

    def create_retry_task(
        self,
        task_func: Callable[[], bool],
        max_retry: int = DEFAULT_MAX_RETRY,
        retry_interval: float = DEFAULT_RETRY_INTERVAL,
        delay: float = DEFAULT_CLICK_DELAY
    ) -> Callable[[], bool]:
        """
        创建带重试机制的任务函数包装器
        :param task_func: 原始任务函数
        :param max_retry: 最大重试次数
        :param retry_interval: 重试间隔(秒)
        :param delay: 初始延迟时间(秒)
        """
        def retry_wrapper() -> bool:
            self._apply_delay(delay)
            return self._execute_with_retry(
                func=task_func,
                task_name="自定义任务",
                max_retry=max_retry,
                retry_interval=retry_interval
            ) or False
        return retry_wrapper


    @chainable
    def add_wait_element_task(
        self,
        template_name: str,
        timeout: float = DEFAULT_TASK_TIMEOUT,
        delay: float = DEFAULT_CHECK_ELEMENT_DELAY,
        device_uri: Optional[str] = None
    ) -> Task:
        """添加等待元素出现的任务"""
        return self.task_executor.add_task(
            self._execute_wait_element, 
            template_name,
            timeout,
            delay,
            device_uri,
            timeout=timeout + 1  # 总超时稍长于等待时间
        )

    def _execute_wait_element(self, template_name, timeout, delay, device_uri):
        """执行等待元素操作"""
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
            max_retry=1,  # 内置已有重试机制
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
    ) -> Task:
        """添加滑动操作任务"""
        return self.task_executor.add_task(
            self._execute_swipe, start_pos, end_pos, duration, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_swipe(self, start_pos, end_pos, duration, delay, device_uri):
        """执行滑动操作"""
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
    ) -> Task:
        """添加文本输入任务"""
        return self.task_executor.add_task(
            self._execute_text_input, text, interval, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_text_input(self, text, interval, delay, device_uri):
        """执行文本输入"""
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
    ) -> Task:
        """添加移动窗口任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_move_window, x, y, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_move_window(self, x: int, y: int, delay, device_uri):
        """执行移动窗口任务"""
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
    ) -> Task:
        """添加重置窗口任务并返回Task对象"""
        return self.task_executor.add_task(
            self._execute_reset_window, delay, device_uri,
            timeout=DEFAULT_TASK_TIMEOUT
        )

    def _execute_reset_window(self, delay, device_uri):
        """执行重置窗口任务"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if not device:
            return False
        return device.reset_window()
    
    @chainable
    def add_sleep_task(
        self, 
        secs: float = 1.0,
        delay: float = 0,
        device_uri: Optional[str] = None
    ) -> Task:
        """添加带日志记录的睡眠任务
        
        Args:
            secs: 睡眠时长（秒）
            delay: 执行前延迟（秒）
            device_uri: 指定设备URI
        """
        return self.task_executor.add_task(
            self._execute_sleep,
            secs,
            delay,
            device_uri,
            timeout=secs + 1  # 设置比睡眠时间稍长的超时
        )

    def _execute_sleep(self, secs, delay, device_uri):
        """执行带设备状态的睡眠操作"""
        self._apply_delay(delay)
        device = self._get_device(device_uri)
        if device and device.connected:
            device.sleep(secs)
        else:
            time.sleep(secs)
        return True