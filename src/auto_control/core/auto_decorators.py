"""装饰器模块：包含重试/中断检查等通用装饰器"""

import time
from functools import wraps
from typing import Any, Callable, Dict, Optional

from .auto_base import AutoBaseError, AutoConfig, AutoResult, DeviceError, VerifyError


def with_retry_and_check(func: Callable) -> Callable:
    """通用重试+前置检查装饰器：抽离重复的重试/中断/设备/验证逻辑"""

    @wraps(func)
    def wrapper(self, *args, **kwargs) -> AutoResult:
        # 提取通用参数（兼容原有调用）
        config: AutoConfig = self.config
        
        # 获取重试次数：优先从kwargs获取，否则从settings_manager获取，最后使用默认值
        retry = kwargs.get("retry")
        
        # 检查是否有settings_manager，并且支持获取重试次数
        if retry is None and hasattr(self, "auto") and hasattr(self.auto, "settings_manager") and self.auto.settings_manager is not None:
            retry = self.auto.settings_manager.get_setting("retry_count", config.DEFAULT_OPERATION_RETRY)
        
        # 使用默认值作为最后的回退
        if retry is None:
            retry = config.DEFAULT_OPERATION_RETRY
        
        delay = kwargs.get("delay", config.CLICK_DELAY)
        device_uri = kwargs.get("device_uri")
        verify = kwargs.get("verify")
        total_start_time = time.time()
        actual_retry_count = 0

        # 通用重试循环
        for attempt in range(retry + 1):
            # 1. 中断检查（最高优先级）
            if self.auto.check_should_stop():
                elapsed = time.time() - total_start_time
                self.logger.debug(f"[{func.__name__}] 任务被中断（尝试{attempt+1}）")
                return AutoResult.fail_result(
                    error_msg=f"{func.__name__}任务被中断",
                    elapsed_time=elapsed,
                    retry_count=actual_retry_count,
                    is_interrupted=True,
                )

            # 2. 执行前延迟
            delay_result = self.delay_manager.apply_delay(delay, self.auto.stop_event)
            if not delay_result.success:
                actual_retry_count += 1
                continue

            # 3. 获取设备（核心依赖）
            try:
                # 优化：如果device_uri为空，直接使用active_device，避免不必要的错误日志
                if device_uri and str(device_uri).strip():
                    device = self.auto.device_manager.get_device(device_uri)
                else:
                    device = None
                
                # 如果指定设备不存在，使用active_device
                if not device:
                    device = self.auto.device_manager.get_active_device()
                
                if not device:
                    raise DeviceError("未找到可用设备")
            except DeviceError as e:
                actual_retry_count += 1
                self.logger.warning(f"[{func.__name__}] 尝试{attempt+1}：{str(e)}，重试")
                continue

            # 4. 执行核心逻辑（传入device参数）
            kwargs["_device"] = device
            kwargs["_attempt"] = attempt
            try:
                result = func(self, *args, **kwargs)
            except AutoBaseError as e:
                result = AutoResult.fail_result(error_msg=str(e))
            except Exception as e:
                result = AutoResult.fail_result(error_msg=f"{func.__name__}执行异常：{str(e)}")

            # 5. 核心逻辑执行失败，继续重试
            if not result.success:
                actual_retry_count += 1
                self.logger.warning(
                    f"[{func.__name__}] 尝试{attempt+1}：{result.error_msg}，重试（剩余{retry-attempt}次）"
                )
                continue

            # 6. 无需验证，直接返回成功
            if not verify:
                elapsed = time.time() - total_start_time
                return AutoResult.success_result(data=result.data, elapsed_time=elapsed, retry_count=actual_retry_count)

            # 7. 执行验证逻辑
            verify_start = time.time()
            try:
                verify_result = self.auto.verify(
                    verify_type=verify.get("type"),
                    target=verify.get("target"),
                    timeout=verify.get("timeout", config.DEFAULT_WAIT_TIMEOUT),
                    roi=verify.get("roi"),
                )
            except VerifyError as e:
                verify_result = AutoResult.fail_result(error_msg=str(e))

            verify_elapsed = time.time() - verify_start

            # 8. 验证成功
            if verify_result.success:
                total_elapsed = time.time() - total_start_time
                self.logger.info(f"[{func.__name__}] 验证成功，总耗时{total_elapsed:.1f}秒")
                return AutoResult.success_result(
                    data=result.data, elapsed_time=total_elapsed, retry_count=actual_retry_count
                )
            # 9. 验证失败，继续重试
            else:
                actual_retry_count += 1
                self.logger.warning(
                    f"[{func.__name__}] 尝试{attempt+1}：验证失败（{verify_result.error_msg}），重试（剩余{retry-attempt}次）"
                )

        # 重试耗尽，返回失败
        elapsed = time.time() - total_start_time
        error_msg = f"{func.__name__}已达最大重试次数{retry}，操作失败"
        self.logger.error(error_msg)
        return AutoResult.fail_result(error_msg=error_msg, elapsed_time=elapsed, retry_count=actual_retry_count)

    return wrapper
