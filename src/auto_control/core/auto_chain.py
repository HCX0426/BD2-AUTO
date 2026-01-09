"""链式调用模块：包含Step类和ChainManager类，实现线性步骤执行"""

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .auto_base import AutoBaseError, AutoConfig, AutoResult, StepExecuteError, VerifyError
from .auto_utils import LogFormatter


@dataclass
class Step:
    """链式调用的步骤对象（支持单步重试+前置验证重试+回退重试）"""

    step_type: str  # 操作类型：template_click/text_click/custom等
    params: dict  # 操作参数
    timeout: float  # 单步超时时间（秒）
    step_retry: int = AutoConfig.DEFAULT_STEP_RETRY  # 单步重试次数
    retry_on_failure: bool = True  # 单步耗尽后是否整体失败
    pre_verify: Optional[dict] = None  # 前置验证配置：{"type": 方法名, "params": 参数}
    pre_verify_retry: int = AutoConfig.DEFAULT_VERIFY_RETRY  # 前置验证的单步重试次数
    back_retry: int = AutoConfig.DEFAULT_BACK_RETRY  # 前置验证失败时回退到上一步的重试次数
    is_back_retried: bool = False  # 标记当前步骤是否已经回退重试过


class ChainManager:
    """链式调用管理器：单步重试优先，耗尽后整体失败"""

    def __init__(self, auto_instance: "Auto"):
        self.auto = auto_instance
        self.config = auto_instance.config
        self.logger = auto_instance.logger
        self.steps: List[Step] = []
        self.total_timeout: float = self.config.DEFAULT_TASK_TIMEOUT  # 步骤链总超时（0=不限制）
        self._current_pre_verify: Optional[dict] = None  # 临时存储当前步骤的前置验证

    # ======================== 链式语法糖 ========================
    def then(self) -> "ChainManager":
        """链式调用衔接符（仅语法糖，无实际逻辑）"""
        return self

    def with_pre_verify(
        self, verify_type: str, pre_verify_retry: int = None, back_retry: int = None, **verify_params
    ) -> "ChainManager":
        """
        为下一个步骤配置前置验证
        :param verify_type: 验证方法名（复用已有方法：wait_element/wait_text/verify等）
        :param pre_verify_retry: 前置验证的单步重试次数
        :param back_retry: 前置验证失败时回退到上一步的重试次数
        :param verify_params: 验证方法的参数（与对应方法完全一致）
        """
        pre_verify_retry = pre_verify_retry or self.config.DEFAULT_VERIFY_RETRY
        back_retry = back_retry or self.config.DEFAULT_BACK_RETRY
        self._current_pre_verify = {
            "type": verify_type,
            "params": verify_params,
            "retry": pre_verify_retry,
            "back_retry": back_retry,
        }
        return self

    # ======================== 重试/超时配置 ========================
    def set_total_timeout(self, timeout: float) -> "ChainManager":
        """设置步骤链总超时时间（秒）"""
        self.total_timeout = timeout
        return self

    # ======================== 链式操作方法 ========================
    def template_click(
        self,
        template: Union[str, List[str]],
        delay: float = None,
        device_uri: Optional[str] = None,
        duration: float = 0.1,
        click_time: int = 1,
        right_click: bool = False,
        roi: Optional[Tuple[int, int, int, int]] = None,
        timeout: float = None,
        step_retry: int = None,
        retry_on_failure: bool = True,
    ) -> "ChainManager":
        """链式调用-模板点击"""
        delay = delay or self.config.CLICK_DELAY
        timeout = timeout or self.config.DEFAULT_WAIT_TIMEOUT
        step_retry = step_retry or self.config.DEFAULT_STEP_RETRY

        self.steps.append(
            Step(
                step_type="template_click",
                params={
                    "template": template,
                    "delay": delay,
                    "device_uri": device_uri,
                    "duration": duration,
                    "click_time": click_time,
                    "right_click": right_click,
                    "roi": roi,
                    "retry": 0,  # 步骤内不重试，由链管理器统一处理
                },
                timeout=timeout,
                step_retry=step_retry,
                retry_on_failure=retry_on_failure,
                pre_verify=self._current_pre_verify,
                pre_verify_retry=(
                    self._current_pre_verify.get("retry", self.config.DEFAULT_VERIFY_RETRY)
                    if self._current_pre_verify
                    else self.config.DEFAULT_VERIFY_RETRY
                ),
                back_retry=(
                    self._current_pre_verify.get("back_retry", self.config.DEFAULT_BACK_RETRY)
                    if self._current_pre_verify
                    else self.config.DEFAULT_BACK_RETRY
                ),
            )
        )
        self._current_pre_verify = None
        return self

    def text_click(
        self,
        text: str,
        click: bool = True,
        lang: str = None,
        roi: Optional[Tuple[int, int, int, int]] = None,
        delay: float = None,
        device_uri: Optional[str] = None,
        duration: float = 0.1,
        click_time: int = 1,
        right_click: bool = False,
        timeout: float = None,
        step_retry: int = None,
        retry_on_failure: bool = True,
    ) -> "ChainManager":
        """链式调用-文字识别点击"""
        delay = delay or self.config.CLICK_DELAY
        timeout = timeout or self.config.DEFAULT_WAIT_TIMEOUT
        step_retry = step_retry or self.config.DEFAULT_STEP_RETRY

        self.steps.append(
            Step(
                step_type="text_click",
                params={
                    "text": text,
                    "click": click,
                    "lang": lang,
                    "roi": roi,
                    "delay": delay,
                    "device_uri": device_uri,
                    "duration": duration,
                    "click_time": click_time,
                    "right_click": right_click,
                    "retry": 0,
                },
                timeout=timeout,
                step_retry=step_retry,
                retry_on_failure=retry_on_failure,
                pre_verify=self._current_pre_verify,
                pre_verify_retry=(
                    self._current_pre_verify.get("retry", self.config.DEFAULT_VERIFY_RETRY)
                    if self._current_pre_verify
                    else self.config.DEFAULT_VERIFY_RETRY
                ),
            )
        )
        self._current_pre_verify = None
        return self

    def click(
        self,
        pos: Tuple[int, int],
        click_time: int = 1,
        delay: float = None,
        device_uri: Optional[str] = None,
        coord_type: str = None,
        timeout: float = None,
        step_retry: int = None,
        retry_on_failure: bool = True,
    ) -> "ChainManager":
        """链式调用-坐标点击"""
        delay = delay or self.config.CLICK_DELAY
        coord_type = coord_type or self.config.DEFAULT_COORD_TYPE
        timeout = timeout or self.config.DEFAULT_WAIT_TIMEOUT
        step_retry = step_retry or self.config.DEFAULT_STEP_RETRY

        self.steps.append(
            Step(
                step_type="click",
                params={
                    "pos": pos,
                    "click_time": click_time,
                    "delay": delay,
                    "device_uri": device_uri,
                    "coord_type": coord_type,
                    "retry": 0,
                },
                timeout=timeout,
                step_retry=step_retry,
                retry_on_failure=retry_on_failure,
                pre_verify=self._current_pre_verify,
                pre_verify_retry=(
                    self._current_pre_verify.get("retry", self.config.DEFAULT_VERIFY_RETRY)
                    if self._current_pre_verify
                    else self.config.DEFAULT_VERIFY_RETRY
                ),
            )
        )
        self._current_pre_verify = None
        return self

    def swipe(
        self,
        start_pos: Tuple[int, int],
        end_pos: Tuple[int, int],
        duration: float = None,
        steps: int = None,
        delay: float = None,
        device_uri: Optional[str] = None,
        coord_type: str = None,
        timeout: float = None,
        step_retry: int = None,
        retry_on_failure: bool = True,
    ) -> "ChainManager":
        """链式调用-滑动"""
        duration = duration or self.config.DEFAULT_SWIPE_DURATION
        steps = steps or self.config.DEFAULT_SWIPE_STEPS
        delay = delay or self.config.CLICK_DELAY
        coord_type = coord_type or self.config.DEFAULT_COORD_TYPE
        timeout = timeout or self.config.DEFAULT_WAIT_TIMEOUT
        step_retry = step_retry or self.config.DEFAULT_STEP_RETRY

        self.steps.append(
            Step(
                step_type="swipe",
                params={
                    "start_pos": start_pos,
                    "end_pos": end_pos,
                    "duration": duration,
                    "steps": steps,
                    "delay": delay,
                    "device_uri": device_uri,
                    "coord_type": coord_type,
                    "retry": 0,
                },
                timeout=timeout,
                step_retry=step_retry,
                retry_on_failure=retry_on_failure,
                pre_verify=self._current_pre_verify,
                pre_verify_retry=(
                    self._current_pre_verify.get("retry", self.config.DEFAULT_VERIFY_RETRY)
                    if self._current_pre_verify
                    else self.config.DEFAULT_VERIFY_RETRY
                ),
            )
        )
        self._current_pre_verify = None
        return self

    def text_input(
        self,
        text: str,
        interval: float = None,
        delay: float = None,
        device_uri: Optional[str] = None,
        timeout: float = None,
        step_retry: int = None,
        retry_on_failure: bool = True,
    ) -> "ChainManager":
        """链式调用-文本输入"""
        interval = interval or self.config.TEXT_INPUT_INTERVAL
        delay = delay or self.config.CLICK_DELAY
        timeout = timeout or self.config.DEFAULT_WAIT_TIMEOUT
        step_retry = step_retry or self.config.DEFAULT_STEP_RETRY

        self.steps.append(
            Step(
                step_type="text_input",
                params={"text": text, "interval": interval, "delay": delay, "device_uri": device_uri, "retry": 0},
                timeout=timeout,
                step_retry=step_retry,
                retry_on_failure=retry_on_failure,
                pre_verify=self._current_pre_verify,
                pre_verify_retry=(
                    self._current_pre_verify.get("retry", self.config.DEFAULT_VERIFY_RETRY)
                    if self._current_pre_verify
                    else self.config.DEFAULT_VERIFY_RETRY
                ),
            )
        )
        self._current_pre_verify = None
        return self

    def custom_step(
        self,
        func: Callable[[], bool],
        timeout: float = None,
        step_retry: int = None,
        retry_on_failure: bool = True,
    ) -> "ChainManager":
        """
        链式调用-自定义步骤（支持多分支/条件判断/任意逻辑）
        :param func: 自定义函数（返回bool表示是否成功）
        :param timeout: 单步超时
        :param step_retry: 单步重试次数
        :param retry_on_failure: 失败是否整体失败
        """
        timeout = timeout or self.config.DEFAULT_WAIT_TIMEOUT
        step_retry = step_retry or self.config.DEFAULT_STEP_RETRY

        self.steps.append(
            Step(
                step_type="custom",
                params={"func": func},
                timeout=timeout,
                step_retry=step_retry,
                retry_on_failure=retry_on_failure,
                pre_verify=self._current_pre_verify,
                pre_verify_retry=(
                    self._current_pre_verify.get("retry", self.config.DEFAULT_VERIFY_RETRY)
                    if self._current_pre_verify
                    else self.config.DEFAULT_VERIFY_RETRY
                ),
            )
        )
        self._current_pre_verify = None
        return self

    # ======================== 核心执行逻辑 ========================
    def execute(self) -> AutoResult:
        """
        执行逻辑：
        1. 前置验证失败 → 重试验证（直到验证重试耗尽）→ 验证仍失败则回退到上一步重试
        2. 步骤执行失败 → 重试当前步骤（直到单步重试耗尽）→ 步骤仍失败则整体失败
        3. 回退重试时，重置到上一个步骤重新执行
        """
        start_time = time.time()
        step_results: List[AutoResult] = []

        # 总超时检查
        if self._check_total_timeout(start_time):
            return AutoResult.fail_result(
                error_msg=f"步骤链总超时（{self.total_timeout}秒）", elapsed_time=time.time() - start_time
            )

        # 逐个执行步骤，使用while循环替代for循环，支持回退重试
        idx = 0
        while idx < len(self.steps):
            step = self.steps[idx]
            step_idx = idx + 1
            step_name = step.step_type
            step_start = time.time()
            self.logger.info(f"\n--- 执行步骤 {step_idx}/{len(self.steps)}: {step_name} ---\n")

            # 总超时检查
            if self._check_total_timeout(start_time):
                return AutoResult.fail_result(
                    error_msg=f"步骤链总超时（{self.total_timeout}秒）", elapsed_time=time.time() - start_time
                )

            # 步骤1：执行前置验证（带单步重试）
            verify_success = True
            if step.pre_verify:
                try:
                    verify_success = self._execute_pre_verify(step)
                except VerifyError as e:
                    error_msg = f"步骤{step_idx}前置验证异常：{str(e)}"
                    self.logger.error(error_msg)
                    verify_success = False

            if not verify_success:
                error_msg = f"步骤{step_idx}前置验证重试{step.pre_verify_retry}次后仍失败"
                self.logger.error(error_msg)

                # 检查是否可以回退到上一步
                if idx > 0 and step.back_retry > 0 and not step.is_back_retried:
                    # 可以回退，执行回退逻辑
                    self.logger.info(
                        f"尝试回退到步骤{idx}/{len(self.steps)}重新执行，剩余回退次数：{step.back_retry-1}"
                    )

                    # 重置当前步骤的回退状态
                    step.is_back_retried = True
                    step.back_retry -= 1

                    # 清空已保存的当前步骤及后续步骤的结果
                    if idx < len(step_results):
                        step_results = step_results[:idx]

                    # 回退到上一个步骤
                    idx -= 1
                    continue

                # 无法回退，返回失败结果
                if step.retry_on_failure:
                    return AutoResult.fail_result(error_msg=error_msg, elapsed_time=time.time() - start_time)
                else:
                    # 允许跳过，继续执行下一个步骤
                    self.logger.warning(f"步骤{step_idx}失败，但允许跳过，继续执行下一个步骤")
                    idx += 1
                    continue

            if step.pre_verify:
                self.logger.info("前置验证通过")

            # 步骤2：执行当前步骤（带单步重试）
            try:
                step_success, step_result = self._execute_step_with_retry(step, step_start)
            except StepExecuteError as e:
                error_msg = f"步骤{step_idx}执行异常：{str(e)}"
                self.logger.error(error_msg)
                if step.retry_on_failure:
                    return AutoResult.fail_result(error_msg=error_msg, elapsed_time=time.time() - start_time)
                else:
                    # 允许跳过，继续执行下一个步骤
                    self.logger.warning(f"步骤{step_idx}失败，但允许跳过，继续执行下一个步骤")
                    idx += 1
                    continue

            if not step_success:
                error_msg = f"步骤{step_idx}({step_name})重试{step.step_retry}次后仍失败"
                self.logger.error(error_msg)
                if step.retry_on_failure:
                    return AutoResult.fail_result(
                        error_msg=error_msg, elapsed_time=time.time() - start_time, retry_count=step.step_retry
                    )
                else:
                    # 允许跳过，继续执行下一个步骤
                    self.logger.warning(f"步骤{step_idx}失败，但允许跳过，继续执行下一个步骤")
                    idx += 1
                    continue

            # 步骤执行成功，保存结果，继续执行下一个步骤
            if idx < len(step_results):
                step_results[idx] = step_result
            else:
                step_results.append(step_result)
            self.logger.info(f"步骤{step_idx}执行成功，耗时: {time.time()-step_start:.1f}秒")

            # 重置回退状态，准备执行下一个步骤
            step.is_back_retried = False
            idx += 1

        # 所有步骤执行成功
        total_elapsed = time.time() - start_time
        return AutoResult.success_result(data=[r.data for r in step_results], elapsed_time=total_elapsed, retry_count=0)

    # ======================== 辅助方法 ========================
    def _execute_pre_verify(self, step: Step) -> bool:
        """执行前置验证，失败时重试（直到验证重试耗尽）"""
        verify_type = step.pre_verify["type"]
        verify_params = step.pre_verify["params"]
        max_retry = step.pre_verify_retry

        # 验证方法存在性检查
        if not hasattr(self.auto, verify_type):
            raise VerifyError(f"无效的验证方法：{verify_type}")

        for attempt in range(max_retry + 1):
            # 中断检查
            if self.auto.check_should_stop():
                raise VerifyError("前置验证被中断")

            attempt_idx = attempt + 1
            self.logger.info(f"前置验证第{attempt_idx}/{max_retry+1}次尝试")
            try:
                verify_method = getattr(self.auto, verify_type)
                verify_result = verify_method(**verify_params)

                if verify_result.success:
                    return True
                self.logger.warning(f"前置验证失败：{verify_result.error_msg}")
            except AutoBaseError as e:
                self.logger.error(f"前置验证异常：{str(e)}", exc_info=True)
            except Exception as e:
                self.logger.error(f"前置验证未知异常：{str(e)}", exc_info=True)

            # 最后一次重试不等待
            if attempt < max_retry:
                self.auto.sleep(0.5)

        return False

    def _execute_step_with_retry(self, step: Step, step_start: float) -> Tuple[bool, Optional[AutoResult]]:
        """执行单个步骤，失败时重试（直到单步重试耗尽）"""
        max_retry = step.step_retry
        step_timeout = step.timeout

        for attempt in range(max_retry + 1):
            # 中断检查
            if self.auto.check_should_stop():
                raise StepExecuteError("步骤执行被中断")

            # 超时检查
            if time.time() - step_start > step_timeout:
                raise StepExecuteError(f"步骤超时（{step_timeout}秒）")

            attempt_idx = attempt + 1
            self.logger.info(f"步骤第{attempt_idx}/{max_retry+1}次尝试")
            step_result = self._execute_single_step(step)

            if step_result.success:
                return True, step_result
            self.logger.warning(f"步骤执行失败：{step_result.error_msg}")

            # 最后一次重试不等待
            if attempt < max_retry:
                self.auto.sleep(0.5)

        return False, step_result

    def _execute_single_step(self, step: Step) -> AutoResult:
        """执行单个步骤（无重试）"""
        try:
            if step.step_type == "template_click":
                return self.auto.template_click(**step.params)
            elif step.step_type == "text_click":
                return self.auto.text_click(**step.params)
            elif step.step_type == "click":
                return self.auto.click(**step.params)
            elif step.step_type == "swipe":
                return self.auto.swipe(**step.params)
            elif step.step_type == "text_input":
                return self.auto.text_input(**step.params)
            elif step.step_type == "custom":
                func = step.params["func"]
                result = func()
                if result:
                    return AutoResult.success_result(data=result)
                else:
                    return AutoResult.fail_result(error_msg="自定义步骤执行失败")
            else:
                raise StepExecuteError(f"不支持的步骤类型: {step.step_type}")
        except AutoBaseError as e:
            return AutoResult.fail_result(error_msg=str(e))
        except Exception as e:
            return AutoResult.fail_result(error_msg=f"步骤执行异常: {str(e)}")

    def _check_total_timeout(self, start_time: float) -> bool:
        """检查步骤链总超时"""
        if self.total_timeout <= 0:
            return False
        elapsed = time.time() - start_time
        return elapsed >= self.total_timeout
