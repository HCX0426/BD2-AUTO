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
        """等待条件满足，支持超时和中断检查"""
        timeout = timeout or self.config.DEFAULT_WAIT_TIMEOUT
        start_time = time.time()
        self.logger.info(f"[等待] {desc}，超时: {timeout}秒")

        while True:
            # 中断检查（最高优先级）
            if self.auto.check_should_stop():
                elapsed = time.time() - start_time
                self.logger.info(f"[等待中断] {desc}")
                return AutoResult.fail_result(error_msg=f"{desc}被中断", elapsed_time=elapsed, is_interrupted=True)

            # 超时检查
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                self.logger.warning(f"[等待超时] {desc}（{timeout}秒）")
                return AutoResult.fail_result(error_msg=f"等待{desc}超时（{timeout}秒）", elapsed_time=elapsed)

            # 条件满足
            if condition():
                self.logger.info(f"[等待成功] {desc}，耗时: {elapsed:.1f}秒")
                return AutoResult.success_result(data=True, elapsed_time=elapsed)

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
        self.logger.info(f"[验证] {verify_type} - {target}，超时: {timeout}秒")

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

    def _wait_with_condition(
        self, condition_func: Callable[[], bool], desc: str, timeout: int, start_time: float, result: Any = None
    ) -> AutoResult:
        """通用等待方法，减少代码重复"""
        wait_result = self.wait_for(condition_func, timeout, desc=desc)
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
