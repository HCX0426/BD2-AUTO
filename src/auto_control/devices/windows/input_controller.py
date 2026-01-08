import time
from typing import List, Optional, Tuple, Union

import pydirectinput
import win32api
import win32con
import win32gui

from .constants import CoordType


class InputController:
    """
    输入控制器：负责Windows窗口的鼠标点击、滑动和键盘按键等输入控制功能。
    """

    def __init__(self, device):
        """
        初始化输入控制器。

        Args:
            device: 所属的WindowsDevice实例
        """
        self.device = device
        self.logger = device.logger

    def _ensure_window_foreground(self, max_attempts: int = 3) -> bool:
        """
        确保窗口在前台，支持多次尝试。

        Args:
            max_attempts: 最大尝试次数

        Returns:
            bool: 操作成功返回True，否则返回False
        """
        current_time = time.time()
        foreground_hwnd = win32gui.GetForegroundWindow()

        # 检查窗口是否已在前台
        if self.device.window_manager._is_window_ready() and foreground_hwnd == self.device.window_manager.hwnd:
            self.device._last_activate_time = current_time
            self.logger.debug(f"窗口已在前台（句柄: {self.device.window_manager.hwnd}），无需激活")
            # 窗口已在前台且状态就绪，无需更新动态信息
            return True

        # 前台模式：不自动激活，等待用户手动操作
        if self.device.screenshot_manager._best_screenshot_strategy != "printwindow":
            self.logger.debug(f"前台模式，等待用户手动激活窗口 | 句柄: {self.device.window_manager.hwnd}")
            # 前台模式下，只要窗口未最小化且存在，就返回True
            return self.device.window_manager._is_window_ready()

        # 后台模式：执行正常激活逻辑
        if current_time - self.device._last_activate_attempt < self.device.window_manager.ACTIVATE_RETRY_COOLDOWN:
            self.logger.debug(
                f"激活操作冷却中（剩余{self.device.window_manager.ACTIVATE_RETRY_COOLDOWN - (current_time - self.device._last_activate_attempt):.1f}秒）"
            )
            return False
        self.device._last_activate_attempt = current_time

        self.logger.info(f"开始激活窗口（最多{max_attempts}次尝试）| 句柄: {self.device.window_manager.hwnd}")
        if self.device.window_manager._activate_window(temp_activation=False, max_attempts=max_attempts):
            self.device._last_activate_time = current_time
            self.device._update_dynamic_window_info()
            return True
        else:
            self.logger.warning(f"窗口激活失败（已尝试{max_attempts}次），可能被遮挡/权限不足")
            return False

    def click(
        self,
        pos: Union[Tuple[int, int], str, List[str]],
        click_time: int = 1,
        duration: float = 0.1,
        right_click: bool = False,
        coord_type: CoordType = CoordType.LOGICAL,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> bool:
        """
        执行鼠标点击操作。

        Args:
            pos: 点击位置，可以是坐标元组、模板名称或模板名称列表
            click_time: 点击次数
            duration: 点击持续时间（秒）
            right_click: 是否为右键点击
            coord_type: 坐标类型
            roi: 可选，感兴趣区域，用于模板匹配

        Returns:
            bool: 操作成功返回True，否则返回False
        """
        # 记录原始前台窗口，仅在background模式下恢复
        original_foreground_hwnd = None
        if self.device._click_mode == "background":
            original_foreground_hwnd = self.device.window_manager._get_original_foreground()

        # 激活目标窗口
        activate_success = self._ensure_window_foreground(max_attempts=3)
        if not activate_success:
            self.device._record_error("click", "无法激活窗口至前台（所有尝试失败）")
            self.logger.error(self.device.last_error)
            # background模式下恢复原始前台窗口
            if original_foreground_hwnd and win32gui.IsWindow(original_foreground_hwnd):
                self.device.window_manager._restore_foreground(original_foreground_hwnd)
            return False

        # 模式适配：临时置顶（background点击模式生效，foreground点击模式跳过）
        temp_topmost_success = self.device.window_manager._set_window_temp_topmost()

        time.sleep(0.2)  # 增加临时置顶后的延迟，确保窗口状态稳定
        target_pos: Optional[Tuple[int, int]] = None
        ctx = self.device.display_context
        click_source = "直接坐标"

        if isinstance(pos, (str, list)):
            click_source = "模板匹配"
            screen_img = self.device.screenshot_manager.capture_screen()
            if screen_img is None:
                self.device._record_error("click", "截图失败，无法执行模板匹配")
                self.logger.error(self.device.last_error)
                self.device.window_manager._restore_window_original_topmost()
                return False

            processed_roi = roi
            if roi:
                is_valid, err_msg = self.device.coord_transformer.validate_roi_format(roi)
                if not is_valid:
                    self.logger.warning(f"ROI预处理失败: {err_msg}，切换为全图匹配")
                    processed_roi = None
                # Note: 不在这里手动限制ROI边界，因为模板匹配前会调用coord_transformer.process_roi进行统一处理
                # 统一的ROI处理逻辑会根据全屏/窗口模式自动适配不同坐标系统
                self.logger.debug(f"使用原始ROI: {roi}")

            templates = [pos] if isinstance(pos, str) else pos
            matched_template = None
            match_result = None
            for template_name in templates:
                match_result = self.device.image_processor.match_template(
                    image=screen_img, template=template_name, threshold=0.6, roi=processed_roi
                )
                if match_result is not None:
                    matched_template = template_name
                    break

            if match_result is None:
                self.device._record_error("click", f"所有模板匹配失败: {templates}")
                self.logger.error(self.device.last_error)
                self.device.window_manager._restore_window_original_topmost()
                return False

            match_rect = self.device.coord_transformer._convert_numpy_to_tuple(match_result)
            is_valid, err_msg = self.device.coord_transformer.validate_roi_format(match_rect)
            if not is_valid:
                self.device._record_error("click", f"模板匹配结果无效: {err_msg} | 模板: {matched_template}")
                self.logger.error(self.device.last_error)
                self.device.window_manager._restore_window_original_topmost()
                return False
            target_pos = self.device.coord_transformer.get_rect_center(match_rect)
            self.logger.debug(
                f"模板匹配成功 | 模板: {matched_template} | 匹配矩形: {match_rect} | 逻辑中心点: {target_pos}"
            )
            coord_type = CoordType.LOGICAL
        else:
            target_pos = self.device.coord_transformer._convert_numpy_to_tuple(pos)
            if not isinstance(target_pos, tuple) or len(target_pos) != 2:
                self.device._record_error("click", f"点击坐标格式无效（需2元组）: {pos}")
                self.logger.error(self.device.last_error)
                self.device.window_manager._restore_window_original_topmost()
                return False
            x, y = target_pos
            if x < 0 or y < 0:
                self.device._record_error("click", f"点击坐标无效（非负）: ({x},{y})")
                self.logger.error(self.device.last_error)
                self.device.window_manager._restore_window_original_topmost()
                return False

        x_target, y_target = target_pos
        logical_x, logical_y = 0, 0
        if coord_type == CoordType.PHYSICAL:
            logical_x, logical_y = x_target, y_target
            self.logger.debug(f"坐标类型：物理坐标 | 输入: ({x_target},{y_target})")
        elif coord_type == CoordType.BASE:
            logical_x, logical_y = self.device.coord_transformer.convert_original_to_current_client(x_target, y_target)
            self.logger.debug(f"基准坐标转换 | 基准: ({x_target},{y_target}) → 逻辑: ({logical_x},{logical_y})")
        else:
            logical_x, logical_y = x_target, y_target

        if ctx.is_fullscreen:
            screen_x, screen_y = logical_x, logical_y
            screen_w, screen_h = ctx.screen_physical_res
            screen_x = max(0, min(screen_x, screen_w - 1))
            screen_y = max(0, min(screen_y, screen_h - 1))
        else:
            if coord_type == CoordType.PHYSICAL:
                screen_x, screen_y = self.device.coord_transformer.convert_client_physical_to_screen_physical(
                    logical_x, logical_y
                )
            else:
                screen_x, screen_y = self.device.coord_transformer.convert_client_logical_to_screen_physical(
                    logical_x, logical_y
                )

        click_success = True
        # 只有在执行实际点击操作时，才记录和恢复鼠标位置
        original_mouse_pos = win32api.GetCursorPos()
        self.logger.debug(f"记录原鼠标位置: {original_mouse_pos}")

        try:
            win32api.SetCursorPos((screen_x, screen_y))
            time.sleep(0.1)  # 增加鼠标移动后的延迟，确保系统识别到鼠标位置变化

            mouse_down = win32con.MOUSEEVENTF_RIGHTDOWN if right_click else win32con.MOUSEEVENTF_LEFTDOWN
            mouse_up = win32con.MOUSEEVENTF_RIGHTUP if right_click else win32con.MOUSEEVENTF_LEFTUP

            for i in range(click_time):
                if i > 0:
                    time.sleep(0.2)  # 增加多次点击之间的间隔
                win32api.mouse_event(mouse_down, 0, 0, 0, 0)
                time.sleep(duration)
                win32api.mouse_event(mouse_up, 0, 0, 0, 0)
                time.sleep(0.1)  # 增加点击完成后的延迟，确保系统响应点击事件
        except Exception as e:
            self.device._record_error("click", f"执行鼠标点击操作失败: {str(e)}")
            self.logger.error(self.device.last_error, exc_info=True)
            click_success = False
        finally:
            # 恢复原始鼠标位置
            win32api.SetCursorPos(original_mouse_pos)
            self.logger.debug(f"恢复原鼠标位置: {original_mouse_pos}")

            # 模式适配：恢复置顶状态（仅background点击模式生效）
            self.device.window_manager._restore_window_original_topmost()

        if click_success:
            click_type = "右键" if right_click else "左键"
            self.logger.info(
                f"点击成功 | 类型: {click_type} | 次数: {click_time} | 按住时长: {duration}s | "
                f"屏幕坐标: ({screen_x},{screen_y}) | 模式: {'全屏' if ctx.is_fullscreen else '窗口'} | 来源: {click_source}"
            )

            # 仅在background模式下且操作成功时恢复原始前台窗口
            if (
                self.device._click_mode == "background"
                and original_foreground_hwnd
                and win32gui.IsWindow(original_foreground_hwnd)
            ):
                self.device.window_manager._restore_foreground(original_foreground_hwnd)
            # foreground模式下保持目标窗口在前台
        return click_success

    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.3,
        steps: int = 10,
        coord_type: CoordType = CoordType.LOGICAL,
    ) -> bool:
        """
        执行鼠标滑动操作。

        Args:
            start_x: 起始X坐标
            start_y: 起始Y坐标
            end_x: 结束X坐标
            end_y: 结束Y坐标
            duration: 滑动持续时间（秒）
            steps: 滑动步数
            coord_type: 坐标类型

        Returns:
            bool: 操作成功返回True，否则返回False
        """
        # 记录原始前台窗口，仅在background模式下恢复
        original_foreground_hwnd = None
        if self.device._click_mode == "background":
            original_foreground_hwnd = self.device.window_manager._get_original_foreground()

        # 激活目标窗口
        activate_success = self._ensure_window_foreground(max_attempts=3)
        if not activate_success:
            self.device._record_error("swipe", "无法激活窗口至前台（所有尝试失败）")
            self.logger.error(self.device.last_error)
            # background模式下恢复原始前台窗口
            if original_foreground_hwnd and win32gui.IsWindow(original_foreground_hwnd):
                self.device.window_manager._restore_foreground(original_foreground_hwnd)
            return False

        # 模式适配：临时置顶（background点击模式生效，foreground点击模式跳过）
        temp_topmost_success = self.device.window_manager._set_window_temp_topmost()

        time.sleep(0.1)
        start_pos = (start_x, start_y)
        end_pos = (end_x, end_y)

        if coord_type == CoordType.BASE:
            start_pos = self.device.coord_transformer.convert_original_to_current_client(*start_pos)
            end_pos = self.device.coord_transformer.convert_original_to_current_client(*end_pos)
        elif coord_type == CoordType.PHYSICAL:
            start_pos = self.device.coord_transformer.convert_client_physical_to_logical(*start_pos)
            end_pos = self.device.coord_transformer.convert_client_physical_to_logical(*end_pos)

        screen_start = self.device.coord_transformer.convert_client_logical_to_screen_physical(*start_pos)
        screen_end = self.device.coord_transformer.convert_client_logical_to_screen_physical(*end_pos)
        step_x = (screen_end[0] - screen_start[0]) / steps
        step_y = (screen_end[1] - screen_start[1]) / steps
        step_delay = duration / steps

        swipe_success = True
        try:
            win32api.SetCursorPos(screen_start)
            time.sleep(0.1)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)

            for i in range(1, steps + 1):
                current_x = int(round(screen_start[0] + step_x * i))
                current_y = int(round(screen_start[1] + step_y * i))
                win32api.SetCursorPos((current_x, current_y))
                time.sleep(step_delay)

            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        except Exception as e:
            self.device._record_error("swipe", f"执行鼠标滑动操作失败: {str(e)}")
            self.logger.error(self.device.last_error, exc_info=True)
            swipe_success = False
        finally:
            # 模式适配：恢复置顶状态
            self.device.window_manager._restore_window_original_topmost()

        if swipe_success:
            self.logger.info(f"滑动成功 | 逻辑坐标: {start_pos} → {end_pos} | 时长: {duration}s | 步数: {steps}")

            # 仅在background模式下且操作成功时恢复原始前台窗口
            if (
                self.device._click_mode == "background"
                and original_foreground_hwnd
                and win32gui.IsWindow(original_foreground_hwnd)
            ):
                self.device.window_manager._restore_foreground(original_foreground_hwnd)
            # foreground模式下保持目标窗口在前台
        return swipe_success

    def key_press(self, key: str, duration: float = 0.1) -> bool:
        """
        执行键盘按键操作。

        Args:
            key: 按键名称
            duration: 按键持续时间（秒）

        Returns:
            bool: 操作成功返回True，否则返回False
        """
        # 记录原始前台窗口，仅在background模式下恢复
        original_foreground_hwnd = None
        if self.device._click_mode == "background":
            original_foreground_hwnd = self.device.window_manager._get_original_foreground()

        # 激活目标窗口
        activate_success = self._ensure_window_foreground(max_attempts=3)
        if not activate_success:
            self.device._record_error("key_press", "无法激活窗口至前台")
            self.logger.error(self.device.last_error)
            # background模式下恢复原始前台窗口
            if original_foreground_hwnd and win32gui.IsWindow(original_foreground_hwnd):
                self.device.window_manager._restore_foreground(original_foreground_hwnd)
            return False

        # 模式适配：临时置顶
        temp_topmost_success = self.device.window_manager._set_window_temp_topmost()
        # 初始化点击模式（默认foreground）
        if self.device._click_mode is None:
            self.device._click_mode = "foreground"
        if not temp_topmost_success and self.device._click_mode == "background":
            self.logger.warning("background点击模式窗口临时置顶失败，按键操作可能不稳定")

        time.sleep(0.1)
        press_success = True
        try:
            pydirectinput.keyDown(key)
            time.sleep(duration)
            pydirectinput.keyUp(key)
        except Exception as e:
            self.device._record_error("key_press", f"执行键盘按键操作失败: {str(e)}")
            self.logger.error(self.device.last_error, exc_info=True)
            press_success = False
        finally:
            # 模式适配：恢复置顶状态（仅background点击模式生效）
            self.device.window_manager._restore_window_original_topmost()

        if press_success:
            self.logger.info(f"按键成功 | 按键: {key} | 按住时长: {duration}s")

            # 仅在background模式下且操作成功时恢复原始前台窗口
            if (
                self.device._click_mode == "background"
                and original_foreground_hwnd
                and win32gui.IsWindow(original_foreground_hwnd)
            ):
                self.device.window_manager._restore_foreground(original_foreground_hwnd)
            # foreground模式下保持目标窗口在前台
        return press_success
