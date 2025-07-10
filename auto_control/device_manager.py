from typing import Dict, Optional

from .adb_device import ADBDevice
from .device_base import BaseDevice
from .windows_device import WindowsDevice


class DeviceManager:
    def __init__(self):
        self.devices: Dict[str, BaseDevice] = {}
        self.active_device: Optional[str] = None

    def add_device(self, device_uri: str, timeout: float = 10.0) -> bool:
        """
        添加设备(从URI自动判断设备类型)
        :param device_uri: 设备连接URI
        :param timeout: 连接超时时间(秒)
        :return: 是否添加成功
        """
        # 自动检测设备类型
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
        if device.connect(timeout=timeout):
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

    def get_active_device(self) -> Optional[BaseDevice]:
        """获取当前活动设备"""
        if self.active_device:
            return self.devices.get(self.active_device)
        return None

    def get_device(self, device_uri):
        """获取指定设备"""
        return self.devices.get(device_uri)

    def remove_device(self, device_uri: str) -> bool:
        """移除设备"""
        device = self.devices.get(device_uri)
        if device:
            if not device.disconnect():
                print(f"设备 {device_uri} 断开连接失败")
            if device_uri in self.devices:
                device = self.devices.pop(device_uri)
                device.disconnect()
                if self.active_device == device_uri:
                    if self.devices:
                        self.active_device = list(self.devices.keys())[0]
                    else:
                        self.active_device = None
                return True
            return False
        return False
