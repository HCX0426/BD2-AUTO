import time
from typing import Dict, Optional, List, Tuple

from src.auto_control.devices.adb_device import ADBDevice
from src.auto_control.devices.base_device import BaseDevice, DeviceState
from src.auto_control.devices.windows_device import WindowsDevice
from src.auto_control.image.image_processor import ImageProcessor
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.display_context import RuntimeDisplayContext


class DeviceManager:
    """设备管理器：负责设备的添加、移除、状态跟踪和活动设备管理（含分辨率自动同步）"""
    
    def __init__(self, logger, image_processor: ImageProcessor, coord_transformer: CoordinateTransformer, display_context: RuntimeDisplayContext):
        """
        初始化设备管理器（强制依赖上层传入有效实例）
        :param logger: 日志实例（必需）
        :param image_processor: 图像处理器实例（必需）
        :param coord_transformer: 坐标转换器实例（必需）
        :param display_context: 显示上下文实例（必需）
        :raises ValueError: 任何必需依赖缺失时抛错
        """
        # 强制检查所有必需依赖（不存在直接抛错，不提供降级）
        if not logger:
            raise ValueError("[DeviceManager] 初始化失败：logger不能为空（Auto层必须传入有效日志实例）")
        if not isinstance(image_processor, ImageProcessor):
            raise ValueError("[DeviceManager] 初始化失败：image_processor必须是ImageProcessor实例")
        if not isinstance(coord_transformer, CoordinateTransformer):
            raise ValueError("[DeviceManager] 初始化失败：coord_transformer必须是CoordinateTransformer实例")
        if not isinstance(display_context, RuntimeDisplayContext):
            raise ValueError("[DeviceManager] 初始化失败：display_context必须是RuntimeDisplayContext实例")

        # 设备存储：URI -> 设备实例（统一转为小写存储）
        self.devices: Dict[str, BaseDevice] = {}
        # 活动设备URI（当前操作的设备）
        self.active_device: Optional[str] = None
        # 共享组件（已在上层校验有效，直接赋值）
        self.logger = logger
        self.image_processor = image_processor
        self.coord_transformer = coord_transformer
        self.display_context = display_context

        self.logger.info("[DeviceManager] 设备管理器初始化完成")

    # ======================== 分辨率同步核心方法 ========================
    def _sync_device_resolution(self, device: BaseDevice) -> bool:
        """同步设备分辨率到上下文和坐标转换器（内部自动调用）"""
        # 只保留业务相关检查（设备是否有效+已连接）
        if not device or not device.is_connected:
            self.logger.debug(f"[DeviceManager] 分辨率同步失败：设备{getattr(device, 'device_uri', '未知')}未连接或无效")
            return False

        try:
            # 触发设备更新动态窗口信息（仅WindowsDevice支持，兼容其他设备）
            if hasattr(device, "_update_dynamic_window_info") and callable(device._update_dynamic_window_info):
                device._update_dynamic_window_info()
            
            # 获取设备客户区分辨率（检查格式合法性，运行时可能出现）
            resolution = device.get_resolution()
            if not isinstance(resolution, (tuple, list)) or len(resolution) != 2:
                self.logger.error(f"[DeviceManager] 分辨率同步失败：设备{device.device_uri}返回无效格式 {resolution}（需(x, y)）")
                return False
            if resolution[0] <= 0 or resolution[1] <= 0:
                self.logger.error(f"[DeviceManager] 分辨率同步失败：设备{device.device_uri}返回无效尺寸 {resolution}（需正数）")
                return False
            
            # 同步到显示上下文（依赖已在__init__校验，直接调用）
            self.display_context.update_client_resolution(
                client_logical_width=resolution[0],
                client_logical_height=resolution[1]
            )
            
            # 同步到坐标转换器（依赖已在__init__校验，直接调用）
            self.coord_transformer.update_context(self.display_context)
            
            # 输出详细同步日志
            self.logger.debug(
                f"[DeviceManager] 分辨率同步成功 | 设备: {device.device_uri} | "
                f"客户区尺寸: {resolution[0]}x{resolution[1]} | "
                f"全屏状态: {self.coord_transformer.is_fullscreen}"
            )
            return True
        except Exception as e:
            self.logger.error(f"[DeviceManager] 设备{getattr(device, 'device_uri', '未知')}分辨率同步异常：{str(e)}", exc_info=True)
            return False

    # ======================== 设备管理核心方法 ========================
    def get_device(self, device_uri: str) -> Optional[BaseDevice]:
        """获取指定URI的设备实例（URI自动转为小写匹配）"""
        lower_uri = device_uri.lower()
        device = self.devices.get(lower_uri)
        if device:
            self.logger.debug(f"[DeviceManager] 获取设备成功: {device_uri}（状态: {device.get_state().name}）")
        else:
            self.logger.debug(f"[DeviceManager] 未找到设备: {device_uri}")
        return device

    def get_active_device(self) -> Optional[BaseDevice]:
        """获取当前活动设备（自动校验有效性）"""
        if not self.active_device:
            self.logger.debug("[DeviceManager] 无活动设备")
            return None
        
        device = self.get_device(self.active_device)
        if not device:
            self.logger.warning(f"[DeviceManager] 活动设备{self.active_device}不存在，已重置")
            self.active_device = None
        return device

    def get_all_devices(self) -> Dict[str, BaseDevice]:
        """获取所有设备字典（URI -> 实例）（返回副本，避免外部修改）"""
        device_count = len(self.devices)
        self.logger.debug(f"[DeviceManager] 当前已连接设备总数: {device_count}")
        return self.devices.copy()

    def get_device_list(self) -> List[str]:
        """获取所有设备URI列表（按添加顺序返回）"""
        uri_list = list(self.devices.keys())
        self.logger.debug(f"[DeviceManager] 设备URI列表: {uri_list}")
        return uri_list

    def add_device(
        self, 
        device_uri: str, 
        timeout: float = 10.0
    ) -> bool:
        """
        添加设备并自动连接（支持Windows/ADB设备）
        :param device_uri: 设备URI（格式：windows://xxx 或 adb://xxx）
        :param timeout: 连接超时时间（秒）
        :return: 是否添加成功
        """
        lower_uri = device_uri.lower()
        
        # 1. 检查设备是否已存在
        if lower_uri in self.devices:
            device = self.devices[lower_uri]
            if device.is_connected:
                self.logger.info(f"[DeviceManager] 设备已存在且已连接: {device_uri}（状态: {device.get_state().name}）")
                self._sync_device_resolution(device)
                return True
            else:
                self.logger.warning(f"[DeviceManager] 设备已存在但未连接，尝试重新连接: {device_uri}")
                del self.devices[lower_uri]

        # 2. 识别设备类型
        if lower_uri.startswith("windows://"):
            device_type = "Windows"
            # Windows设备依赖ImageProcessor（已在__init__校验，直接使用）
        elif lower_uri.startswith(("android://", "adb://")):
            device_type = "ADB"
        else:
            self.logger.error(f"[DeviceManager] 添加设备失败：无法识别URI类型 - {device_uri}（支持windows:// / adb://）")
            return False

        try:
            self.logger.info(f"[DeviceManager] 开始添加{device_type}设备: {device_uri}（超时时间: {timeout}s）")
            
            # 3. 创建设备实例（依赖已校验，直接传入）
            if device_type == "Windows":
                device = WindowsDevice(
                    device_uri=device_uri,
                    logger=self.logger,
                    image_processor=self.image_processor,
                    coord_transformer=self.coord_transformer,
                    display_context=self.display_context
                )
            else:  # ADB设备
                device = ADBDevice(
                    device_uri=device_uri,
                    logger=self.logger
                )

            # 4. 尝试连接设备
            start_time = time.time()
            connect_success = device.connect(timeout=timeout)
            elapsed_time = time.time() - start_time
            
            if connect_success:
                # 5. 连接成功：添加到设备列表
                self.devices[lower_uri] = device
                # 6. 自动设置第一个设备为活动设备
                if not self.active_device:
                    self.active_device = lower_uri
                    self.logger.debug(f"[DeviceManager] 自动设置活动设备: {device_uri}（首个添加的设备）")
                # 7. 自动同步分辨率
                sync_success = self._sync_device_resolution(device)
                sync_msg = "分辨率同步成功" if sync_success else "分辨率同步失败（不影响设备使用）"
                self.logger.info(
                    f"[DeviceManager] 设备添加成功: {device_uri} | "
                    f"耗时: {elapsed_time:.2f}s | "
                    f"{sync_msg}"
                )
                return True
            else:
                # 连接失败：输出具体错误
                error_msg = device.last_error or "未知连接错误"
                self.logger.error(
                    f"[DeviceManager] 设备连接失败: {device_uri} | "
                    f"耗时: {elapsed_time:.2f}s | "
                    f"错误原因: {error_msg}"
                )
                return False

        except Exception as e:
            self.logger.error(f"[DeviceManager] 添加设备异常: {device_uri} - {str(e)}", exc_info=True)
            return False

    def remove_device(self, device_uri: str) -> bool:
        """
        移除设备（断开连接并删除实例）
        :param device_uri: 设备URI
        :return: 是否移除成功
        """
        lower_uri = device_uri.lower()
        device = self.devices.get(lower_uri)
        
        if not device:
            self.logger.warning(f"[DeviceManager] 移除设备失败：设备不存在 - {device_uri}")
            return False

        try:
            # 1. 断开设备连接
            if device.is_connected:
                disconnect_success = device.disconnect()
                disconnect_msg = "已断开连接" if disconnect_success else "断开连接失败"
            else:
                disconnect_msg = "设备未连接"
            
            # 2. 从设备列表中删除
            del self.devices[lower_uri]
            self.logger.info(f"[DeviceManager] 设备移除成功: {device_uri} | {disconnect_msg}")
            
            # 3. 处理活动设备切换（如果移除的是当前活动设备）
            if self.active_device == lower_uri:
                self.active_device = next(iter(self.devices.keys()), None)
                if self.active_device:
                    self.logger.info(f"[DeviceManager] 活动设备自动切换为: {self.active_device}")
                    self._sync_device_resolution(self.get_active_device())
                else:
                    self.logger.info("[DeviceManager] 所有设备已移除，无当前活动设备")
            
            return True
        except Exception as e:
            self.logger.error(f"[DeviceManager] 移除设备异常: {device_uri} - {str(e)}", exc_info=True)
            return False

    def set_active_device(self, device_uri: str) -> bool:
        """
        设置活动设备（仅支持已连接的设备）
        :param device_uri: 设备URI
        :return: 是否设置成功
        """
        lower_uri = device_uri.lower()
        device = self.devices.get(lower_uri)
        
        # 1. 校验设备是否存在
        if not device:
            self.logger.error(f"[DeviceManager] 设置活动设备失败：设备不存在 - {device_uri}")
            return False
        
        # 2. 校验设备是否已连接
        if not device.is_connected:
            current_state = device.get_state().name
            self.logger.error(
                f"[DeviceManager] 设置活动设备失败：设备未连接 - {device_uri} | "
                f"当前状态: {current_state}（需CONNECTED状态）"
            )
            return False
        
        # 3. 设置为活动设备并同步分辨率
        old_active_device = self.active_device
        self.active_device = lower_uri
        sync_success = self._sync_device_resolution(device)
        sync_msg = "分辨率同步成功" if sync_success else "分辨率同步失败"
        
        self.logger.info(
            f"[DeviceManager] 活动设备切换成功 | "
            f"原设备: {old_active_device or '无'} | "
            f"新设备: {device_uri} | "
            f"{sync_msg}"
        )
        return True

    def sync_active_device_resolution(self) -> bool:
        """
        主动同步当前活动设备的分辨率（供窗口操作后调用）
        :return: 是否同步成功
        """
        active_device = self.get_active_device()
        if not active_device:
            self.logger.debug("[DeviceManager] 主动同步分辨率失败：无活动设备")
            return False
        
        self.logger.debug(f"[DeviceManager] 开始主动同步活动设备分辨率：{active_device.device_uri}")
        return self._sync_device_resolution(active_device)

    def disconnect_all(self) -> Tuple[int, int]:
        """
        断开所有设备连接并清空列表
        :return: (成功断开数量, 失败断开数量)
        """
        success_count = 0
        fail_count = 0
        total_count = len(self.devices)
        
        if total_count == 0:
            self.logger.info("[DeviceManager] 无设备需要断开连接")
            return (0, 0)
        
        self.logger.info(f"[DeviceManager] 开始断开所有设备连接（共{total_count}个设备）")
        for uri, device in list(self.devices.items()):
            if device.is_connected:
                if device.disconnect():
                    success_count += 1
                else:
                    fail_count += 1
        
        self.devices.clear()
        self.active_device = None
        self.logger.info(
            f"[DeviceManager] 所有设备断开连接完成 | "
            f"成功: {success_count}个 | "
            f"失败: {fail_count}个 | "
            f"总计: {total_count}个"
        )
        return (success_count, fail_count)

    def get_device_state(self, device_uri: str) -> Optional[DeviceState]:
        """
        获取指定设备的当前状态
        :param device_uri: 设备URI
        :return: DeviceState枚举（None表示设备不存在）
        """
        device = self.get_device(device_uri)
        if not device:
            return None
        
        device_state = device.get_state()
        self.logger.debug(f"[DeviceManager] 设备状态查询: {device_uri} - {device_state.name}")
        return device_state

    def is_device_operable(self, device_uri: str) -> bool:
        """
        检查设备是否可操作（状态为CONNECTED或IDLE）
        :param device_uri: 设备URI
        :return: True=可操作，False=不可操作
        """
        device_state = self.get_device_state(device_uri)
        if not device_state:
            self.logger.debug(f"[DeviceManager] 设备可操作性查询失败：设备不存在 - {device_uri}")
            return False
        
        operable = device_state in (DeviceState.CONNECTED, DeviceState.IDLE)
        self.logger.debug(
            f"[DeviceManager] 设备可操作性查询: {device_uri} - {operable} | "
            f"状态: {device_state.name}"
        )
        return operable

    # ======================== 魔术方法 ========================
    def __len__(self) -> int:
        """返回当前设备总数"""
        return len(self.devices)

    def __contains__(self, device_uri: str) -> bool:
        """检查设备是否已存在（支持 in 语法）"""
        return device_uri.lower() in self.devices