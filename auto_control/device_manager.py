from typing import Dict, Optional
from .adb_device import ADBDevice
from .device_base import BaseDevice, DeviceState
from .windows_device import WindowsDevice


class DeviceManager:
    def __init__(self):
        self.devices: Dict[str, BaseDevice] = {}
        self.active_device: Optional[str] = None

    def add_device(self, device_uri: str, timeout: float = 10.0) -> bool:
        """
        添加设备(从URI自动判断设备类型)
        :param device_uri: 设备连接URI（支持大小写不敏感判断）
        :param timeout: 连接超时时间(秒)
        :return: 是否添加成功
        """
        # 兼容大小写
        lower_uri = device_uri.lower()
        
        # 修复1：大小写不敏感判断设备类型
        if lower_uri.startswith("windows://"):
            device_type = "windows"
        elif lower_uri.startswith(("android://", "adb://")):
            device_type = "adb"
        else:
            print(f"无法识别设备URI类型: {device_uri}（支持windows:///、android:///、adb:///）")
            return False

        # 避免重复添加
        if device_uri in self.devices:
            print(f"设备已存在: {device_uri}")
            return True

        try:
            # 创建设备实例
            if device_type == "windows":
                device = WindowsDevice(device_uri)
            elif device_type == "adb":
                device = ADBDevice(device_uri)
            else:
                raise ValueError(f"不支持的设备类型: {device_type}")

            # 连接设备
            if device.connect(timeout=timeout):
                self.devices[device_uri] = device
                # 自动将第一个设备设为活动设备
                if not self.active_device:
                    self.active_device = device_uri
                # print(f"设备添加成功: {device_uri}（状态：{device.get_state().name}）")
                return True
            else:
                # print(f"设备连接失败: {device_uri}（错误：{device.last_error}）")
                return False
        except Exception as e:
            print(f"添加设备异常: {str(e)}")
            return False

    def set_active_device(self, device_uri: str) -> bool:
        """设置活动设备（仅允许已连接的设备）"""
        if device_uri in self.devices:
            device = self.devices[device_uri]
            if device.is_connected:
                self.active_device = device_uri
                # print(f"活动设备已切换为: {device_uri}")
                return True
            else:
                # print(f"无法设置活动设备: {device_uri}（当前状态：{device.get_state().name}）")
                return False
        print(f"设备不存在: {device_uri}")
        return False

    def get_active_device(self) -> Optional[BaseDevice]:
        """获取当前活动设备"""
        if self.active_device and self.active_device in self.devices:
            device = self.devices[self.active_device]
            # print(f"获取活动设备: {self.active_device}（状态：{device.get_state().name}）")
            return device
        print("无活动设备")
        return None

    def get_device(self, device_uri: str) -> Optional[BaseDevice]:
        """获取指定设备"""
        device = self.devices.get(device_uri)
        # if device:
        #     print(f"获取设备: {device_uri}（状态：{device.get_state().name}）")
        # else:
        #     print(f"设备不存在: {device_uri}")
        return device

    def remove_device(self, device_uri: str) -> bool:
        """移除设备"""
        device = self.devices.get(device_uri)
        if not device:
            print(f"设备不存在: {device_uri}")
            return False

        try:
            # 断开设备连接
            disconnect_success = device.disconnect()
            if not disconnect_success:
                print(f"设备断开警告: {device_uri}（错误：{device.last_error}）")

            # 从列表中移除
            self.devices.pop(device_uri)
            print(f"设备已从列表移除: {device_uri}")

            # 切换活动设备
            if self.active_device == device_uri:
                if self.devices:
                    new_active = list(self.devices.keys())[0]
                    self.active_device = new_active
                    print(f"活动设备自动切换为: {new_active}")
                else:
                    self.active_device = None
                    print("无剩余设备，活动设备已清空")
            return True
        except Exception as e:
            print(f"移除设备异常: {str(e)}")
            return False

    def get_all_devices(self) -> Dict[str, BaseDevice]:
        """获取所有设备（含状态信息）"""
        device_info = {uri: dev.get_state().name for uri, dev in self.devices.items()}
        print(f"当前设备列表: {device_info}")
        return self.devices