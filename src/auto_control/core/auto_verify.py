"""验证模块：包含等待、元素检查、文本验证等核心逻辑"""

import time
from typing import Any, Callable, List, Optional, Tuple, Union

from .auto_base import AutoBaseError, AutoConfig, AutoResult, VerifyError
from .auto_utils import DelayManager, LogFormatter


class VerifyHandler:
    """验证/等待处理器（封装所有验证相关逻辑）"""

    def __init__(self, auto_instance, config: AutoConfig):
        self.auto = auto_instance
        self.config = config
        self.logger = auto_instance.logger
        self.stop_event = auto_instance.stop_event
        self.delay_manager = DelayManager()
        self.device_handler = auto_instance.device_handler

    def wait_for(
        self, condition: Callable[[], bool], timeout: int = None, interval: float = 0.5, desc: str = "条件验证"
    ) -> AutoResult:
        """等待条件满足，支持超时和中断检查，窗口未置顶时不计入超时时间"""
        timeout = timeout or self.config.DEFAULT_WAIT_TIMEOUT
        start_time = time.time()
        productive_start_time = start_time  # 有效等待开始时间（仅窗口有效时计数）
        self.logger.info(f"[等待] {desc}，超时: {timeout}秒")

        # 获取当前活动设备用于窗口状态检查
        active_device = self.device_handler.get_device()

        while True:
            # 中断检查（最高优先级）
            if self.auto.check_should_stop():
                total_elapsed = time.time() - start_time
                self.logger.info(f"[等待中断] {desc}")
                return AutoResult.fail_result(
                    error_msg=f"{desc}被中断", elapsed_time=total_elapsed, is_interrupted=True
                )

            # 检查窗口是否处于有效状态
            window_valid = self._check_window_topmost(active_device)

            # 窗口有效时更新有效等待开始时间
            if window_valid:
                current_time = time.time()
                # 超时检查（仅在窗口有效时计数）
                productive_elapsed = current_time - productive_start_time
                if productive_elapsed >= timeout:
                    total_elapsed = current_time - start_time
                    self.logger.warning(f"[等待超时] {desc}（{timeout}秒）")
                    return AutoResult.fail_result(
                        error_msg=f"等待{desc}超时（{timeout}秒）", elapsed_time=total_elapsed
                    )

                # 窗口有效时才执行条件检查
                if condition():
                    total_elapsed = time.time() - start_time
                    self.logger.info(f"[等待成功] {desc}，耗时: {total_elapsed:.1f}秒")
                    return AutoResult.success_result(data=True, elapsed_time=total_elapsed)
            else:
                # 窗口无效时重置有效等待开始时间，不计入超时
                productive_start_time = time.time()
                self.logger.debug(f"窗口无效，跳过条件检查，当前时间: {time.time()}")

            # 等待间隔
            self.delay_manager.apply_delay(interval, self.stop_event)

    def _verify_condition(
        self, verify_type: str, target: Union[str, List[str]], roi: Optional[Tuple[int, int, int, int]]
    ) -> bool:
        """验证条件判断函数"""
        if verify_type == "exist":
            return self.check_element_exist(target, roi=roi, wait_timeout=0).success
        elif verify_type == "disappear":
            return not self.check_element_exist(target, roi=roi, wait_timeout=0).success
        elif verify_type == "text":
            return self.auto.text_click(target, click=False, roi=roi, retry=0).success
        else:
            raise VerifyError(f"无效的验证类型: {verify_type}")

    def verify(
        self,
        verify_type: str,
        target: Union[str, List[str]],
        timeout: int = None,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> AutoResult:
        """统一的屏幕验证方法"""
        timeout = timeout or self.config.DEFAULT_WAIT_TIMEOUT
        start_time = time.time()

        # 使用提取的独立方法作为条件
        def condition() -> bool:
            return self._verify_condition(verify_type, target, roi)

        # 执行等待并处理结果
        wait_result = self.wait_for(condition, timeout, desc=f"{verify_type} - {target}")
        if wait_result.success and not wait_result.is_interrupted:
            return AutoResult.success_result(data=True, elapsed_time=wait_result.elapsed_time)
        elif wait_result.is_interrupted:
            return AutoResult.fail_result(
                error_msg=f"验证{verify_type}-{target}被中断",
                elapsed_time=wait_result.elapsed_time,
                is_interrupted=True,
            )
        else:
            return AutoResult.fail_result(
                error_msg=wait_result.error_msg,
                elapsed_time=wait_result.elapsed_time,
                is_interrupted=wait_result.is_interrupted,
            )

    def _check_element_once(
        self,
        template_name: Union[str, List[str]],
        delay: float,
        device_uri: Optional[str] = None,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> AutoResult:
        """单次检查元素是否存在"""
        # 中断检查
        if self.auto.check_should_stop():
            self.logger.debug("检查元素任务被中断")
            return AutoResult.fail_result(error_msg="检查元素任务被中断", is_interrupted=True)

        # 执行延迟
        self.delay_manager.apply_delay(delay, self.stop_event)

        # 获取设备
        try:
            device = self.device_handler.get_device(device_uri)
        except AutoBaseError as e:
            return AutoResult.fail_result(error_msg=str(e))

        # 拼接日志信息
        templates = [template_name] if isinstance(template_name, str) else template_name
        params_info = []
        if roi:
            params_info.append(f"基准ROI: {roi}")
        params_info.append(f"客户区尺寸: {self.auto.display_context.client_logical_res}")
        if len(templates) > 1:
            params_info.append(f"模板数量: {len(templates)}")
        param_log = f" | {', '.join(params_info)}" if params_info else ""

        self.logger.debug(f"检查元素请求: {templates}{param_log}")

        # 执行检查
        try:
            result = device.exists(templates, roi=roi)
            if getattr(device, "last_error", ""):
                self.logger.warning(f"检查元素异常: {device.last_error}")

            if result:
                self.logger.info(f"找到元素 {templates}{param_log}，中心点: {result}")
                return AutoResult.success_result(data=result)
            else:
                return AutoResult.fail_result(error_msg=f"未找到元素 {templates}{param_log}")
        except Exception as e:
            error_msg = f"检查元素异常: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return AutoResult.fail_result(error_msg=error_msg)

    def check_element_exist(
        self,
        template_name: Union[str, List[str]],
        delay: float = None,
        device_uri: Optional[str] = None,
        roi: Optional[Tuple[int, int, int, int]] = None,
        wait_timeout: int = 0,
    ) -> AutoResult:
        """检查模板元素是否存在并返回坐标"""
        start_time = time.time()
        delay = delay or self.config.CHECK_ELEMENT_DELAY

        if wait_timeout > 0:
            result = None

            def condition_func():
                nonlocal result
                check_result = self._check_element_once(template_name, delay, device_uri, roi)
                result = check_result
                return check_result.success

            return self._wait_with_condition(
                condition_func=condition_func,
                desc=f"等待元素 {template_name} 出现",
                timeout=wait_timeout,
                start_time=start_time,
                result=result,
            )
        else:
            return self._check_element_once(template_name, delay, device_uri, roi)

    def wait_element(
        self, template: Union[str, List[str]], timeout: int = None, roi: Optional[Tuple[int, int, int, int]] = None
    ) -> AutoResult:
        """等待元素出现并返回坐标"""
        timeout = timeout or self.config.DEFAULT_WAIT_TIMEOUT
        return self.check_element_exist(template, roi=roi, wait_timeout=timeout)

    def _check_window_topmost(self, device) -> bool:
        """检查窗口是否在前台且可见，用于控制层等待逻辑"""
        try:
            import win32con
            import win32gui

            from src.auto_control.devices.windows import WindowsDevice

            if isinstance(device, WindowsDevice):
                # 1. 检查窗口是否存在
                if not win32gui.IsWindow(device.hwnd):
                    device.logger.debug(f"窗口不存在，句柄: {device.hwnd}")
                    return False  # 窗口不存在时应该停止执行，避免无效等待

                # 2. 检查窗口是否可见
                if not win32gui.IsWindowVisible(device.hwnd):
                    device.logger.warning("窗口不可见，控制层进入无限等待")
                    return False

                # 3. 检查窗口是否最小化
                if win32gui.IsIconic(device.hwnd):
                    device.logger.warning("窗口被最小化，控制层进入无限等待")
                    return False

                # 4. 检查窗口是否在前台（关键：窗口被遮挡时不在前台，应该进入无限等待）
                current_foreground = win32gui.GetForegroundWindow()
                if current_foreground != device.hwnd:
                    device.logger.warning(
                        f"窗口不在前台，当前前台句柄: {current_foreground}，目标句柄: {device.hwnd}，控制层进入无限等待"
                    )
                    return False
            return True
        except Exception as e:
            device.logger.error(f"检查窗口状态异常: {e}")
            return True  # 非Windows设备或异常时默认继续执行

    def _wait_with_condition(
        self, condition_func: Callable[[], bool], desc: str, timeout: int, start_time: float, result: Any = None
    ) -> AutoResult:
        """通用等待方法，减少代码重复，支持窗口未置顶检测"""
        # 获取当前活动设备
        active_device = self.device_handler.get_device()

        def enhanced_condition() -> bool:
            # 1. 检查窗口置顶状态
            if not self._check_window_topmost(active_device):
                return False
            # 2. 执行原始条件检查
            return condition_func()

        wait_result = self.wait_for(enhanced_condition, timeout, desc=desc)
        elapsed = time.time() - start_time

        if wait_result.success and not wait_result.is_interrupted:
            return AutoResult.success_result(data=result.data if result else True, elapsed_time=elapsed)
        elif wait_result.is_interrupted:
            return AutoResult.fail_result(
                error_msg=f"{desc}被中断",
                elapsed_time=elapsed,
                is_interrupted=True,
            )
        else:
            return AutoResult.fail_result(
                error_msg=wait_result.error_msg,
                elapsed_time=elapsed,
                is_interrupted=wait_result.is_interrupted,
            )

    def wait_text(self, text: str, timeout: int = None, roi: Optional[Tuple[int, int, int, int]] = None) -> AutoResult:
        """等待文本出现并返回坐标"""
        timeout = timeout or self.config.DEFAULT_WAIT_TIMEOUT
        start_time = time.time()
        result = None

        def condition_func():
            nonlocal result
            check_result = self.auto.text_click(text, click=False, roi=roi, retry=0)
            result = check_result
            return check_result.success

        return self._wait_with_condition(
            condition_func=condition_func,
            desc=f"等待文本 '{text}' 出现",
            timeout=timeout,
            start_time=start_time,
            result=result,
        )
