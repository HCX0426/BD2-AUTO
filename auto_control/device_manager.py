from .windows_device import WindowsDevice
from .adb_device import ADBDevice
from .device_base import BaseDevice

class DeviceManager:
    def __init__(self):
        self.devices = {}
        self.active_device = None
        
    def add_device(self, device_uri, device_type='auto'):
        """
        添加设备
        :param device_uri: 设备连接URI
        :param device_type: 设备类型 (windows, adb, auto)
        """
        # 自动检测设备类型
        if device_type == 'auto':
            if 'Windows' in device_uri:
                device_type = 'windows'
            elif 'Android' in device_uri:
                device_type = 'adb'
            else:
                raise ValueError("无法自动识别设备类型")
        
        # 创建设备实例
        if device_type == 'windows':
            device = WindowsDevice(device_uri)
        elif device_type == 'adb':
            device = ADBDevice(device_uri)
        else:
            raise ValueError(f"不支持的设备类型: {device_type}")
        
        # 连接设备
        if device.connect():
            self.devices[device_uri] = device
            if not self.active_device:
                self.active_device = device_uri
            return True
        return False
        
    def set_active_device(self, device_uri):
        """设置活动设备"""
        if device_uri in self.devices:
            self.active_device = device_uri
            return True
        return False
        
    def get_active_device(self):
        """获取当前活动设备"""
        if self.active_device:
            return self.devices[self.active_device]
        return None
        
    def get_device(self, device_uri):
        """获取指定设备"""
        return self.devices.get(device_uri)
        
    def remove_device(self, device_uri):
        """移除设备"""
        if device_uri in self.devices:
            device = self.devices.pop(device_uri)
            device.disconnect()
            if self.active_device == device_uri:
                self.active_device = list(self.devices.keys())[0] if self.devices else None
            return True
        return False