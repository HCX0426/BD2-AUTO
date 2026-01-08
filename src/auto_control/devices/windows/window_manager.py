import ctypes
import time
from threading import Event, Lock
from typing import Dict, Optional, Tuple

import win32api
import win32con
import win32gui
import win32process


class WindowManager:
    """
    窗口管理器：负责Windows窗口的查找、激活、状态检测和临时置顶等功能。
    """
    
    # 窗口操作延迟配置
    WINDOW_RESTORE_DELAY = 0.5
    WINDOW_ACTIVATE_DELAY = 0.1
    ACTIVATE_COOLDOWN = 5.0
    FOREGROUND_CHECK_INTERVAL = 5.0
    TEMP_FOREGROUND_DELAY = 0.1
    TEMP_TOPMOST_DELAY = 0.05
    TOPMOST_CHECK_INTERVAL = 3.0
    ACTIVATE_RETRY_COOLDOWN = 1.0
    
    def __init__(self, device):
        """
        初始化窗口管理器。
        
        Args:
            device: 所属的WindowsDevice实例
        """
        self.device = device
        self.logger = device.logger
        self.hwnd: Optional[int] = None
        self.window_title: str = ""
        self.window_class: str = ""
        self.process_id: int = 0
        
        # 窗口激活状态缓存
        self._last_activate_time = 0.0
        self._foreground_activation_allowed = True
        self._last_activate_attempt = 0.0
        
        # 临时置顶相关状态
        self._original_window_ex_style: Optional[int] = None
        self._is_temp_topmost = False
        self._topmost_lock = Lock()
        
        # DPI感知相关
        self._enable_dpi_awareness()
    
    def _enable_dpi_awareness(self) -> None:
        """
        启用DPI感知，避免坐标偏移。
        """
        try:
            # 定义DPI感知级别常量
            PROCESS_DPI_UNAWARE = 0
            PROCESS_SYSTEM_DPI_AWARE = 1
            PROCESS_PER_MONITOR_DPI_AWARE = 2
    
            shcore = ctypes.windll.shcore
    
            # 首先尝试获取当前DPI感知级别，避免重复设置
            try:
                current_awareness = ctypes.c_int()
                result = shcore.GetProcessDpiAwareness(ctypes.byref(current_awareness))
                if result == 0:
                    self.logger.debug(f"当前DPI感知级别: {current_awareness.value}")
                    if current_awareness.value > 0:
                        # 已经设置了合适的DPI感知级别，无需再次设置
                        return
            except Exception:
                # GetProcessDpiAwareness可能不可用，继续尝试设置
                pass
    
            # 尝试不同的DPI感知级别，从高到低
            for awareness_level in [PROCESS_PER_MONITOR_DPI_AWARE, PROCESS_SYSTEM_DPI_AWARE]:
                try:
                    result = shcore.SetProcessDpiAwareness(awareness_level)
                    if result == 0:
                        self.logger.debug(f"已启用DPI感知模式，级别: {awareness_level}")
                        try:
                            system_dpi = ctypes.windll.user32.GetDpiForSystem()
                            self.logger.debug(f"系统DPI: {system_dpi}（标准DPI=96）")
                        except Exception:
                            pass
                        return
                except Exception:
                    # 尝试下一个级别
                    continue
    
            # 如果SetProcessDpiAwareness所有级别都失败，尝试旧版API
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                self.logger.debug("已启用系统级DPI感知模式（旧版API）")
            except Exception as e:
                self.logger.error(f"所有DPI感知模式启用失败：{str(e)}，可能导致坐标偏移", exc_info=True)
        except Exception as e:
            self.logger.error(f"启用DPI感知失败: {str(e)}", exc_info=True)
    
    def _get_dpi_for_window(self) -> float:
        """
        获取窗口的DPI缩放因子。
        
        Returns:
            float: DPI缩放因子
        """
        if not self.hwnd:
            self.logger.warning("窗口句柄未初始化，返回默认DPI缩放因子1.0")
            return 1.0
    
        try:
            if hasattr(ctypes.windll.user32, "GetDpiForWindow"):
                window_dpi = ctypes.windll.user32.GetDpiForWindow(self.hwnd)
                if window_dpi > 0:
                    return window_dpi / 96.0
            system_dpi = ctypes.windll.user32.GetDpiForSystem()
            return system_dpi / 96.0
        except Exception as e:
            self.logger.warning(f"获取DPI缩放因子异常：{str(e)}")
            return 1.0
    
    def _parse_uri(self, uri: str) -> Dict[str, str]:
        """
        解析设备URI，提取参数。
        
        Args:
            uri: 设备URI
            
        Returns:
            Dict[str, str]: 解析后的参数字典
        """
        params = {}
        if "://" in uri:
            _, query = uri.split("://", 1)
            for part in query.split("&"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    params[key.lower()] = value
        return params
    
    def _get_window_handle(self) -> Optional[int]:
        """
        查找目标窗口，支持多种查找策略。
        
        Returns:
            Optional[int]: 窗口句柄，未找到返回None
        """
        self.logger.info("开始查找目标窗口...")
        uri_params = self.device.uri_params
        strategies = [
            ("精确标题", lambda: uri_params.get("title") and win32gui.FindWindow(None, uri_params["title"])),
            ("正则标题", self._find_by_title_regex),
            (
                "进程名",
                lambda: uri_params.get("process")
                and self._find_window_by_process_name(uri_params["process"]),
            ),
            ("类名", lambda: uri_params.get("class") and win32gui.FindWindow(uri_params["class"], None)),
        ]
    
        for strategy_name, strategy_func in strategies:
            self.logger.info(f"尝试通过「{strategy_name}」查找窗口")
            hwnd = strategy_func()
            if hwnd:
                self.window_title = win32gui.GetWindowText(hwnd)
                self.logger.info(f"窗口查找成功 | 标题: {self.window_title} | 句柄: {hwnd} | 查找方式: {strategy_name}")
                return hwnd
    
        self.logger.error("所有查找策略均未找到匹配窗口")
        return None
    
    def _find_by_title_regex(self) -> Optional[int]:
        """
        通过正则表达式匹配窗口标题。
        
        Returns:
            Optional[int]: 窗口句柄，未找到返回None
        """
        uri_params = self.device.uri_params
        if "title_re" not in uri_params:
            self.logger.debug("URI未配置title_re参数，跳过正则标题查找")
            return None
    
        import re
    
        pattern_str = uri_params["title_re"]
        if "*" in pattern_str and not (pattern_str.startswith(".*") or pattern_str.endswith(".*")):
            pattern_str = pattern_str.replace("*", ".*")
    
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
        except re.error as e:
            self.logger.error(f"正则表达式编译失败：{str(e)} | 表达式: {pattern_str}", exc_info=True)
            return None
    
        def window_callback(hwnd, result_list):
            title = win32gui.GetWindowText(hwnd)
            if title and pattern.search(title):
                result_list.append(hwnd)
                return False
            return True
    
        match_results = []
        win32gui.EnumWindows(window_callback, match_results)
        return match_results[0] if match_results else None
    
    def _find_window_by_process_name(self, process_name: str) -> Optional[int]:
        """
        通过进程名查找窗口。
        
        Args:
            process_name: 进程名
            
        Returns:
            Optional[int]: 窗口句柄，未找到返回None
        """
        try:
            import os
    
            import psutil
    
            # 从文件路径中提取进程名
            if os.path.isfile(process_name):
                process_name = os.path.basename(process_name)
                self.logger.info(f"从路径中提取进程名: {process_name}")
    
            # 收集所有匹配的进程
            matched_processes = []
            for proc in psutil.process_iter(["name", "pid"]):
                if proc.info["name"] and proc.info["name"].lower() == process_name.lower():
                    matched_processes.append(proc)
    
            if not matched_processes:
                self.logger.warning(f"未找到进程: {process_name}")
                return None
    
            self.logger.info(f"找到 {len(matched_processes)} 个匹配进程: {process_name}")
    
            # 收集所有可见窗口
            all_visible_windows = []
    
            def collect_visible_windows(hwnd, ctx):
                _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                if win32gui.IsWindowVisible(hwnd):
                    ctx.append((window_pid, hwnd))
    
            win32gui.EnumWindows(collect_visible_windows, all_visible_windows)
    
            # 筛选出与目标进程相关的窗口
            related_windows = []
            process_pids = {proc.info["pid"] for proc in matched_processes}
    
            for window_pid, hwnd in all_visible_windows:
                if window_pid in process_pids:
                    window_title = win32gui.GetWindowText(hwnd)
                    if window_title:
                        related_windows.append(hwnd)
    
            if related_windows:
                hwnd = related_windows[0]
                window_title = win32gui.GetWindowText(hwnd)
                self.logger.info(f"找到进程关联窗口 | 句柄: {hwnd} | 标题: {window_title}")
                return hwnd
        except ImportError:
            self.logger.warning("psutil未安装，无法通过进程名查找窗口")
        except Exception as e:
            self.logger.error(f"进程名查找窗口异常：{str(e)}", exc_info=True)
        return None
    
    def _activate_window(self, temp_activation: bool = False, max_attempts: int = 1) -> bool:
        """
        统一的窗口激活方法，支持临时激活和多次尝试。
        
        Args:
            temp_activation: 是否为临时激活（仅用于截图等操作）
            max_attempts: 最大尝试次数
            
        Returns:
            bool: 激活成功返回True，否则返回False
        """
        if not self._is_window_ready():
            self.logger.warning(f"窗口未就绪，无法激活 | 句柄: {self.hwnd}")
            return False
    
        # 检查窗口是否已经在前台
        if win32gui.GetForegroundWindow() == self.hwnd:
            self.logger.debug(f"窗口已在前台，无需激活 | 句柄: {self.hwnd}")
            return True
    
        # 优化激活策略：减少尝试次数，避免多次激活导致闪烁
        # 对于临时激活，只尝试一次
        if temp_activation:
            max_attempts = 1
    
        for attempt in range(max_attempts):
            if self.device.stop_event.is_set():
                self.logger.debug(f"激活操作被中断 | 句柄: {self.hwnd}")
                return False
    
            try:
                # 如果窗口最小化，先恢复
                if self.is_minimized():
                    win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                    time.sleep(self.WINDOW_RESTORE_DELAY)
    
                # 使用SwitchToThisWindow激活窗口（绕过SetForegroundWindow限制）
                ctypes.windll.user32.SwitchToThisWindow(self.hwnd, True)
    
                # 等待窗口稳定，减少延迟时间，避免闪烁
                delay = self.TEMP_FOREGROUND_DELAY / 2 if temp_activation else self.WINDOW_ACTIVATE_DELAY / 2
                time.sleep(delay)
    
                # 验证激活结果
                if win32gui.GetForegroundWindow() == self.hwnd:
                    self.logger.debug(f"窗口激活成功 | 句柄: {self.hwnd} | 尝试次数: {attempt+1}")
                    return True
                else:
                    self.logger.warning(f"窗口激活失败 | 句柄: {self.hwnd} | 尝试次数: {attempt+1}")
                    # 只在最后一次尝试失败后才等待重试
                    if attempt < max_attempts - 1:
                        time.sleep(0.3)  # 减少等待时间，避免闪烁
    
            except Exception as e:
                self.logger.warning(f"窗口激活异常 | 句柄: {self.hwnd} | 尝试次数: {attempt+1} | 错误: {e}")
                # 只在最后一次尝试失败后才等待重试
                if attempt < max_attempts - 1:
                    time.sleep(0.3)  # 减少等待时间，避免闪烁
    
        self.logger.warning(f"窗口激活失败，已尝试{max_attempts}次 | 句柄: {self.hwnd}")
        return False
    
    def _temp_activate_window(self) -> Optional[int]:
        """
        临时激活目标窗口，保存原始前台窗口句柄。
        
        Returns:
            Optional[int]: 原始前台窗口句柄，失败返回None
        """
        if not self.hwnd:
            return None
    
        try:
            # 保存原始前台窗口
            original_foreground = win32gui.GetForegroundWindow()
    
            # 如果目标窗口已经在前台，直接返回
            if original_foreground == self.hwnd:
                return original_foreground
    
            # 使用统一激活方法
            if self._activate_window(temp_activation=True):
                return original_foreground
            else:
                return None
    
        except Exception as e:
            self.logger.warning(f"临时激活窗口异常: {e}")
            return None
    
    def _set_window_temp_topmost(self) -> bool:
        """
        background点击模式专用：临时设置窗口置顶，foreground点击模式下直接返回True。
        
        Returns:
            bool: 操作成功返回True，否则返回False
        """
        # foreground点击模式无需临时置顶
        if self.device._click_mode == "foreground":
            return True
    
        with self._topmost_lock:
            if not self.hwnd or self._is_temp_topmost:
                return False
    
            try:
                current_ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
                if (current_ex_style & win32con.WS_EX_TOPMOST) != 0:
                    self._is_temp_topmost = True
                    self._original_window_ex_style = current_ex_style
                    self.logger.debug(f"background点击模式窗口已置顶，标记临时置顶状态 | 句柄: {self.hwnd}")
                    return True
    
                self._original_window_ex_style = current_ex_style
                new_ex_style = self._original_window_ex_style | win32con.WS_EX_TOPMOST
                win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, new_ex_style)
    
                win32gui.SetWindowPos(
                    self.hwnd,
                    win32con.HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )
    
                time.sleep(self.TEMP_TOPMOST_DELAY)
                self._is_temp_topmost = True
                self.logger.debug(f"background点击模式窗口临时置顶成功 | 句柄: {self.hwnd}")
                return True
            except Exception as e:
                self.logger.warning(f"background点击模式设置临时置顶失败: {e}")
                self._original_window_ex_style = None
                self._is_temp_topmost = False
                return False
    
    def _restore_window_original_topmost(self, pre_delay: float = 0.1) -> None:
        """
        background点击模式专用：恢复窗口原始置顶状态；foreground点击模式下直接返回（不恢复）。
        """
        # foreground点击模式不恢复置顶状态
        if self.device._click_mode == "foreground":
            self.logger.debug("foreground点击模式跳过窗口置顶状态恢复")
            return
    
        with self._topmost_lock:
            if not self.hwnd or not self._is_temp_topmost or self._original_window_ex_style is None:
                self.logger.debug("background点击模式无需恢复置顶状态：窗口句柄/临时置顶标记/原始样式缺失")
                return
    
            try:
                if pre_delay > 0:
                    time.sleep(pre_delay)
    
                # 恢复原始扩展样式
                win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, self._original_window_ex_style)
    
                # 取消置顶
                win32gui.SetWindowPos(
                    self.hwnd,
                    win32con.HWND_NOTOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )
    
                time.sleep(self.TEMP_TOPMOST_DELAY)
    
                # 验证恢复结果
                current_ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
                is_still_topmost = (current_ex_style & win32con.WS_EX_TOPMOST) != 0
    
                if is_still_topmost:
                    self.logger.warning(
                        f"background点击模式窗口仍置顶 | 当前样式: {hex(current_ex_style)} | 原始样式: {hex(self._original_window_ex_style)}"
                    )
                    win32gui.SetWindowPos(
                        self.hwnd,
                        win32con.HWND_NOTOPMOST,
                        0,
                        0,
                        0,
                        0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER,
                    )
                else:
                    self.logger.debug(f"background点击模式窗口恢复原始置顶状态成功 | 句柄: {self.hwnd}")
            except Exception as e:
                self.logger.warning(f"background点击模式恢复置顶状态失败: {e}", exc_info=True)
            finally:
                self._original_window_ex_style = None
                self._is_temp_topmost = False
    
    def is_minimized(self) -> bool:
        """
        检查窗口是否处于最小化状态。
        
        Returns:
            bool: 最小化返回True，否则返回False
        """
        if not self.hwnd:
            return False
        try:
            window_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_STYLE)
            return (window_style & win32con.WS_MINIMIZE) != 0
        except Exception as e:
            self.logger.warning(f"检查窗口最小化状态失败: {e}")
            return False
    
    def _is_window_ready(self) -> bool:
        """
        统一检查窗口是否就绪。

        Returns:
            bool: 窗口就绪返回True，否则返回False
        """
        if not self.hwnd:
            self.logger.debug("窗口句柄为None，窗口未就绪")
            return False
        try:
            is_window = win32gui.IsWindow(self.hwnd)
            if not is_window:
                self.logger.warning(f"窗口句柄无效: {self.hwnd}，窗口未就绪")
                return False
            is_minimized = self.is_minimized()
            return not is_minimized
        except Exception as e:
            self.logger.error(f"检查窗口状态时发生异常: {e}")
            return False
    
    def _check_topmost_status(self):
        """
        foreground模式专用：后台线程持续检查窗口状态，未激活则记录日志。
        每3秒检查一次，直到stop_event触发或窗口断开。
        """
        self.logger.info(f"foreground模式状态检查线程启动 | 检查间隔: {self.TOPMOST_CHECK_INTERVAL}秒")
        self._topmost_check_stop = Event()
    
        while not self.device.stop_event.is_set() and not self._topmost_check_stop.is_set():
            try:
                if not self.hwnd or not win32gui.IsWindow(self.hwnd):
                    self.logger.warning("窗口句柄无效，退出状态检查线程")
                    break
    
                # 检查当前窗口是否在前台
                is_foreground = win32gui.GetForegroundWindow() == self.hwnd
    
                if is_foreground:
                    self.logger.debug("foreground模式窗口激活状态正常")
                else:
                    self.logger.info("foreground模式窗口不在前台，可能影响截图效果")
    
                # 等待检查间隔（支持中断）
                if self.device.stop_event.wait(timeout=self.TOPMOST_CHECK_INTERVAL):
                    break
            except Exception as e:
                self.logger.error(f"foreground模式状态检查异常: {e}", exc_info=True)
                # 异常后等待1秒再重试，避免频繁报错
                time.sleep(1.0)
    
        self.logger.info("foreground模式状态检查线程退出")
    
    def _get_original_foreground(self) -> Optional[int]:
        """
        获取原始前台窗口句柄。
        
        Returns:
            Optional[int]: 原始前台窗口句柄，失败返回None
        """
        try:
            return win32gui.GetForegroundWindow()
        except Exception as e:
            self.logger.warning(f"获取原始前台窗口失败: {e}")
            return None
    
    def _restore_foreground(self, original_hwnd: Optional[int]) -> None:
        """
        恢复原始前台窗口。
        
        Args:
            original_hwnd: 原始前台窗口句柄
        """
        if original_hwnd and win32gui.IsWindow(original_hwnd):
            try:
                win32gui.SetForegroundWindow(original_hwnd)
                time.sleep(self.WINDOW_ACTIVATE_DELAY)
            except Exception as e:
                self.logger.warning(f"恢复原始前台窗口失败: {e}")