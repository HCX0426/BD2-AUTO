import time
from typing import Optional

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

        # 确定最终使用的分辨率
        resolution = None
        if base_resolution is None:
            # 尝试从设备获取分辨率
            device = self.device_manager.get_active_device()
            if device and device.connected:
                resolution = device.get_resolution()

        # 初始化image_processor，优先级：设备分辨率 > 传入的分辨率 > 默认分辨率
        self.image_processor = ImageProcessor(
            resolution or base_resolution or (1920, 1080)
        )

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
            callback=callback  # 直接使用新的回调机制
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
            callback=callback
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

            # 保存截图用于调试
            cv2.imwrite("debug_screen.png", screen)
            print("[DEBUG] 截图已保存为 debug_screen.png")

            # 获取设备分辨率
            resolution = device.get_resolution()
            print(f"[DEBUG] 设备分辨率: {resolution}")

            # 匹配模板
            for attempt in range(max_retry):
                # 修改：处理 ImageProcessor.match_template 返回值
                pos, confidence = self.image_processor.match_template(
                    screen, template_name, resolution)
                print(
                    f"[DEBUG] 匹配尝试 {attempt+1}/{max_retry}, 位置: {pos}, 置信度: {confidence}")

                if pos:
                    print(f"[DEBUG] 准备点击位置: {pos}")
                    # 确保pos是(x,y)元组
                    if isinstance(pos, tuple) and len(pos) == 2:
                        # 添加点击前的延迟
                        time.sleep(0.5)
                        # 明确构造坐标元组
                        click_pos = (int(pos[0]), int(pos[1]))
                        success = device.click(click_pos)
                        print(f"[DEBUG] 点击结果: {'成功' if success else '失败'}")
                        return success
                    else:
                        print(f"[ERROR] 无效的坐标格式: {pos}")
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

    def add_text_click_task(self, target_text, lang="ch_sim", roi=None, max_retry=3, retry_interval=1, delay=0, device_uri=None):
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
        """执行文本点击任务(支持模糊匹配和正则表达式)"""
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
            # 捕获屏幕
            screen = device.capture_screen()
            if screen is None:
                print("[WARNING] 屏幕捕获失败")
                time.sleep(retry_interval)
                continue

            # 提取ROI区域(如果没有指定ROI则使用全屏)
            roi_screen = self.image_processor.get_roi_region(
                screen, roi) if roi else screen
            print(f"[DEBUG] ROI区域: {'自定义' if roi else '全屏'}")

            # 查找文本位置(支持模糊匹配和正则表达式)
            print(f"[DEBUG] 正在查找文本位置...")
            text_pos = self.ocr_processor.find_text_position(
                roi_screen,
                target_text,
                lang=lang,
                fuzzy_match=True
            )

            if text_pos:
                print(f"[DEBUG] 找到文本位置: {text_pos}")
                # 计算绝对坐标
                x, y, w, h = text_pos
                center_x = x + w // 2
                center_y = y + h // 2

                if roi and len(roi) >= 4:  # 确保roi是(x1,y1,x2,y2)
                    h, w = screen.shape[:2]
                    roi_x1 = int(w * roi[0])
                    roi_y1 = int(h * roi[1])
                    center_x += roi_x1
                    center_y += roi_y1

                # 确保坐标为整数类型
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
