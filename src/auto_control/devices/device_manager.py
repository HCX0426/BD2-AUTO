import time
from typing import Dict, Optional, List, Tuple

from src.auto_control.devices.adb_device import ADBDevice
from src.auto_control.devices.base_device import BaseDevice, DeviceState
from src.auto_control.devices.windows_device import WindowsDevice
from src.auto_control.image.image_processor import ImageProcessor
from src.auto_control.until.coordinate_transformer import CoordinateTransformer


class DeviceManager:
    """设备管理器：负责设备的添加、移除、状态跟踪和活动设备管理"""
    
    def __init__(self, logger=None, image_processor: Optional[ImageProcessor] = None, coord_transformer: Optional[CoordinateTransformer] = None):
        """初始化设备管理器"""
        # 设备存储：URI -> 设备实例
        self.devices: Dict[str, BaseDevice] = {}
        # 活动设备URI（当前操作的设备）
        self.active_device: Optional[str] = None
        # 日志实例（从上层接收）
        self.logger = logger if logger else self._create_default_logger()
        # 坐标转换器实例（从上层接收）
        self.coord_transformer = coord_transformer
        # 图像处理器实例（从上层接收）
        self.image_processor = image_processor
        self.logger.info("设备管理器初始化完成")

    def _create_default_logger(self):
        """降级方案：无日志实例时的基础实现"""
        class DefaultLogger:
            @staticmethod
            def debug(msg):
                print(f"[DEBUG] DeviceManager: {msg}")
            
            @staticmethod
            def info(msg):
                print(f"[INFO] DeviceManager: {msg}")
            
            @staticmethod
            def warning(msg):
                print(f"[WARNING] DeviceManager: {msg}")
            
            @staticmethod
            def error(msg, exc_info=False):
                print(f"[ERROR] DeviceManager: {msg}")
        
        return DefaultLogger()

    def get_device(self, device_uri: str) -> Optional[BaseDevice]:
        """获取指定URI的设备实例"""
        device = self.devices.get(device_uri.lower())
        if device:
            self.logger.debug(f"获取设备成功: {device_uri}（状态: {device.get_state().name}）")
        else:
            self.logger.debug(f"未找到设备: {device_uri}")
        return device

    def get_active_device(self) -> Optional[BaseDevice]:
        """获取当前活动设备"""
        if not self.active_device:
            self.logger.debug("无活动设备")
            return None
        
        device = self.get_device(self.active_device)
        if not device:
            self.logger.warning(f"活动设备不存在，已重置: {self.active_device}")
            self.active_device = None
        return device

    def get_all_devices(self) -> Dict[str, BaseDevice]:
        """获取所有设备字典（URI -> 实例）"""
        self.logger.debug(f"当前设备总数: {len(self.devices)}")
        return self.devices.copy()

    def get_device_list(self) -> List[str]:
        """获取所有设备URI列表"""
        return list(self.devices.keys())

    def add_device(
        self, 
        device_uri: str, 
        timeout: float = 10.0, 
        logger=None,
        image_processor: Optional[ImageProcessor] = None,
        coord_transformer: Optional[CoordinateTransformer] = None
    ) -> bool:
        """
        添加设备并连接（支持Windows和ADB设备）
        :param device_uri: 设备URI（如windows://title_re=xxx或adb://xxx）
        :param timeout: 连接超时时间
        :param logger: 传递给设备的日志实例
        :param image_processor: 共享的ImageProcessor实例
        :param coord_transformer: 共享的CoordinateTransformer实例
        :return: 是否添加成功
        """
        lower_uri = device_uri.lower()
        
        # 检查设备是否已存在
        if lower_uri in self.devices:
            device = self.devices[lower_uri]
            if device.is_connected:
                self.logger.info(f"设备已存在且已连接: {device_uri}（状态: {device.get_state().name}）")
                return True
            else:
                self.logger.warning(f"设备已存在但未连接，尝试重新连接: {device_uri}")
                # 移除旧实例，重新创建
                del self.devices[lower_uri]

        # 识别设备类型
        if lower_uri.startswith("windows://"):
            device_type = "windows"
            # Windows设备必须传入ImageProcessor
            if not image_processor and not self.image_processor:
                self.logger.error("添加Windows设备失败：必须提供ImageProcessor实例")
                return False
        elif lower_uri.startswith(("android://", "adb://")):
            device_type = "adb"
        else:
            self.logger.error(f"无法识别设备URI类型: {device_uri}")
            return False

        try:
            self.logger.info(f"开始添加{device_type}设备: {device_uri}（超时: {timeout}s）")
            
            # 创建对应类型的设备实例
            if device_type == "windows":
                device = WindowsDevice(
                    device_uri=device_uri,
                    logger=logger or self.logger,
                    image_processor=image_processor or self.image_processor,
                    coord_transformer=coord_transformer or self.coord_transformer
                )
            else:  # adb设备
                device = ADBDevice(
                    device_uri=device_uri,
                    logger=logger or self.logger
                )

            # 尝试连接设备
            start_time = time.time()
            connect_success = device.connect(timeout=timeout)
            
            if connect_success:
                self.devices[lower_uri] = device
                # 自动设置第一个设备为活动设备
                if not self.active_device:
                    self.active_device = lower_uri
                    self.logger.debug(f"自动设置活动设备: {lower_uri}")
                self.logger.info(f"设备添加成功: {device_uri}（耗时: {time.time()-start_time:.2f}s）")
                return True
            else:
                self.logger.error(
                    f"设备连接失败: {device_uri}（错误: {device.last_error or '未知错误'}）"
                )
                return False

        except Exception as e:
            self.logger.error(f"添加设备异常: {str(e)}", exc_info=True)
            return False

    def remove_device(self, device_uri: str) -> bool:
        """移除设备（断开连接并删除实例）"""
        lower_uri = device_uri.lower()
        device = self.devices.get(lower_uri)
        
        if not device:
            self.logger.warning(f"无法移除设备: {device_uri}（设备不存在）")
            return False

        try:
            # 断开连接
            if device.is_connected:
                device.disconnect()
            
            # 从设备列表中移除
            del self.devices[lower_uri]
            self.logger.info(f"设备已移除: {device_uri}")
            
            # 如果移除的是活动设备，自动切换
            if self.active_device == lower_uri:
                self.active_device = next(iter(self.devices.keys()), None)
                if self.active_device:
                    self.logger.info(f"活动设备已切换为: {self.active_device}")
                    # 切换后更新坐标转换器上下文
                    self._update_coord_transformer_context()
                else:
                    self.logger.info("所有设备已移除，无活动设备")
            
            return True
        except Exception as e:
            self.logger.error(f"移除设备失败: {str(e)}", exc_info=True)
            return False

    def set_active_device(self, device_uri: str) -> bool:
        """设置活动设备（仅允许已连接的设备）"""
        lower_uri = device_uri.lower()
        device = self.devices.get(lower_uri)
        
        if not device:
            self.logger.error(f"无法设置活动设备: {device_uri}（设备不存在）")
            return False
        
        if not device.is_connected:
            self.logger.error(
                f"无法设置活动设备: {device_uri}（设备未连接，当前状态: {device.get_state().name}）"
            )
            return False
        
        self.active_device = lower_uri
        self.logger.info(f"活动设备已设置为: {device_uri}（状态: {device.get_state().name}）")
        
        # 切换活动设备后，更新坐标转换器上下文
        self._update_coord_transformer_context()
        
        return True

    def _update_coord_transformer_context(self):
        """更新坐标转换器的上下文（内部方法）"""
        active_device = self.get_active_device()
        if not active_device or not self.coord_transformer:
            return
            
        # 对于Windows设备，触发动态窗口信息更新，确保坐标转换器获取最新状态
        if isinstance(active_device, WindowsDevice):
            try:
                active_device._update_dynamic_window_info()
                self.logger.debug(f"已为活动设备更新坐标转换器上下文: {self.active_device}")
            except Exception as e:
                self.logger.error(f"更新坐标转换器上下文失败: {str(e)}")

    def disconnect_all(self) -> Tuple[int, int]:
        """断开所有设备连接（返回成功/失败数量）"""
        success_count = 0
        fail_count = 0
        
        for uri, device in list(self.devices.items()):
            if device.is_connected:
                if device.disconnect():
                    success_count += 1
                else:
                    fail_count += 1
        
        self.devices.clear()
        self.active_device = None
        self.logger.info(f"所有设备断开连接完成: 成功{success_count}个, 失败{fail_count}个")
        return (success_count, fail_count)

    def get_device_state(self, device_uri: str) -> Optional[DeviceState]:
        """获取设备当前状态"""
        device = self.get_device(device_uri)
        if device:
            state = device.get_state()
            self.logger.debug(f"设备{device_uri}状态: {state.name}")
            return state
        return None

    def is_device_operable(self, device_uri: str) -> bool:
        """检查设备是否可操作（状态为CONNECTED或IDLE）"""
        state = self.get_device_state(device_uri)
        operable = state in (DeviceState.CONNECTED, DeviceState.IDLE)
        self.logger.debug(f"设备{device_uri}可操作性: {operable}（状态: {state.name if state else '未知'}）")
        return operable

    def __len__(self) -> int:
        """返回设备数量"""
        return len(self.devices)

    def __contains__(self, device_uri: str) -> bool:
        """检查设备是否已存在"""
        return device_uri.lower() in self.devices
