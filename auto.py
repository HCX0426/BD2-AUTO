import time
from concurrent.futures import Future
from functools import wraps
from typing import Any, Callable, Optional, Tuple, Union

import cv2

from auto_control.device_manager import DeviceManager
from auto_control.image_processor import ImageProcessor
from auto_control.ocr_processor import OCRProcessor
from auto_control.task_executor import TaskExecutor


class Auto:
    def __init__(self, base_resolution: tuple = None, ocr_engine: str = "easyocr"):
        self.device_manager = DeviceManager()
        self.ocr_processor = OCRProcessor(engine=ocr_engine)
        self.task_executor = TaskExecutor(max_workers=5)
        self.running = False
        self.last_error: Optional[str] = None
        self.last_future: Optional[Future] = None

        # 确定最终使用的分辨率
        resolution = None
        if base_resolution is None:
            # 尝试从设备获取分辨率
            device = self.device_manager.get_active_device()
            if device and device.connected:
                resolution = device.get_resolution()

        # 初始化image_processor
        self.image_processor = ImageProcessor(
            resolution or base_resolution or (1920, 1080)
        )

    def chainable(func: Callable) -> Callable:
        """装饰器使方法支持链式调用"""
        @wraps(func)
        def wrapper(self, *args, **kwargs) -> "Auto":
            # 保存上一个future
            prev_future = self.last_future
            
            # 执行当前方法
            current_future = func(self, *args, **kwargs)
            self.last_future = current_future
            
            # 如果前一个future存在，设置依赖关系
            if prev_future and not prev_future.done():
                def dependency_callback(f):
                    if not f.exception():
                        return current_future
                    # 如果前一个任务失败，取消当前任务
                    if hasattr(current_future, 'id'):
                        self.task_executor.cancel_task(current_future.id)
                    return self
                prev_future.add_done_callback(dependency_callback)
            
            return self
        return wrapper
    
    def then(self, callback: Callable[[Any], Any]) -> "Auto":
        """添加任务完成后的回调"""
        if self.last_future:
            def wrapper(f: Future):
                if not f.exception():
                    try:
                        callback(f.result())
                    except Exception as e:
                        print(f"Then callback error: {e}")
            self.last_future.add_done_callback(wrapper)
        return self

    def catch(self, error_handler: Callable[[Exception], Any]) -> "Auto":
        """添加错误处理回调"""
        if self.last_future:
            def wrapper(f: Future):
                if f.exception():
                    try:
                        error_handler(f.exception())
                    except Exception as e:
                        print(f"Catch handler error: {e}")
            self.last_future.add_done_callback(wrapper)
        return self
    
    def wait(self, timeout: Optional[float] = None) -> "Auto":
        """等待当前任务完成（不抛出异常）"""
        if self.last_future:
            try:
                self.last_future.result(timeout=timeout)
            except Exception:
                pass  # 异常已经由catch处理，这里不再抛出
        return self
    
    def result(self) -> Any:
        """获取上一个任务的结果"""
        if self.last_future and self.last_future.done():
            return self.last_future.result()
        return None
    
    def exception(self) -> Optional[Exception]:
        """获取上一个任务的异常"""
        if self.last_future and self.last_future.done():
            return self.last_future.exception()
        return None

    def _update_resolution_from_device(self):
        """从活动设备获取分辨率并更新image_processor"""
        device = self.device_manager.get_active_device()
        if not device or not device.connected:
            self.last_error = "无活动设备或设备未连接，无法更新分辨率"
            return False
        resolution = device.get_resolution()
        if not resolution:
            self.last_error = "从设备获取分辨率失败"
            return False
        self.image_processor.update_resolution(resolution)
        return True

    @chainable
    def add_click_task(self, pos: tuple, is_relative: bool = True,
                       delay: float = 0, device_uri: Optional[str] = None) -> Future:
        """添加点击任务并返回Future"""
        return self.task_executor.add_task(
            self._execute_click,
            pos,
            is_relative,
            delay,
            device_uri
        )

    @chainable
    def add_ocr_task(self, lang: str = 'en',
                     roi: Optional[tuple] = None, delay: float = 0,
                     device_uri: Optional[str] = None) -> Future:
        """添加OCR任务并返回Future"""
        return self.task_executor.add_task(
            self._execute_ocr,
            lang,
            roi,
            delay,
            device_uri
        )

    def add_device(self, device_uri):
        """添加设备并自动更新分辨率"""
        try:
            success = self.device_manager.add_device(device_uri)
            if success:
                if not self._update_resolution_from_device():
                    self.last_error = f"设备 {device_uri} 添加成功，但分辨率更新失败"
            else:
                self.last_error = f"设备 {device_uri} 添加失败"
            return success
        except Exception as e:
            self.last_error = f"添加设备 {device_uri} 时发生异常: {str(e)}"
            return False

    def set_active_device(self, device_uri):
        """设置活动设备"""
        return self.device_manager.set_active_device(device_uri)

    def start(self):
        """启动自动化系统"""
        if self.running:
            return

        self.running = True
        self.task_executor.start()
        print("BD2-AUTO 已启动")

    def stop(self):
        """停止自动化系统"""
        self.running = False
        self.task_executor.stop()
        print("BD2-AUTO 已停止")

    def pause(self):
        """暂停自动化"""
        self.task_executor.pause()
        print("自动化已暂停")

    def resume(self):
        """恢复自动化"""
        self.task_executor.resume()
        print("自动化已恢复")

    def capture_screen(self):
        """捕获当前屏幕截图"""
        device = self.device_manager.get_active_device()
        if not device or not device.connected:
            return None
        return device.capture_screen()

    def _execute_click(self, pos, is_relative, delay, device_uri):
        """执行点击任务"""
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device or not device.connected:
            self.last_error = "设备未连接"
            return False

        # 转换坐标
        if is_relative:
            resolution = device.get_resolution()
            abs_pos = (
                int(pos[0] * resolution[0]),
                int(pos[1] * resolution[1])
            )
        else:
            abs_pos = pos

        return device.click(*abs_pos)

    @chainable
    def add_key_task(self, key, duration=0.1, delay=0, device_uri=None) -> Future:
        """添加按键任务并返回Future"""
        return self.task_executor.add_task(
            self._execute_key,
            key,
            duration,
            delay,
            device_uri
        )

    def _execute_key(self, key, duration, delay, device_uri):
        """执行按键任务"""
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device:
            return False

        return device.key_press(key, duration)

    @chainable
    def add_template_click_task(self, template_name, delay=0, max_retry=3, retry_interval=1, device_uri=None) -> Future:
        """添加模板点击任务并返回Future"""
        return self.task_executor.add_task(
            self._execute_template_click,
            template_name,
            delay,
            max_retry,
            retry_interval,
            device_uri
        )

    def _execute_template_click(self, template_name, delay, max_retry, retry_interval, device_uri):
        try:
            if delay > 0:
                time.sleep(delay)

            device = self._get_device(device_uri)
            if not device or not device.connected or device.is_minimized():
                return False

            # 获取屏幕截图
            screen = device.capture_screen()
            if screen is None:
                print("[DEBUG] 截图失败")
                self.last_error = "设备屏幕捕获失败"
                return False

            # 获取设备分辨率
            resolution = device.get_resolution()
            print(f"[DEBUG] 设备分辨率: {resolution}")

            # 匹配模板
            for attempt in range(max_retry):
                match_result = self.image_processor.match_template(
                    screen, template_name, resolution)
                print(
                    f"[DEBUG] 匹配尝试 {attempt+1}/{max_retry}, 位置: {match_result.position}, 置信度: {match_result.confidence}")

                if match_result.position:
                    print(f"[DEBUG] 准备点击位置: {match_result.position}")
                    if isinstance(match_result.position, tuple) and len(match_result.position) == 2:
                        time.sleep(0.5)
                        click_pos = (int(match_result.position[0]), int(
                            match_result.position[1]))
                        success = device.click(click_pos)
                        print(f"[DEBUG] 点击结果: {'成功' if success else '失败'}")
                        return success
                    else:
                        print(f"[ERROR] 无效的坐标格式: {match_result.position}")
                    return False

                time.sleep(retry_interval)

            self.last_error = f"模板点击任务重试{max_retry}次仍未找到匹配模板"
            return False
        except Exception as e:
            self.last_error = f"模板点击任务执行失败: {str(e)}"
            print("模板点击任务执行失败:", str(e))
            return False

    def _get_device(self, device_uri):
        """获取设备实例"""
        if device_uri:
            return self.device_manager.get_device(device_uri)
        return self.device_manager.get_active_device()

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

    def _execute_ocr(self, lang, roi, delay, device_uri):
        """执行OCR任务"""
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device or not device.connected:
            return False

        # 捕获屏幕
        screen = device.capture_screen()
        if screen is None:
            return False

        # 提取ROI区域
        if roi:
            screen = self.image_processor.get_roi_region(screen, roi)

        # 执行OCR
        return self.ocr_processor.recognize_text(screen, lang=lang)

    @chainable
    def add_text_click_task(self, target_text, lang="ch_sim", roi=None, max_retry=3, retry_interval=1, delay=0, device_uri=None) -> Future:
        """添加点击文本任务并返回Future"""
        return self.task_executor.add_task(
            self._execute_text_click,
            target_text,
            lang,
            roi,
            max_retry,
            retry_interval,
            delay,
            device_uri
        )

    def _execute_text_click(self, target_text, lang, roi, max_retry, retry_interval, delay, device_uri):
        """执行文本点击任务"""
        print(f"[DEBUG] 开始执行文本点击任务，目标文本: '{target_text}'")
        if delay > 0:
            print(f"[DEBUG] 等待延迟 {delay} 秒")
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device or not device.connected:
            print("[ERROR] 设备未连接或无效")
            return False

        for attempt in range(max_retry):
            print(f"[DEBUG] 尝试 {attempt + 1}/{max_retry}")
            screen = device.capture_screen()
            if screen is None:
                print("[WARNING] 屏幕捕获失败")
                time.sleep(retry_interval)
                continue

            roi_screen = self.image_processor.get_roi_region(
                screen, roi) if roi else screen
            print(f"[DEBUG] ROI区域: {'自定义' if roi else '全屏'}")

            print(f"[DEBUG] 正在查找文本位置...")
            text_pos = self.ocr_processor.find_text_position(
                roi_screen,
                target_text,
                lang=lang,
                fuzzy_match=True
            )

            if text_pos:
                print(f"[DEBUG] 找到文本位置: {text_pos}")
                x, y, w, h = text_pos
                center_x = x + w // 2
                center_y = y + h // 2

                if roi and len(roi) >= 4:
                    h, w = screen.shape[:2]
                    roi_x1 = int(w * roi[0])
                    roi_y1 = int(h * roi[1])
                    center_x += roi_x1
                    center_y += roi_y1

                center_x = int(center_x)
                center_y = int(center_y)
                click_pos = (center_x, center_y)
                print(f"[DEBUG] 准备点击坐标: {click_pos}")
                try:
                    device.click(click_pos)
                    print("[DEBUG] 点击完成")
                    return True
                except Exception as e:
                    print(f"点击操作失败: {e}")

            print(f"[DEBUG] 未找到文本，等待 {retry_interval} 秒后重试")
            time.sleep(retry_interval)

        print(f"[ERROR] 重试 {max_retry} 次后仍未找到文本")
        return False

    @chainable
    def add_minimize_window_task(self, delay=0, device_uri=None) -> Future:
        """添加最小化窗口任务并返回Future"""
        return self.task_executor.add_task(
            self._execute_minimize_window,
            delay,
            device_uri
        )

    def _execute_minimize_window(self, delay, device_uri):
        """执行最小化窗口任务"""
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device or not device.connected:
            print("[ERROR] 设备未连接或无效")
            return False

        try:
            return device.minimize_window()
        except Exception as e:
            print(f"最小化窗口任务执行失败: {str(e)}")
            return False

    @chainable
    def add_maximize_window_task(self, delay=0, device_uri=None) -> Future:
        """添加最大化窗口任务并返回Future"""
        return self.task_executor.add_task(
            self._execute_maximize_window,
            delay,
            device_uri
        )

    def _execute_maximize_window(self, delay, device_uri):
        """执行最大化窗口任务"""
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device or not device.connected:
            print("[ERROR] 设备未连接或无效")
            return False

        try:
            return device.maximize_window()
        except Exception as e:
            print(f"最大化窗口任务执行失败: {str(e)}")
            return False

    @chainable
    def add_restore_window_task(self, delay=0, device_uri=None) -> Future:
        """添加恢复窗口任务并返回Future"""
        return self.task_executor.add_task(
            self._execute_restore_window,
            delay,
            device_uri
        )

    def _execute_restore_window(self, delay, device_uri):
        """执行恢复窗口任务"""
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device or not device.connected:
            print("[ERROR] 设备未连接或无效")
            return False

        try:
            return device.restore_window()
        except Exception as e:
            print(f"恢复窗口任务执行失败: {str(e)}")
            return False

    @chainable
    def add_resize_window_task(self, width: int, height: int, delay=0, device_uri=None) -> Future:
        """添加调整窗口大小任务并返回Future"""
        return self.task_executor.add_task(
            self._execute_resize_window,
            width,
            height,
            delay,
            device_uri
        )

    def _execute_resize_window(self, width: int, height: int, delay, device_uri):
        """执行调整窗口大小任务"""
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device or not device.connected:
            print("[ERROR] 设备未连接或无效")
            return False

        try:
            return device.resize_window(width, height)
        except Exception as e:
            print(f"调整窗口大小任务执行失败: {str(e)}")
            return False

    @chainable
    def add_check_element_exist_task(self, template, delay=0, device_uri=None) -> Future:
        """添加检查元素是否存在的任务并返回Future"""
        return self.task_executor.add_task(
            self._execute_check_element_exist,
            template,
            delay,
            device_uri
        )

    def _execute_check_element_exist(self, template, delay, device_uri):
        """执行检查元素是否存在的任务"""
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device or not device.connected:
            print("[ERROR] 设备未连接或无效")
            return False

        try:
            return device.exists(template)
        except Exception as e:
            print(f"检查元素存在任务执行失败: {str(e)}")
            return False

    @chainable
    def add_screenshot_task(self, save_path: str = None, delay: float = 0, device_uri: str = None) -> Future:
        """添加截图任务并返回Future"""
        return self.task_executor.add_task(
            self._execute_screenshot,
            save_path,
            delay,
            device_uri
        )

    def _execute_screenshot(self, save_path: str, delay: float, device_uri: str):
        """执行截图任务"""
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device or not device.connected:
            print("[ERROR] 设备未连接或无效")
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
    def add_wait_task(self, seconds: float) -> Future:
        """添加等待任务并返回Future"""
        return self.task_executor.add_task(
            time.sleep,
            seconds
        )

    @chainable
    def add_custom_task(self, func: Callable, *args, **kwargs) -> Future:
        """添加自定义任务并返回Future"""
        return self.task_executor.add_task(
            func,
            *args,
            **kwargs
        )