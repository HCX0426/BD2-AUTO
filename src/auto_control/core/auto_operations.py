"""操作模块：包含点击、滑动、输入、按键等核心操作方法"""

import time
from typing import Any, List, Optional, Tuple, Union

from .auto_base import AutoBaseError, AutoConfig, AutoResult, CoordinateError, DeviceError, VerifyError
from .auto_decorators import with_retry_and_check
from .auto_utils import DelayManager, LogFormatter


class OperationHandler:
    """操作处理器（封装所有用户交互操作）"""

    def __init__(self, auto_instance, config: AutoConfig):
        self.auto = auto_instance
        self.config = config
        self.logger = auto_instance.logger
        self.delay_manager = DelayManager()
        self.device_handler = auto_instance.device_handler
        self.ocr_processor = auto_instance.ocr_processor
        self.image_processor = auto_instance.image_processor

    @with_retry_and_check
    def click(
        self,
        pos: Tuple[int, int],
        click_time: int = 1,
        delay: float = None,
        device_uri: Optional[str] = None,
        coord_type: str = None,
        verify: Optional[dict] = None,
        retry: int = None,
        _device: Optional[Any] = None,
        _attempt: int = 0,
    ) -> AutoResult:
        """坐标点击操作（自动进行坐标转换）"""
        # 参数默认值
        delay = delay or self.config.CLICK_DELAY
        coord_type = coord_type or self.config.DEFAULT_COORD_TYPE
        retry = retry or self.config.DEFAULT_OPERATION_RETRY

        # 坐标类型转换
        try:
            device_coord_type = self.device_handler.get_coord_type_enum(coord_type)
        except CoordinateError as e:
            return AutoResult.fail_result(error_msg=str(e))

        # 坐标类型名称格式化
        coord_type_str = LogFormatter.format_coord_type(coord_type)

        # 执行点击
        try:
            result = _device.click((pos[0], pos[1]), click_time=click_time, coord_type=device_coord_type)
            if not result:
                error_msg = getattr(_device, "last_error", "") or f"坐标{coord_type_str}{pos}点击失败"
                raise DeviceError(error_msg)
        except Exception as e:
            return AutoResult.fail_result(error_msg=str(e))

        # 点击后等待
        self.delay_manager.apply_delay(self.config.AFTER_CLICK_DELAY, self.auto.stop_event)
        self.logger.info(f"点击成功: {coord_type_str}{pos} | 点击次数{click_time}")
        return AutoResult.success_result(data=pos)

    @with_retry_and_check
    def key_press(
        self,
        key: str,
        duration: float = None,
        delay: float = None,
        device_uri: Optional[str] = None,
        verify: Optional[dict] = None,
        retry: int = None,
        _device: Optional[Any] = None,
        _attempt: int = 0,
    ) -> AutoResult:
        """按键操作（支持系统按键和普通字符键）"""
        # 参数默认值
        duration = duration or self.config.KEY_DURATION
        delay = delay or self.config.CLICK_DELAY
        retry = retry or self.config.DEFAULT_OPERATION_RETRY

        # 执行按键
        try:
            result = _device.key_press(key, duration=duration)
            if not result:
                error_msg = getattr(_device, "last_error", "") or f"按键 {key} 失败"
                raise DeviceError(error_msg)
        except Exception as e:
            return AutoResult.fail_result(error_msg=str(e))

        # 按键后等待
        self.delay_manager.apply_delay(self.config.AFTER_CLICK_DELAY, self.auto.stop_event)
        self.logger.info(f"按键成功: {key} | 按住时长{duration}s")
        return AutoResult.success_result(data=key)

    @with_retry_and_check
    def template_click(
        self,
        template: Union[str, List[str]],
        delay: float = None,
        device_uri: Optional[str] = None,
        duration: float = 0.1,
        click_time: int = 1,
        right_click: bool = False,
        roi: Optional[Tuple[int, int, int, int]] = None,
        verify: Optional[dict] = None,
        retry: int = None,
        _device: Optional[Any] = None,
        _attempt: int = 0,
    ) -> AutoResult:
        """模板匹配点击（支持多模板、ROI筛选，自动适配分辨率）"""
        # 参数默认值
        delay = delay or self.config.CLICK_DELAY
        retry = retry or self.config.DEFAULT_OPERATION_RETRY

        # 模板/ROI信息拼接
        roi_info = LogFormatter.format_roi(roi)
        template_info = LogFormatter.format_template(template)
        self.logger.info(f"[模板点击] {template_info}{roi_info}，尝试: {_attempt + 1}")

        # 执行模板点击
        try:
            result = _device.click(
                pos=template, duration=duration, click_time=click_time, right_click=right_click, roi=roi
            )
            if not result:
                error_msg = getattr(_device, "last_error", "") or f"模板 {template_info} 点击失败"
                raise DeviceError(error_msg)
        except Exception as e:
            return AutoResult.fail_result(error_msg=str(e))

        # 点击后等待
        self.delay_manager.apply_delay(self.config.AFTER_CLICK_DELAY, self.auto.stop_event)
        self.logger.info(f"[点击成功] {template_info}{roi_info} | 右键={right_click}")
        return AutoResult.success_result(data=result)

    @with_retry_and_check
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
        verify: Optional[dict] = None,
        retry: int = None,
        _device: Optional[Any] = None,
        _attempt: int = 0,
    ) -> AutoResult:
        """OCR文本识别并点击（支持ROI筛选，自动坐标适配）"""
        # 参数默认值
        delay = delay or self.config.CLICK_DELAY
        retry = retry or self.config.DEFAULT_OPERATION_RETRY

        # 日志信息格式化
        roi_info = LogFormatter.format_roi(roi)
        self.logger.info(f"[文本点击] '{text}'{roi_info}，尝试: {_attempt + 1}")

        # 截图
        try:
            screen = _device.capture_screen()
            if screen is None:
                raise DeviceError("[文本点击] 截图失败")
        except Exception as e:
            return AutoResult.fail_result(error_msg=str(e))

        # OCR识别
        try:
            ocr_result = self.ocr_processor.find_text_position(image=screen, target_text=text, lang=lang, region=roi)
            if not ocr_result:
                raise VerifyError(f"[文本识别失败] 未识别到文本 '{text}'")
        except VerifyError as e:
            self.logger.warning(str(e))
            return AutoResult.fail_result(error_msg=str(e))
        except Exception as e:
            return AutoResult.fail_result(error_msg=f"OCR识别异常：{str(e)}")

        # 计算点击坐标
        x_log, y_log, w_log, h_log = ocr_result
        click_center = (x_log + w_log // 2, y_log + h_log // 2)
        is_fullscreen = self.auto.coord_transformer.is_fullscreen

        self.logger.info(
            f"[识别成功] '{text}' | 模式: {'全屏' if is_fullscreen else '窗口'} | "
            f"坐标: ({x_log},{y_log},{w_log},{h_log}) | 中心点: {click_center}"
        )

        # 执行点击
        if click:
            try:
                click_result = _device.click(
                    pos=click_center,
                    duration=duration,
                    click_time=click_time,
                    right_click=right_click,
                    coord_type=self.device_handler.get_coord_type_enum("LOGICAL"),
                )
                if not click_result:
                    error_msg = getattr(_device, "last_error", "") or "[文本点击执行失败]"
                    raise DeviceError(error_msg)
            except Exception as e:
                return AutoResult.fail_result(error_msg=str(e))

        # 识别/点击后等待
        self.delay_manager.apply_delay(self.config.AFTER_CLICK_DELAY, self.auto.stop_event)
        return AutoResult.success_result(data=click_center)

    @with_retry_and_check
    def swipe(
        self,
        start_pos: Tuple[int, int],
        end_pos: Tuple[int, int],
        duration: float = None,
        steps: int = None,
        delay: float = None,
        device_uri: Optional[str] = None,
        coord_type: str = None,
        verify: Optional[dict] = None,
        retry: int = None,
        _device: Optional[Any] = None,
        _attempt: int = 0,
    ) -> AutoResult:
        """滑动操作（支持多种坐标类型，自动平滑移动）"""
        # 参数默认值
        duration = duration or self.config.DEFAULT_SWIPE_DURATION
        steps = steps or self.config.DEFAULT_SWIPE_STEPS
        delay = delay or self.config.CLICK_DELAY
        coord_type = coord_type or self.config.DEFAULT_COORD_TYPE
        retry = retry or self.config.DEFAULT_OPERATION_RETRY

        # 坐标格式检查
        if not (isinstance(start_pos, (tuple, list)) and len(start_pos) == 2):
            error_msg = f"滑动失败: 起始坐标格式无效（{start_pos}）"
            self.logger.error(error_msg)
            return AutoResult.fail_result(error_msg=error_msg)

        if not (isinstance(end_pos, (tuple, list)) and len(end_pos) == 2):
            error_msg = f"滑动失败: 结束坐标格式无效（{end_pos}）"
            self.logger.error(error_msg)
            return AutoResult.fail_result(error_msg=error_msg)

        # 坐标类型转换
        try:
            coord_type_enum = self.device_handler.get_coord_type_enum(coord_type)
        except CoordinateError as e:
            return AutoResult.fail_result(error_msg=str(e))

        coord_type_name = LogFormatter.format_coord_type(coord_type)

        # 逻辑坐标范围检查
        if coord_type_enum.name == "LOGICAL":
            client_w, client_h = self.auto.display_context.client_logical_res
            sx, sy = start_pos
            ex, ey = end_pos
            if not (0 <= sx <= client_w and 0 <= sy <= client_h):
                self.logger.warning(f"起始坐标超出客户区范围: {start_pos} | 客户区: {client_w}x{client_h}")
            if not (0 <= ex <= client_w and 0 <= ey <= client_h):
                self.logger.warning(f"结束坐标超出客户区范围: {end_pos} | 客户区: {client_w}x{client_h}")

        # 执行滑动
        try:
            result = _device.swipe(
                start_x=start_pos[0],
                start_y=start_pos[1],
                end_x=end_pos[0],
                end_y=end_pos[1],
                duration=duration,
                steps=steps,
                coord_type=coord_type_enum,
            )
            if not result:
                error_msg = getattr(_device, "last_error", "") or "滑动执行失败"
                raise DeviceError(error_msg)
        except Exception as e:
            return AutoResult.fail_result(error_msg=str(e))

        self.logger.info(f"滑动成功: 从{start_pos}到{end_pos} | 类型:{coord_type_name} | 时长{duration}s")
        return AutoResult.success_result(data=(start_pos, end_pos))

    @with_retry_and_check
    def text_input(
        self,
        text: str,
        interval: float = None,
        delay: float = None,
        device_uri: Optional[str] = None,
        verify: Optional[dict] = None,
        retry: int = None,
        _device: Optional[Any] = None,
        _attempt: int = 0,
    ) -> AutoResult:
        """文本输入（优先粘贴模式，粘贴失败时自动降级为逐字符输入）"""
        # 参数默认值
        interval = interval or self.config.TEXT_INPUT_INTERVAL
        delay = delay or self.config.CLICK_DELAY
        retry = retry or self.config.DEFAULT_OPERATION_RETRY

        # 日志脱敏（长文本只显示前30字符）
        log_text = text[:30] + "..." if len(text) > 30 else text
        self.logger.info(f"[文本输入] 尝试{_attempt + 1}：{log_text}")

        # 执行文本输入
        try:
            result = _device.text_input(text, interval=interval)
            if not result:
                error_msg = getattr(_device, "last_error", "") or f"输入文本 '{log_text}' 失败"
                raise DeviceError(error_msg)
        except Exception as e:
            self.logger.error(str(e))
            return AutoResult.fail_result(error_msg=str(e))

        # 清除截图缓存
        self.image_processor.clear_screenshot_cache()
        self.logger.info(f"文本输入成功: {log_text}")
        return AutoResult.success_result(data=text)

    def sleep(self, secs: float = 1.0) -> AutoResult:
        """带中断检查的睡眠操作"""
        start_time = time.time()
        if self.auto.check_should_stop():
            self.logger.debug("睡眠任务被中断")
            return AutoResult.fail_result(error_msg="睡眠任务被中断", elapsed_time=0.0, is_interrupted=True)

        try:
            device = self.device_handler.get_device()
            if device:
                result = device.sleep(secs, stop_event=self.auto.stop_event)
            else:
                self.delay_manager.apply_delay(secs, self.auto.stop_event)
                result = True

            elapsed = time.time() - start_time
            self.logger.debug(f"睡眠完成: {secs}秒")
            return AutoResult.success_result(data=result, elapsed_time=elapsed)
        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"睡眠失败: {str(e)}"
            self.logger.error(error_msg)
            return AutoResult.fail_result(error_msg=error_msg, elapsed_time=elapsed)
