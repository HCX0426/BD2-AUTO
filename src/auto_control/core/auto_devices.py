"""设备模块：包含设备获取、坐标转换、设备管理相关方法"""

import time
from typing import Any, Optional, Tuple, Union

from .auto_base import AutoConfig, AutoResult, CoordinateError, DeviceError
from .auto_utils import LogFormatter


class DeviceHandler:
    """设备操作处理器（封装设备相关核心逻辑）"""

    def __init__(self, auto_instance, config: AutoConfig):
        self.auto = auto_instance
        self.config = config
        self.logger = auto_instance.logger
        self.coord_transformer = auto_instance.coord_transformer
        self.device_manager = auto_instance.device_manager

    def get_device(self, device_uri: Optional[str] = None) -> Any:
        """获取设备实例（封装设备查找逻辑）"""
        target_uri = device_uri or self.config.DEFAULT_DEVICE_URI
        device = self.device_manager.get_device(target_uri) or self.device_manager.get_active_device()

        if device:
            dev_uri = getattr(device, "device_uri", "未知URI")
            self.logger.debug(f"使用设备: {dev_uri}")
            return device

        raise DeviceError(f"未找到可用设备（目标URI：{target_uri}）")

    def get_coord_type_enum(self, coord_type: str) -> Any:
        """通用坐标类型转枚举方法（消除重复）"""
        from src.auto_control.devices.windows.constants import CoordType

        valid_types = {"LOGICAL", "PHYSICAL", "BASE"}
        coord_type_upper = coord_type.upper()

        if coord_type_upper not in valid_types:
            self.logger.warning(f"无效的坐标类型: {coord_type}，使用默认类型{self.config.DEFAULT_COORD_TYPE}")
            return getattr(CoordType, self.config.DEFAULT_COORD_TYPE)

        return getattr(CoordType, coord_type_upper)

    def add_device(self, device_uri: str = None, timeout: float = None) -> AutoResult:
        """添加设备（封装设备添加逻辑）"""
        start_time = time.time()
        timeout = timeout or self.config.DEFAULT_DEVICE_TIMEOUT

        if self.auto.check_should_stop():
            self.logger.debug("添加设备任务被中断")
            return AutoResult.fail_result(error_msg="添加设备任务被中断", elapsed_time=0.0, is_interrupted=True)

        try:
            # 使用默认设备URI如果未提供
            device_uri = device_uri or self.config.DEFAULT_DEVICE_URI
            result = self.device_manager.add_device(device_uri=device_uri, timeout=timeout)
            elapsed = time.time() - start_time

            if result:
                self.logger.info(f"设备 {device_uri} 添加请求已提交")
                return AutoResult.success_result(data=result, elapsed_time=elapsed)
            else:
                raise DeviceError(f"设备 {device_uri} 添加失败")
        except Exception as e:
            elapsed = time.time() - start_time
            self.logger.error(f"添加设备异常: {str(e)}", exc_info=True)
            return AutoResult.fail_result(error_msg=f"添加设备异常：{str(e)}", elapsed_time=elapsed)

    def set_active_device(self, device_uri: str) -> AutoResult:
        """设置活动设备（封装设备切换逻辑）"""
        start_time = time.time()

        try:
            result = self.device_manager.set_active_device(device_uri)
            elapsed = time.time() - start_time

            if not result:
                raise DeviceError(f"设置活动设备失败: {device_uri}")

            self.logger.info(f"活动设备切换为: {device_uri}")
            return AutoResult.success_result(data=result, elapsed_time=elapsed)
        except DeviceError as e:
            self.logger.error(str(e))
            return AutoResult.fail_result(error_msg=str(e), elapsed_time=elapsed)
