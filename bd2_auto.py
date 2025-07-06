from .auto_control.device_manager import DeviceManager
from .auto_control.image_processor import ImageProcessor
from .auto_control.task_executor import TaskExecutor
import time

class BD2Auto:
    def __init__(self, base_resolution=(1920, 1080)):
        # 初始化核心模块
        self.device_manager = DeviceManager()
        self.image_processor = ImageProcessor(base_resolution)
        self.task_executor = TaskExecutor(max_workers=3)
        self.running = False
        
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
        
    def get_status(self):
        """获取系统状态"""
        active_device = self.device_manager.get_active_device()
        return {
            "running": self.running,
            "active_device": active_device.device_uri if active_device else None,
            "devices": list(self.device_manager.devices.keys()),
            "tasks": self.task_executor.get_queue_size(),
            "templates": len(self.image_processor.templates)
        }