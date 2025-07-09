import time
from typing import Optional

import cv2

from auto_control.device_manager import DeviceManager
from auto_control.image_processor import ImageProcessor
from auto_control.ocr_processor import OCRProcessor
from auto_control.task_executor import Task, TaskExecutor


class BD2Auto:
    def __init__(self, base_resolution: tuple = (1920, 1080), ocr_engine: str = "easyocr"):
        self.device_manager = DeviceManager()
        self.image_processor = ImageProcessor(base_resolution)
        self.ocr_processor = OCRProcessor(engine=ocr_engine)
        self.task_executor = TaskExecutor(max_workers=3)
        self.running = False
        self.last_error: Optional[str] = None

    def add_click_task(self, pos: tuple, is_relative: bool = True,
                       delay: float = 0, device_uri: Optional[str] = None,
                       callback: Optional[callable] = None) -> None:
        """添加点击任务(支持回调)"""
        self.task_executor.add_task(
            self._execute_click,
            pos,
            is_relative,
            delay,
            device_uri,
            callback=callback
        )

    def add_ocr_task(self, callback: callable, lang: str = 'en',
                     roi: Optional[tuple] = None, delay: float = 0,
                     device_uri: Optional[str] = None) -> None:
        """添加OCR任务(增强参数类型)"""
        self.task_executor.add_task(
            self._execute_ocr,
            callback,
            lang,
            roi,
            delay,
            device_uri,
            callback=lambda res, err: callback(res) if err is None else None
        )

    def add_device(self, device_uri, device_type='auto'):
        """添加设备"""
        return self.device_manager.add_device(device_uri, device_type)

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

    def add_click_task(self, pos, is_relative=True, delay=0, device_uri=None):
        """添加点击任务"""
        self.task_executor.add_task(
            self._execute_click,
            pos,
            is_relative,
            delay,
            device_uri
        )

    def _execute_click(self, pos, is_relative, delay, device_uri):
        """执行点击任务"""
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device:
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

    def add_key_task(self, key, duration=0.1, delay=0, device_uri=None):
        """添加按键任务"""
        self.task_executor.add_task(
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

    def add_template_click_task(self, template_name, delay=0, max_retry=3, retry_interval=1, device_uri=None):
        """添加模板点击任务"""
        self.task_executor.add_task(
            self._execute_template_click,
            template_name,
            delay,
            max_retry,
            retry_interval,
            device_uri
        )

    def _execute_template_click(self, template_name, delay, max_retry, retry_interval, device_uri):
        """执行模板点击任务"""
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device or not device.connected or device.is_minimized():
            return False

        # 获取屏幕截图
        screen = device.capture_screen()
        if screen is None:
            return False

        # 获取设备分辨率
        resolution = device.get_resolution()

        # 匹配模板
        for attempt in range(max_retry):
            pos = self.image_processor.match_template(
                screen,
                template_name,
                resolution
            )

            if pos:
                # 点击匹配位置
                return device.click(*pos)

            time.sleep(retry_interval)

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

    def add_ocr_task(self, callback, lang='en', roi=None, delay=0, device_uri=None):
        """
        添加OCR识别任务
        :param callback: 回调函数，接收识别结果
        :param lang: 语言
        :param roi: 感兴趣区域 (x1, y1, x2, y2) 0-1范围
        :param delay: 延迟执行时间
        :param device_uri: 指定设备
        """
        self.task_executor.add_task(
            self._execute_ocr,
            callback,
            lang,
            roi,
            delay,
            device_uri
        )

    def _execute_ocr(self, callback, lang, roi, delay, device_uri):
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
        result = self.ocr_processor.recognize_text(screen, lang=lang)

        # 调用回调
        callback(result)
        return True

    def add_text_click_task(self, target_text, lang='en', roi=None, max_retry=3, retry_interval=1, delay=0, device_uri=None):
        """
        添加点击文本任务
        :param target_text: 要点击的文本
        :param lang: 语言
        :param roi: 感兴趣区域
        :param max_retry: 最大重试次数
        :param retry_interval: 重试间隔
        :param delay: 延迟执行时间
        :param device_uri: 指定设备
        """
        self.task_executor.add_task(
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
        if delay > 0:
            time.sleep(delay)

        device = self._get_device(device_uri)
        if not device or not device.connected:
            return False

        for attempt in range(max_retry):
            # 捕获屏幕
            screen = device.capture_screen()
            if screen is None:
                time.sleep(retry_interval)
                continue

            # 提取ROI区域
            if roi:
                roi_screen = self.image_processor.get_roi_region(screen, roi)
            else:
                roi_screen = screen

            # 查找文本位置
            text_pos = self.ocr_processor.find_text_position(
                roi_screen, target_text, lang=lang)

            if text_pos:
                # 计算绝对坐标
                x, y, w, h = text_pos
                center_x = x + w // 2
                center_y = y + h // 2

                # 如果是ROI区域，需要调整坐标
                if roi:
                    h, w = screen.shape[:2]
                    roi_x1 = int(w * roi[0])
                    roi_y1 = int(h * roi[1])
                    center_x += roi_x1
                    center_y += roi_y1

                # 点击文本中心
                device.click(center_x, center_y)
                return True

            time.sleep(retry_interval)

        return False
