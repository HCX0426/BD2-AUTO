import time
from threading import Event
from typing import Dict, List, Optional, Tuple

from src.auto_control.devices.adb_device import ADBDevice
from src.auto_control.devices.base_device import BaseDevice, DeviceState
from src.auto_control.devices.windows import WindowsDevice
from src.auto_control.image.image_processor import ImageProcessor
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer
from src.auto_control.utils.display_context import RuntimeDisplayContext


class DeviceManager:
    """
    设备管理器：统一管理多类型设备（Windows/ADB）的生命周期、状态跟踪和分辨率同步
    核心能力：
    1. 设备生命周期：添加/移除/连接/断开，支持多设备共存
    2. 活动设备管理：设置/切换当前操作设备，自动校验有效性
    3. 分辨率同步：自动/手动同步设备分辨率到坐标转换器和显示上下文
    4. 中断支持：全局stop_event传递给设备实例，支持阻塞操作中断
    """

    def __init__(
        self,
        logger,
        image_processor: ImageProcessor,
        coord_transformer: CoordinateTransformer,
        display_context: RuntimeDisplayContext,
        stop_event: Event,
        config: object,
        settings_manager=None,
    ):
        """
        初始化设备管理器

        Args:
            logger: 日志实例（必需）
            image_processor: 图像处理器实例（必需）
            coord_transformer: 坐标转换器实例（必需）
            display_context: 显示上下文实例（必需）
            stop_event: 全局停止事件（用于中断设备阻塞操作，必需）
            config: 配置对象（必需）
            settings_manager: 设置管理器实例（用于获取永久置顶等设置，可选）

        Raises:
            ValueError: 任意必需参数缺失/类型错误时抛出
        """
        # 强制校验必需依赖
        if not logger:
            raise ValueError("初始化失败：logger不能为空（需传入有效日志实例）")
        if not isinstance(image_processor, ImageProcessor):
            raise ValueError("初始化失败：image_processor必须是ImageProcessor实例")
        if not isinstance(coord_transformer, CoordinateTransformer):
            raise ValueError("初始化失败：coord_transformer必须是CoordinateTransformer实例")
        if not isinstance(display_context, RuntimeDisplayContext):
            raise ValueError("初始化失败：display_context必须是RuntimeDisplayContext实例")
        if not isinstance(stop_event, Event):
            raise ValueError("初始化失败：stop_event必须是threading.Event实例")
        if not config:
            raise ValueError("初始化失败：config不能为空")

        # 设备存储：URI（小写）→ 设备实例
        self.devices: Dict[str, BaseDevice] = {}
        # 当前活动设备URI（小写）
        self.active_device: Optional[str] = None

        # 自动重连配置
        self.auto_reconnect_enabled = True  # 是否启用自动重连
        self.max_reconnect_attempts = 3  # 最大重连尝试次数
        self.reconnect_interval = 1.0  # 重连间隔（秒）

        # 共享组件
        self.logger = logger
        self.image_processor = image_processor
        self.coord_transformer = coord_transformer
        self.config = config
        self.display_context = display_context
        self.stop_event = stop_event
        self.settings_manager = settings_manager

        self.logger.info("设备管理器初始化完成")

    # ======================== 内部核心方法 ========================
    def _sync_device_resolution(self, device: BaseDevice) -> bool:
        """
        同步设备分辨率到上下文和坐标转换器

        Args:
            device: 目标设备实例

        Returns:
            同步成功返回True，失败返回False
        """
        if not device or not device.is_connected:
            self.logger.debug(f"分辨率同步失败：设备{getattr(device, 'device_uri', '未知')}未连接或无效")
            return False

        try:
            # Windows设备专属的动态窗口信息更新
            if hasattr(device, "_update_dynamic_window_info") and callable(device._update_dynamic_window_info):
                device._update_dynamic_window_info()
            return True
        except Exception as e:
            self.logger.error(f"设备{getattr(device, 'device_uri', '未知')}分辨率同步异常：{str(e)}", exc_info=True)
            return False

    def _reconnect_device(self, device_uri: str) -> bool:
        """
        尝试重新连接设备

        Args:
            device_uri: 设备标识URI

        Returns:
            重连成功返回True，失败返回False
        """
        if not device_uri or str(device_uri).strip() == "":
            self.logger.error("设备重连失败：device_uri 不能为空")
            return False

        if not self.auto_reconnect_enabled:
            self.logger.debug(f"自动重连已禁用，跳过设备{device_uri}的重连")
            return False

        lower_uri = device_uri.strip().lower()
        device = self.devices.get(lower_uri)

        if not device:
            self.logger.debug(f"设备{device_uri}不存在，无法重连")
            return False

        self.logger.debug(f"开始尝试重连设备：{device_uri}")

        # 尝试多次重连（原有逻辑不变）
        for attempt in range(self.max_reconnect_attempts):
            if self.stop_event.is_set():
                self.logger.debug(f"重连被中断，设备：{device_uri}")
                return False

            self.logger.debug(f"重连尝试 {attempt+1}/{self.max_reconnect_attempts}，设备：{device_uri}")

            # 断开现有连接
            try:
                device.disconnect()
            except Exception as e:
                self.logger.debug(f"断开设备{device_uri}连接时发生异常：{str(e)}")

            # 等待一段时间后尝试重新连接
            time.sleep(self.reconnect_interval)

            # 尝试重新连接
            if device.connect():
                self.logger.debug(f"设备{device_uri}重连成功")
                # 同步分辨率
                self._sync_device_resolution(device)
                return True
            else:
                self.logger.warning(f"设备{device_uri}重连失败，尝试 {attempt+1}/{self.max_reconnect_attempts}")

        self.logger.error(f"设备{device_uri}重连失败，已达到最大尝试次数 {self.max_reconnect_attempts}")
        return False

    # ======================== 设备查询方法 ========================
    def get_device(self, device_uri: str) -> Optional[BaseDevice]:
        """
        获取指定URI的设备实例，如果设备断开连接则尝试自动重连

        Args:
            device_uri: 设备标识URI

        Returns:
            设备实例（不存在返回None）
        """
        # 强化空值校验：不仅判断空字符串，还判断None/空白字符
        if not device_uri or str(device_uri).strip() == "":
            self.logger.error("获取设备失败：device_uri 不能为空（None/空字符串/全空白均不允许）")
            return None

        lower_uri = device_uri.strip().lower()
        device = self.devices.get(lower_uri)

        if device:
            # 检查设备状态，如果断开连接则尝试自动重连
            if not device.is_connected:
                self.logger.warning(f"设备{device_uri}已断开连接，尝试自动重连...")
                if self._reconnect_device(device_uri):
                    self.logger.debug(f"获取设备成功: {device_uri}（状态: {device.get_state().name}）")
                else:
                    self.logger.error(f"获取设备失败: {device_uri}（重连失败）")
                    return None
            else:
                self.logger.debug(f"获取设备成功: {device_uri}（状态: {device.get_state().name}）")
        else:
            self.logger.debug(f"未找到设备: {device_uri}")
        return device

    def get_active_device(self) -> Optional[BaseDevice]:
        """
        获取当前活动设备（自动校验有效性，无效则重置）

        Returns:
            活动设备实例（无/无效返回None）
        """
        if not self.active_device or str(self.active_device).strip() == "":
            self.logger.debug("无活动设备（active_device为空/无效）")
            return None

        active_device_str = str(self.active_device).strip()
        device = self.get_device(active_device_str)
        if not device:
            self.logger.warning(f"活动设备{self.active_device}不存在/无效，已重置active_device")
            self.active_device = None
        return device

    def get_all_devices(self) -> Dict[str, BaseDevice]:
        """
        获取所有设备字典（返回副本，避免外部修改）

        Returns:
            URI（小写）→ 设备实例的字典副本
        """
        device_count = len(self.devices)
        self.logger.debug(f"当前已连接设备总数: {device_count}")
        return self.devices.copy()

    def get_device_list(self) -> List[str]:
        """
        获取所有设备URI列表（按添加顺序）

        Returns:
            设备URI字符串列表
        """
        uri_list = list(self.devices.keys())
        self.logger.debug(f"设备URI列表: {uri_list}")
        return uri_list

    def get_device_state(self, device_uri: str) -> Optional[DeviceState]:
        """
        获取指定设备的当前状态

        Args:
            device_uri: 设备标识URI

        Returns:
            设备状态枚举（None表示设备不存在）
        """
        device = self.get_device(device_uri)
        if not device:
            return None

        device_state = device.get_state()
        self.logger.debug(f"设备状态查询: {device_uri} - {device_state.name}")
        return device_state

    def is_device_operable(self, device_uri: str) -> bool:
        """
        检查设备是否可操作（状态为CONNECTED/IDLE）

        Args:
            device_uri: 设备标识URI

        Returns:
            可操作返回True，否则返回False
        """
        device_state = self.get_device_state(device_uri)
        if not device_state:
            self.logger.debug(f"设备可操作性查询失败：设备不存在 - {device_uri}")
            return False

        operable = device_state in (DeviceState.CONNECTED, DeviceState.IDLE)
        self.logger.debug(f"设备可操作性查询: {device_uri} - {operable} | " f"状态: {device_state.name}")
        return operable

    # ======================== 设备管理方法 ========================
    def add_device(self, device_uri: str, timeout: float = 10.0) -> bool:
        """
        添加设备并自动连接（支持Windows/ADB设备）

        Args:
            device_uri: 设备URI（格式：windows://xxx 或 adb://xxx）
            timeout: 连接超时时间（秒，默认10s）

        Returns:
            添加并连接成功返回True，失败返回False
        """
        if not device_uri:
            self.logger.error("添加设备失败：device_uri 不能为空")
            return False
        lower_uri = device_uri.lower()

        # 检查设备是否已存在
        if lower_uri in self.devices:
            device = self.devices[lower_uri]
            if device.is_connected:
                self.logger.info(f"设备已存在且已连接: {device_uri}（状态: {device.get_state().name}）")
                self._sync_device_resolution(device)
                return True
            else:
                self.logger.warning(f"设备已存在但未连接，尝试重新连接: {device_uri}")
                del self.devices[lower_uri]

        # 识别设备类型
        if lower_uri.startswith("windows://"):
            device_type = "Windows"
        elif lower_uri.startswith(("android://", "adb://")):
            device_type = "ADB"
        else:
            self.logger.error(f"添加设备失败：无法识别URI类型 - {device_uri}（支持windows:// / adb://）")
            return False

        try:
            self.logger.info(f"开始添加{device_type}设备: {device_uri}（超时时间: {timeout}s）")

            # 创建设备实例（传递stop_event给Windows设备）
            if device_type == "Windows":
                device = WindowsDevice(
                    device_uri=device_uri,
                    logger=self.logger,
                    image_processor=self.image_processor,
                    coord_transformer=self.coord_transformer,
                    display_context=self.display_context,
                    stop_event=self.stop_event,
                    settings_manager=self.settings_manager,
                )
            else:  # ADB设备
                device = ADBDevice(device_uri=device_uri, logger=self.logger)

            # 尝试连接设备
            start_time = time.time()
            connect_success = device.connect(timeout=timeout)
            elapsed_time = time.time() - start_time

            if connect_success:
                # 连接成功：添加到设备列表
                self.devices[lower_uri] = device
                # 自动设置第一个设备为活动设备
                if not self.active_device:
                    self.active_device = lower_uri
                    self.logger.debug(f"自动设置活动设备: {device_uri}（首个添加的设备）")
                # 自动同步分辨率
                sync_success = self._sync_device_resolution(device)
                sync_msg = "分辨率同步成功" if sync_success else "分辨率同步失败（不影响设备使用）"
                self.logger.info(f"设备添加成功: {device_uri} | " f"耗时: {elapsed_time:.2f}s | " f"{sync_msg}")
                return True
            else:
                # 连接失败：输出具体错误
                error_msg = device.last_error or "未知连接错误"
                self.logger.error(
                    f"设备连接失败: {device_uri} | " f"耗时: {elapsed_time:.2f}s | " f"错误原因: {error_msg}"
                )
                self.logger.error(f"设备连接失败时的详细状态: hwnd={device.hwnd}, last_error={device.last_error}")
                return False

        except Exception as e:
            import traceback

            self.logger.error(f"添加设备异常: {device_uri} - {str(e)}")
            self.logger.error(f"异常堆栈: {traceback.format_exc()}")
            return False

    def remove_device(self, device_uri: str) -> bool:
        """
        移除设备（断开连接并删除实例）

        Args:
            device_uri: 设备标识URI

        Returns:
            移除成功返回True，失败返回False
        """
        lower_uri = device_uri.lower()
        device = self.devices.get(lower_uri)

        if not device:
            self.logger.warning(f"移除设备失败：设备不存在 - {device_uri}")
            return False

        try:
            # 断开设备连接
            if device.is_connected:
                disconnect_success = device.disconnect()
                disconnect_msg = "已断开连接" if disconnect_success else "断开连接失败"
            else:
                disconnect_msg = "设备未连接"

            # 从设备列表中删除
            del self.devices[lower_uri]
            self.logger.info(f"设备移除成功: {device_uri} | {disconnect_msg}")

            # 处理活动设备切换
            if self.active_device == lower_uri:
                self.active_device = next(iter(self.devices.keys()), None)
                if self.active_device:
                    self.logger.info(f"活动设备自动切换为: {self.active_device}")
                    self._sync_device_resolution(self.get_active_device())
                else:
                    self.logger.info("所有设备已移除，无当前活动设备")

            return True
        except Exception as e:
            self.logger.error(f"移除设备异常: {device_uri} - {str(e)}", exc_info=True)
            return False

    def set_active_device(self, device_uri: str) -> bool:
        """
        设置活动设备（仅支持已连接的设备）

        Args:
            device_uri: 设备标识URI

        Returns:
            设置成功返回True，失败返回False
        """
        lower_uri = device_uri.lower()
        device = self.devices.get(lower_uri)

        # 校验设备是否存在
        if not device:
            self.logger.error(f"设置活动设备失败：设备不存在 - {device_uri}")
            return False

        # 校验设备是否已连接
        if not device.is_connected:
            current_state = device.get_state().name
            self.logger.error(
                f"设置活动设备失败：设备未连接 - {device_uri} | " f"当前状态: {current_state}（需CONNECTED状态）"
            )
            return False

        # 设置为活动设备并同步分辨率
        old_active_device = self.active_device
        self.active_device = lower_uri
        sync_success = self._sync_device_resolution(device)
        sync_msg = "分辨率同步成功" if sync_success else "分辨率同步失败"

        self.logger.info(
            f"活动设备切换成功 | " f"原设备: {old_active_device or '无'} | " f"新设备: {device_uri} | " f"{sync_msg}"
        )
        return True

    def sync_active_device_resolution(self) -> bool:
        """
        主动同步当前活动设备的分辨率（供窗口操作后调用）

        Returns:
            同步成功返回True，失败返回False
        """
        active_device = self.get_active_device()
        if not active_device:
            self.logger.debug("主动同步分辨率失败：无活动设备")
            return False

        self.logger.debug(f"开始主动同步活动设备分辨率：{active_device.device_uri}")
        return self._sync_device_resolution(active_device)

    def disconnect_all(self) -> Tuple[int, int]:
        """
        断开所有设备连接并清空列表

        Returns:
            (成功断开数量, 失败断开数量)
        """
        success_count = 0
        fail_count = 0
        total_count = len(self.devices)

        if total_count == 0:
            self.logger.info("无设备需要断开连接")
            return (0, 0)

        self.logger.info(f"开始断开所有设备连接（共{total_count}个设备）")
        for uri, device in list(self.devices.items()):
            if device.is_connected:
                if device.disconnect():
                    success_count += 1
                else:
                    fail_count += 1

        self.devices.clear()
        self.active_device = None
        self.logger.info(
            f"所有设备断开连接完成 | " f"成功: {success_count}个 | " f"失败: {fail_count}个 | " f"总计: {total_count}个"
        )
        return (success_count, fail_count)

    # ======================== 魔术方法 ========================
    def __len__(self) -> int:
        """返回当前设备总数"""
        return len(self.devices)

    def __contains__(self, device_uri: str) -> bool:
        """检查设备是否已存在（支持 in 语法）"""
        return device_uri.lower() in self.devices
