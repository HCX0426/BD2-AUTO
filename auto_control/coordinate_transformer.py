from typing import Tuple, Optional
import win32gui
import win32api
import win32con

class CoordinateTransformer:
    """坐标转换工具类：处理全屏和窗口模式下的坐标转换，正确响应DPI和窗口大小变化"""

    def __init__(
        self,
        original_base_res: Tuple[int, int],  # 原始基准分辨率（采集坐标时的分辨率，固定不变）
        original_dpi: float,                 # 原始基准DPI（采集坐标时的DPI，固定不变）
        logger
    ):
        """
        初始化坐标转换器

        :param original_base_res: 原始基准分辨率 (宽, 高) → 固定，不允许修改
        :param original_dpi: 原始基准DPI（如1.0=100%，1.25=125%）→ 固定，不允许修改
        :param logger: 日志实例
        """
        # -------------------------- 原始固定基准（初始化后不可修改）--------------------------
        self._original_base_res = original_base_res  # 核心：原始采集的基准分辨率
        self._original_dpi = original_dpi            # 核心：原始采集的基准DPI
        self.logger = logger
        self.logger.info(
            f"坐标转换器初始化 | 原始基准分辨率: {self._original_base_res} | "
            f"原始基准DPI: {self._original_dpi:.2f}"
        )

        # -------------------------- 动态窗口参数（随窗口状态实时更新）--------------------------
        self._current_client_size = (0, 0)    # 当前窗口客户区尺寸 (宽, 高)
        self._current_dpi = 1.0               # 当前窗口的DPI缩放因子（如系统设置的125%）
        self._current_handle = None           # 当前窗口句柄

    def update_context(
        self,
        client_size: Tuple[int, int],
        current_dpi: float,
        handle: Optional[int] = None
    ) -> None:
        """
        更新当前窗口的动态上下文（仅更新当前状态，不影响原始基准）
        :param client_size: 当前窗口客户区尺寸 (宽, 高)
        :param current_dpi: 当前窗口的DPI缩放因子（如1.0=100%）
        :param handle: 当前窗口句柄
        """
        # 校验动态参数有效性
        if not all(client_size) or current_dpi <= 0:
            self.logger.error(f"无效的窗口上下文参数：客户区{client_size}，DPI{current_dpi}")
            return

        self._current_client_size = client_size
        self._current_dpi = current_dpi
        self._current_handle = handle
        self.logger.debug(
            f"窗口动态上下文更新 | 当前客户区: {self._current_client_size} | "
            f"当前DPI: {self._current_dpi:.2f} | 窗口句柄: {self._current_handle}"
        )

    def get_original_base(self) -> Tuple[Tuple[int, int], float]:
        """获取原始基准参数（供外部查询，不可修改）"""
        return self._original_base_res, self._original_dpi

    def convert_original_to_current_client(self, x: int, y: int) -> Tuple[int, int]:
        """
        核心转换：将"基于原始基准的坐标"转换为"当前窗口的客户区坐标"
        """
        # 1. 校验必要参数
        if not all(self._original_base_res) or not all(self._current_client_size):
            raise ValueError("原始基准或当前窗口上下文未初始化")
        # 2. 提取原始基准与当前窗口参数
        orig_w, orig_h = self._original_base_res
        curr_w, curr_h = self._current_client_size
        # 3. 转换逻辑：基于原始基准与当前客户区的比例
        scale_x = curr_w / orig_w
        scale_y = curr_h / orig_h
        final_x = int(round(x * scale_x))
        final_y = int(round(y * scale_y))
        self.logger.debug(
            f"坐标转换 | 原始基准坐标: ({x},{y}) "
            f"→ 当前客户区坐标: ({final_x},{final_y}) "
            f"[原始基准: {orig_w}x{orig_h}, 当前窗口: {curr_w}x{curr_h}]"
        )
        return final_x, final_y

    def convert_original_rect_to_current_client(self, rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """
        将"基于原始基准的矩形（x,y,w,h）"转换为"当前窗口的客户区矩形"
        :param rect: 原始基准矩形，格式为 (x, y, w, h)（x,y=左上角坐标，w=宽度，h=高度）
        :return: 当前客户区矩形，格式为 (x, y, w, h)
        """
        # 1. 校验必要参数
        if not all(self._original_base_res) or not all(self._current_client_size):
            raise ValueError("原始基准或当前窗口上下文未初始化")
        if not isinstance(rect, (tuple, list)) or len(rect) != 4:
            raise ValueError(f"无效的矩形参数：需为(x,y,w,h)格式的4元素元组/列表，当前为{rect}")
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            raise ValueError(f"矩形尺寸无效：宽度{w}、高度{h}需为正数")
        # 2. 提取原始基准与当前窗口参数，计算缩放比例
        orig_w, orig_h = self._original_base_res
        curr_w, curr_h = self._current_client_size
        # 3. 使用与模板相同的缩放策略：保持宽高比
        scale_ratio = min(curr_w / orig_w, curr_h / orig_h)
        final_x = int(round(x * scale_ratio))
        final_y = int(round(y * scale_ratio))
        final_w = int(round(w * scale_ratio))
        final_h = int(round(h * scale_ratio))
        # 4. 确保缩放后尺寸有效（避免极端情况导致的0尺寸）
        final_w = max(1, final_w)
        final_h = max(1, final_h)
        # --- 修改部分：更新日志中的变量名 ---
        self.logger.debug(
            f"矩形转换 | 原始基准矩形: {rect} "
            f"→ 当前客户区矩形: ({final_x},{final_y},{final_w},{final_h}) "
            f"[原始基准: {orig_w}x{orig_h}, 当前窗口: {curr_w}x{curr_h}, 缩放比: {scale_ratio:.2f}]"
        )
        # --- 修改结束 ---
        return (final_x, final_y, final_w, final_h)

    def convert_current_client_to_screen(
        self,
        client_x: int,
        client_y: int,
    ) -> Tuple[int, int]:
        """
        将"当前窗口的客户区坐标"转换为"屏幕坐标"，
        无论全屏还是窗口模式，都使用 win32gui.ClientToScreen，
        因为模板和 ROI 均基于物理像素采集，客户区坐标即为物理像素坐标
        """
        # 校验必要参数
        if not self._current_handle:
            raise ValueError("当前窗口句柄未设置，无法转换为屏幕坐标")

        try:
            # 直接使用 ClientToScreen 将客户区物理像素坐标转换为屏幕物理像素坐标
            # 这适用于窗口模式和全屏模式，因为我们操作的是物理像素坐标。
            screen_point = win32gui.ClientToScreen(self._current_handle, (client_x, client_y))
            screen_x, screen_y = screen_point

            self.logger.debug(
                f"客户区→屏幕坐标 | 客户区坐标: ({client_x},{client_y}) "
                f"→ 屏幕坐标: ({screen_x},{screen_y}) | 窗口句柄: {self._current_handle}"
            )
            return screen_x, screen_y
        except Exception as e:
            error_msg = f"客户区→屏幕坐标转换失败 (句柄: {self._current_handle}, 坐标: ({client_x},{client_y})): {str(e)}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def _is_current_window_fullscreen(self, hwnd) -> bool:
        """判断窗口是否全屏（基于屏幕硬件分辨率）"""
        if not hwnd:
            self.logger.warning("未设置当前窗口句柄，无法判断是否全屏")
            return False

        try:
            # 1. 获取当前窗口的整体矩形（屏幕坐标，含边框，全屏时无边框）
            win_rect = win32gui.GetWindowRect(hwnd)
            win_width = win_rect[2] - win_rect[0]
            win_height = win_rect[3] - win_rect[1]

            # 2. 获取屏幕的真实分辨率（硬件分辨率，不受DPI影响）
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

            # 3. 全屏判断：窗口尺寸 ≈ 屏幕分辨率（误差<5像素，排除边框影响）
            FULLSCREEN_ERROR_TOLERANCE = 5
            is_fullscreen = (
                abs(win_width - screen_width) < FULLSCREEN_ERROR_TOLERANCE and
                abs(win_height - screen_height) < FULLSCREEN_ERROR_TOLERANCE
            )

            self.logger.debug(
                f"全屏判断 | 窗口尺寸: {win_width}x{win_height} | "
                f"屏幕分辨率: {screen_width}x{screen_height} | 全屏: {is_fullscreen}"
            )
            return is_fullscreen
        except Exception as e:
            self.logger.error(f"判断当前窗口是否全屏失败: {str(e)}")
            return False

    def convert_current_client_to_original(self, x: int, y: int) -> Tuple[int, int]:
        """
        当前客户区坐标 → 原始基准坐标（反向转换）
        逻辑：基于原始基准分辨率与当前客户区尺寸的比例推导
        """
        if not all(self._original_base_res) or not all(self._current_client_size):
            self.logger.warning("原始基准或当前窗口上下文未初始化，无法反向转换坐标")
            return (x, y)

        # 获取当前客户区尺寸
        curr_client_w, curr_client_h = self._current_client_size
        orig_base_w, orig_base_h = self._original_base_res

        # 校验参数有效性（避免除零错误）
        if curr_client_w <= 0 or curr_client_h <= 0 or orig_base_w <= 0 or orig_base_h <= 0:
            self.logger.warning(
                f"无效参数，无法反向转换坐标 | "
                f"当前客户区尺寸: ({curr_client_w},{curr_client_h}) | "
                f"原始基准分辨率: ({orig_base_w},{orig_base_h})"
            )
            return (x, y)

        # 反向转换比例：原始基准尺寸 / 当前客户区尺寸
        scale_x = orig_base_w / curr_client_w
        scale_y = orig_base_h / curr_client_h

        # 计算原始基准坐标（四舍五入为整数）
        base_x = int(round(x * scale_x))
        base_y = int(round(y * scale_y))

        self.logger.debug(
            f"当前客户区→原始基准坐标转换 | "
            f"当前坐标: ({x},{y}) | 比例(x:y): {scale_x:.2f}:{scale_y:.2f} | "
            f"原始基准坐标: ({base_x},{base_y})"
        )
        return (base_x, base_y)

    def convert_current_client_rect_to_original(self, rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """
        当前客户区矩形 → 原始基准矩形（反向转换，处理ROI）
        :param rect: 当前客户区矩形 (x, y, w, h)
        :return: 原始基准矩形 (x, y, w, h)
        """
        if not all(self._original_base_res) or not all(self._current_client_size):
            self.logger.warning("原始基准或当前窗口上下文未初始化，无法反向转换矩形")
            return rect

        x, y, w, h = rect
        # 转换左上角坐标
        base_x, base_y = self.convert_current_client_to_original(x, y)

        # 转换宽高（使用相同比例）
        curr_client_w, curr_client_h = self._current_client_size
        orig_base_w, orig_base_h = self._original_base_res

        if curr_client_w <= 0 or curr_client_h <= 0 or orig_base_w <= 0 or orig_base_h <= 0:
            return (base_x, base_y, w, h)

        scale_x = orig_base_w / curr_client_w
        scale_y = orig_base_h / curr_client_h
        base_w = int(round(w * scale_x))
        base_h = int(round(h * scale_y))

        # 确保尺寸为正
        base_w = max(1, base_w)
        base_h = max(1, base_h)

        self.logger.debug(
            f"当前客户区→原始基准矩形转换 | "
            f"当前矩形: {rect} | 比例(x:y): {scale_x:.2f}:{scale_y:.2f} | "
            f"原始基准矩形: ({base_x},{base_y},{base_w},{base_h})"
        )
        return (base_x, base_y, base_w, base_h)