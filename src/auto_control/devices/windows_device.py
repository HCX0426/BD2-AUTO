import ctypes
import time
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import pydirectinput
import win32api
import win32con
import win32gui
import win32process
import win32ui
from PIL import Image

from src.auto_control.devices.base_device import BaseDevice, DeviceState
from src.auto_control.utils.coordinate_transformer import CoordinateTransformer  # 新的转换器
from src.auto_control.image.image_processor import ImageProcessor
from src.auto_control.utils.display_context import RuntimeDisplayContext  # 新的上下文容器


class DCHandle:
    """DC资源上下文管理器：仅获取客户区DC，排除标题栏/边框"""

    def __init__(self, hwnd, logger):
        self.hwnd = hwnd
        self.hdc = None
        self.logger = logger

    def __enter__(self):
        self.hdc = win32gui.GetDC(self.hwnd)
        if not self.hdc:
            raise RuntimeError(f"获取客户区DC失败（窗口句柄: {self.hwnd}）")
        self.logger.debug(f"成功获取客户区DC: {self.hdc}（窗口句柄: {self.hwnd}）")
        return self.hdc

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.hdc and self.hwnd:
            try:
                win32gui.ReleaseDC(self.hwnd, self.hdc)
                self.logger.debug(f"成功释放客户区DC: {self.hdc}")
            except Exception as e:
                print(f"释放客户区DC失败: {str(e)}")


class BitmapHandle:
    """位图资源上下文管理器，自动释放资源"""

    def __init__(self, bitmap):
        self.bitmap = bitmap

    def __enter__(self):
        return self.bitmap

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.bitmap:
            try:
                win32gui.DeleteObject(self.bitmap.GetHandle())
            except Exception as e:
                print(f"释放位图失败: {str(e)}")


class WindowsDevice(BaseDevice):
    """Windows设备控制器：基于新的CoordinateTransformer和RuntimeDisplayContext"""

    # 类常量
    WINDOW_RESTORE_DELAY = 0.5  # 窗口恢复后的等待时间
    WINDOW_ACTIVATE_DELAY = 0.1  # 窗口激活后的验证等待时间
    ACTIVATE_COOLDOWN = 5.0  # 激活冷却时间（5秒内不重复激活）
    FOREGROUND_CHECK_INTERVAL = 5.0  # 前台检查间隔

    def __init__(
            self,
            device_uri: str,
            logger=None,
            image_processor: Optional[ImageProcessor] = None,
            coord_transformer: Optional[CoordinateTransformer] = None,
            display_context: Optional[RuntimeDisplayContext] = None,  # 新增：传入全局上下文
    ):
        super().__init__(device_uri)
        self.logger = logger
        self.device_uri = device_uri
        self.image_processor: ImageProcessor = image_processor
        
        # 全局唯一的转换器和上下文（必须传入同一个实例）
        self.coord_transformer: CoordinateTransformer = coord_transformer
        self.display_context: RuntimeDisplayContext = display_context

        # 窗口基础信息（稳定属性，存储到上下文）
        self.hwnd: Optional[int] = None  # 窗口句柄（临时缓存，核心数据在上下文）
        self.window_title: str = ""      # 窗口标题
        self.window_class: str = ""      # 窗口类名
        self.process_id: int = 0         # 进程ID

        # 激活状态缓存
        self._last_activate_time = 0.0  # 上次激活时间（秒级时间戳）
        self._foreground_activation_allowed = True  # 是否允许尝试激活到前台

        # 解析URI参数
        self.uri_params = self._parse_uri(device_uri)
        self.logger.debug(f"Windows设备URI参数: {self.uri_params}")

        # 启用DPI感知
        self._enable_dpi_awareness()

    def _parse_uri(self, uri: str) -> Dict[str, str]:
        """解析设备URI参数"""
        params = {}
        if "://" in uri:
            _, query = uri.split("://", 1)
            for part in query.split("&"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    params[key.lower()] = value
        return params

    def _get_window_handle(self) -> Optional[int]:
        """根据URI参数查找窗口句柄"""
        self.logger.info("开始查找窗口...")
        
        # 按优先级尝试不同查找方式
        strategies = [
            ("精确标题", lambda: self.uri_params.get("title") and win32gui.FindWindow(None, self.uri_params["title"])),
            ("正则标题", self._find_by_title_regex),
            ("进程名", lambda: self._find_window_by_process_name("BrownDust2")),
            ("类名", lambda: win32gui.FindWindow("UnityWndClass", None)),
        ]
        
        for name, strategy in strategies:
            self.logger.info(f"尝试通过{name}查找窗口...")
            hwnd = strategy()
            if hwnd:
                # 获取窗口标题
                title = win32gui.GetWindowText(hwnd)
                self.window_title = title
                self.logger.info(f"通过{name}找到窗口: {title}, 句柄: {hwnd}")
                return hwnd
        
        self.logger.error("未找到匹配的窗口")
        return None

    def _find_by_title_regex(self) -> Optional[int]:
        """通过正则表达式查找窗口标题"""
        if "title_re" not in self.uri_params:
            return None
        
        import re
        pattern_str = self.uri_params["title_re"]
        if '*' in pattern_str and not (pattern_str.startswith('.*') or pattern_str.endswith('.*')):
            pattern_str = pattern_str.replace('*', '.*')
        
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
        except re.error as e:
            self.logger.error(f"正则表达式编译错误: {e}")
            return None
        
        def callback(hwnd, ctx):
            title = win32gui.GetWindowText(hwnd)
            if title and pattern.search(title):
                ctx.append(hwnd)
                return False
            return True
        
        results = []
        win32gui.EnumWindows(callback, results)
        return results[0] if results else None

    def _find_window_by_process_name(self, process_name: str) -> Optional[int]:
        """通过进程名查找窗口"""
        try:
            import psutil
            for proc in psutil.process_iter(['name', 'pid']):
                if proc.info['name'].lower() == process_name.lower():
                    pid = proc.info['pid']
                    self.logger.info(f"找到进程: {process_name}, PID: {pid}")
                    
                    def find_window_by_pid(hwnd, pid_list):
                        _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                        if found_pid == pid_list[0] and win32gui.GetWindowText(hwnd):
                            pid_list.append(hwnd)
                            return False
                        return True
                    
                    results = [pid]
                    win32gui.EnumWindows(find_window_by_pid, results)
                    if len(results) > 1:
                        self.logger.info(f"找到进程窗口: 句柄={results[1]}")
                        return results[1]
        except ImportError:
            self.logger.warning("psutil未安装，无法通过进程名查找窗口")
        except Exception as e:
            self.logger.error(f"通过进程名查找窗口出错: {e}")
        return None
    
    def _enable_dpi_awareness(self) -> None:
        """启用DPI感知"""
        try:
            import ctypes
            shcore = ctypes.windll.shcore
            result = shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            if result == 0:
                self.logger.debug("已成功启用Per-Monitor DPI感知模式")
                try:
                    dpi = ctypes.windll.user32.GetDpiForSystem()
                    self.logger.debug(f"系统DPI: {dpi}")
                except:
                    pass
            else:
                self.logger.warning(f"SetProcessDpiAwareness失败，错误码: {result}")
        except Exception as e:
            self.logger.error(f"启用DPI感知失败: {e}")
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                self.logger.debug("已启用备用DPI感知模式")
            except:
                self.logger.error("所有DPI感知方法都失败")

    def _get_dpi_for_window(self) -> float:
        """获取当前窗口的DPI缩放因子"""
        if not self.hwnd:
            self.logger.warning("窗口句柄不存在，默认DPI=1.0")
            return 1.0
        
        try:
            if hasattr(ctypes.windll.user32, 'GetDpiForWindow'):
                dpi = ctypes.windll.user32.GetDpiForWindow(self.hwnd)
                if dpi > 0:
                    return dpi / 96.0
            dpi = ctypes.windll.user32.GetDpiForSystem()
            return dpi / 96.0
        except Exception as e:
            self.logger.error(f"获取DPI失败: {e}，默认DPI=1.0")
            return 1.0

    def _get_screen_hardware_res(self) -> Tuple[int, int]:
        """获取物理屏幕分辨率"""
        try:
            screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            self.logger.debug(f"获取屏幕分辨率: {screen_w}x{screen_h}")
            return (screen_w, screen_h)
        except Exception as e:
            self.logger.error(f"获取屏幕分辨率失败: {e}")
            return (1920, 1080)

    def _update_dynamic_window_info(self) -> bool:
        """更新动态窗口信息到全局上下文"""
        if not self.hwnd or not self.display_context:
            self.logger.error("无法更新窗口信息：窗口句柄或上下文不存在")
            return False

        try:
            if self.is_minimized():
                self.logger.debug("窗口处于最小化状态，跳过动态信息更新")
                return False

            # 获取窗口矩形
            window_rect = win32gui.GetWindowRect(self.hwnd)
            win_left, win_top, win_right, win_bottom = window_rect
            if win_left == 0 and win_top == 0 and win_right == 0 and win_bottom == 0:
                raise RuntimeError(f"获取窗口矩形失败，返回无效值: {window_rect}")

            # 更新DPI缩放因子
            dpi_scale = self._get_dpi_for_window()
            if dpi_scale <= 0:
                self.logger.warning(f"DPI缩放因子异常: {dpi_scale}，强制使用1.0")
                dpi_scale = 1.0

            # 获取客户区物理尺寸
            client_rect_phys = win32gui.GetClientRect(self.hwnd)
            client_w_phys = client_rect_phys[2] - client_rect_phys[0]
            client_h_phys = client_rect_phys[3] - client_rect_phys[1]
            if client_w_phys <= 0 or client_h_phys <= 0:
                raise RuntimeError(f"获取客户区物理尺寸失败: {client_w_phys}x{client_h_phys}")

            # 计算客户区逻辑尺寸（物理尺寸 / DPI缩放）
            client_w_logic = int(round(client_w_phys / dpi_scale))
            client_h_logic = int(round(client_h_phys / dpi_scale))
            client_w_logic = max(800, client_w_logic)
            client_h_logic = max(600, client_h_logic)

            # 获取客户区左上角屏幕坐标
            client_origin_x, client_origin_y = win32gui.ClientToScreen(self.hwnd, (0, 0))

            # 判断全屏状态（通过转换器）
            is_fullscreen = self.coord_transformer.is_fullscreen if self.coord_transformer else False

            # 更新全局上下文（直接修改上下文属性）
            self.display_context.update_from_window(
                hwnd=self.hwnd,
                is_fullscreen=is_fullscreen,
                dpi_scale=dpi_scale,
                client_logical=(client_w_logic, client_h_logic),
                client_physical=(client_w_phys, client_h_phys),
                screen_physical=self._get_screen_hardware_res(),
                client_origin=(client_origin_x, client_origin_y)
            )

            self.logger.debug(
                f"动态信息更新完成 | 模式: {'全屏' if is_fullscreen else '窗口'} | "
                f"客户区逻辑: {client_w_logic}x{client_h_logic} | "
                f"客户区物理: {client_w_phys}x{client_h_phys} | "
                f"DPI: {dpi_scale:.2f} | "
                f"客户区原点: ({client_origin_x},{client_origin_y})"
            )
            return True
        except Exception as e:
            self.last_error = f"动态窗口信息更新失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    def connect(self, timeout: float = 10.0) -> bool:
        """连接到Windows窗口，初始化并更新上下文"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            self.hwnd = self._get_window_handle()
            if self.hwnd:
                # 初始化上下文（原始基准分辨率从上下文获取）
                if not self.display_context:
                    self.logger.error("未传入全局RuntimeDisplayContext，连接失败")
                    return False

                # 缓存稳定属性
                self.window_class = win32gui.GetClassName(self.hwnd)
                _, self.process_id = win32process.GetWindowThreadProcessId(self.hwnd)
                screen_res = self._get_screen_hardware_res()

                # 初始化上下文基础信息
                self.display_context.original_base_width = self.display_context.original_base_width  # 保持原始基准
                self.display_context.original_base_height = self.display_context.original_base_height
                self.display_context.hwnd = self.hwnd
                self.display_context.screen_physical_width, self.display_context.screen_physical_height = screen_res

                # 激活窗口并更新动态信息
                self.set_foreground()
                time.sleep(0.5)

                # 验证窗口有效性
                if self.hwnd and win32gui.IsWindow(self.hwnd) and win32gui.IsWindowVisible(self.hwnd):
                    self.state = DeviceState.CONNECTED
                    self.logger.info(
                        f"已连接到Windows窗口 | 标题: {self.window_title} | 句柄: {self.hwnd} | "
                        f"类名: {self.window_class} | 进程ID: {self.process_id} | "
                        f"物理屏幕分辨率: {screen_res}"
                    )
                    return True
            time.sleep(0.5)
        self.last_error = f"超时未找到匹配窗口（{timeout}s）"
        self.state = DeviceState.DISCONNECTED
        self.logger.error(f"连接失败: {self.last_error}")
        return False

    def disconnect(self) -> bool:
        """断开连接，重置状态"""
        if self.hwnd:
            self.logger.info(f"断开与窗口的连接: {self.window_title}（句柄: {self.hwnd}）")
            # 重置上下文（保留原始基准）
            if self.display_context:
                self.display_context.update_from_window(
                    hwnd=None,
                    is_fullscreen=False,
                    dpi_scale=1.0,
                    client_logical=(0, 0),
                    client_physical=(0, 0),
                    client_origin=(0, 0)
                )
            # 重置设备状态
            self.hwnd = None
            self.window_title = ""
            self.window_class = ""
            self.process_id = 0
            self._last_activate_time = 0.0
            self._foreground_activation_allowed = True
            self.state = DeviceState.DISCONNECTED
            return True
        return False

    def is_minimized(self) -> bool:
        """检查窗口是否最小化"""
        if not self.hwnd:
            return True
        return win32gui.IsIconic(self.hwnd)

    def set_foreground(self) -> bool:
        """将窗口激活到前台（依赖上下文状态）"""
        if not self.hwnd or not self.display_context:
            self.last_error = f"未连接到窗口或上下文未初始化: {self.hwnd}"
            return False

        current_time = time.time()
        
        # 1. 前台验证：当前前台窗口就是目标窗口
        foreground_hwnd = win32gui.GetForegroundWindow()
        if foreground_hwnd == self.hwnd:
            self._last_activate_time = current_time
            self.logger.debug(f"窗口已在前台 | 句柄: {self.hwnd} | 无需激活")
            self._update_dynamic_window_info()
            return True

        # 2. 首次激活尝试
        if self._foreground_activation_allowed:
            self.logger.info(f"首次尝试激活窗口到前台 | 句柄: {self.hwnd}")
            try:
                # 恢复最小化窗口
                if self.is_minimized():
                    self.logger.info("窗口最小化，正在恢复...")
                    win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                    time.sleep(self.WINDOW_RESTORE_DELAY)
                    if win32gui.GetForegroundWindow() == self.hwnd:
                        self._last_activate_time = current_time
                        self._foreground_activation_allowed = False
                        self.logger.info(f"窗口恢复后自动激活成功")
                        self._update_dynamic_window_info()
                        return True

                # 标准激活流程
                win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
                success = win32gui.SetForegroundWindow(self.hwnd)
                time.sleep(self.WINDOW_ACTIVATE_DELAY)
                final_foreground = win32gui.GetForegroundWindow()

                if success and final_foreground == self.hwnd and not self.is_minimized():
                    self._last_activate_time = current_time
                    self._foreground_activation_allowed = False
                    self.logger.info(f"窗口激活成功 | 句柄: {self.hwnd}")
                    self._update_dynamic_window_info()
                    return True
                else:
                    self.logger.warning(f"窗口激活尝试失败")
            except Exception as e:
                self.logger.error(f"激活窗口异常: {str(e)}")
            
            self._foreground_activation_allowed = False
            self.logger.warning(f"进入前台等待循环，每 {self.FOREGROUND_CHECK_INTERVAL} 秒检查一次")

        # 3. 循环等待窗口回到前台
        while True:
            time.sleep(self.FOREGROUND_CHECK_INTERVAL)
            try:
                if win32gui.GetForegroundWindow() == self.hwnd:
                    self.logger.info(f"窗口已回到前台，退出等待")
                    self._update_dynamic_window_info()
                    return True
                self.logger.debug(f"窗口仍未在前台，继续等待")
            except Exception as e:
                self.logger.error(f"检查前台窗口出错: {e}")
        return False

    def _activate_with_standard_method(self) -> bool:
        """标准激活方法（内部使用）"""
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        return win32gui.SetForegroundWindow(self.hwnd)

    def _activate_with_thread_attach(self) -> bool:
        """高级激活方法（绕过前台限制）"""
        current_thread_id = win32api.GetCurrentThreadId()
        target_thread_id, _ = win32process.GetWindowThreadProcessId(self.hwnd)
        if current_thread_id == target_thread_id:
            return self._activate_with_standard_method()
        try:
            win32process.AttachThreadInput(current_thread_id, target_thread_id, True)
            result = self._activate_with_standard_method()
            return result
        finally:
            try:
                win32process.AttachThreadInput(current_thread_id, target_thread_id, False)
            except Exception as e:
                self.logger.debug(f"分离线程输入上下文异常: {str(e)}")

    def _optimized_minimize_restore(self) -> bool:
        """优化版最小化恢复激活"""
        try:
            if self._activate_with_standard_method():
                return True
            win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
            time.sleep(self.WINDOW_RESTORE_DELAY / 2)
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            time.sleep(self.WINDOW_RESTORE_DELAY / 2)
            return self._activate_with_standard_method()
        except:
            return False

    def get_resolution(self) -> Tuple[int, int]:
        """获取当前客户区逻辑分辨率（从上下文读取）"""
        if not self.display_context:
            self.logger.warning("上下文未初始化，返回默认分辨率")
            return (1920, 1080)
        return self.display_context.client_logical_res

    def capture_screen(self, roi: Optional[Tuple[int, int, int, int]] = None) -> Optional[np.ndarray]:
        """
        截取窗口客户区屏幕（基于上下文的坐标转换）
        Args:
            roi: 原始基准坐标的ROI (x, y, w, h)
        Returns:
            BGR格式图像
        """
        if not self.hwnd or self.state != DeviceState.CONNECTED or not self.display_context:
            self.last_error = "未连接到窗口或上下文未初始化"
            return None
        try:
            time.sleep(0.1)

            # 1. 基础参数从上下文读取
            is_fullscreen = self.display_context.is_fullscreen
            client_w_phys, client_h_phys = self.display_context.client_physical_res
            client_origin_x, client_origin_y = self.display_context.client_screen_origin

            # 2. 区分全屏/窗口模式截图
            if is_fullscreen:
                cap_w, cap_h = self.display_context.screen_physical_res
                self.logger.debug(f"全屏模式截图 | 尺寸: {cap_w}x{cap_h}")
                hdc_screen = win32gui.GetDC(0)
                mfcDC = win32ui.CreateDCFromHandle(hdc_screen)
                saveDC = mfcDC.CreateCompatibleDC()
                saveBitMap = win32ui.CreateBitmap()
                saveBitMap.CreateCompatibleBitmap(mfcDC, cap_w, cap_h)
                saveDC.SelectObject(saveBitMap)
                ctypes.windll.gdi32.BitBlt(
                    saveDC.GetSafeHdc(), 0, 0, cap_w, cap_h, hdc_screen, 0, 0, win32con.SRCCOPY
                )
            else:
                cap_w, cap_h = client_w_phys, client_h_phys
                self.logger.debug(f"窗口模式截图 | 客户区物理尺寸: {cap_w}x{cap_h}")
                hdc_screen = win32gui.GetDC(0)
                mfcDC = win32ui.CreateDCFromHandle(hdc_screen)
                saveDC = mfcDC.CreateCompatibleDC()
                saveBitMap = win32ui.CreateBitmap()
                saveBitMap.CreateCompatibleBitmap(mfcDC, cap_w, cap_h)
                saveDC.SelectObject(saveBitMap)
                # 截取客户区范围
                ctypes.windll.gdi32.BitBlt(
                    saveDC.GetSafeHdc(), 0, 0, cap_w, cap_h,
                    hdc_screen, client_origin_x, client_origin_y,
                    win32con.SRCCOPY
                )

            # 3. 位图转numpy数组
            bmpstr = saveBitMap.GetBitmapBits(True)
            im = Image.frombuffer('RGB', (cap_w, cap_h), bmpstr, 'raw', 'BGRX', 0, 1)
            img_np = np.array(im)
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            # 4. 资源释放
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.DeleteObject(saveBitMap.GetHandle())
            win32gui.ReleaseDC(0, hdc_screen)

            # 5. ROI裁剪（基于上下文和转换器）
            if roi:
                roi_x, roi_y, roi_w, roi_h = roi
                if is_fullscreen:
                    # 全屏模式：直接应用原始ROI
                    if roi_x < 0 or roi_y < 0 or roi_x + roi_w > cap_w or roi_y + roi_h > cap_h:
                        self.logger.warning(f"ROI超出全屏范围 | ROI: {roi} | 忽略裁剪")
                    else:
                        img_np = img_np[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
                        self.logger.debug(f"全屏模式裁剪ROI: {roi}")
                else:
                    # 窗口模式：原始ROI → 客户区逻辑ROI → 客户区物理ROI
                    if not self.coord_transformer:
                        self.logger.warning("缺少转换器，无法裁剪ROI")
                        return img_np
                    # 原始→客户区逻辑矩形
                    logic_rect = self.coord_transformer.convert_original_rect_to_current_client(roi)
                    logic_x, logic_y, logic_w, logic_h = logic_rect
                    # 逻辑→客户区物理坐标
                    phys_x, phys_y = self.display_context.logical_to_physical(logic_x, logic_y)
                    phys_w = int(round(logic_w * self.display_context.logical_to_physical_ratio))
                    phys_h = int(round(logic_h * self.display_context.logical_to_physical_ratio))
                    # 裁剪范围校验
                    crop_x = max(0, phys_x)
                    crop_y = max(0, phys_y)
                    crop_w = min(cap_w, phys_x + phys_w) - crop_x
                    crop_h = min(cap_h, phys_y + phys_h) - crop_y
                    if crop_w > 0 and crop_h > 0:
                        img_np = img_np[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]
                        self.logger.debug(
                            f"窗口模式裁剪ROI | 原始: {roi} → 逻辑: {logic_rect} → 物理: ({crop_x},{crop_y},{crop_w},{crop_h})"
                        )
                    else:
                        self.logger.warning(f"转换后ROI无效 | 原始ROI: {roi}")
            return img_np
        except Exception as e:
            self.last_error = f"截图失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return None

    def click(
            self,
            pos: Union[Tuple[int, int], str, List[str]],
            click_time: int = 1,
            duration: float = 0.1,
            right_click: bool = False,
            is_base_coord: bool = False,
            roi: Optional[Tuple[int, int, int, int]] = None,
            is_base_roi: bool = False
    ) -> bool:
        """鼠标点击操作（基于上下文和转换器）"""
        if not self.hwnd or self.state != DeviceState.CONNECTED or not self.display_context:
            self.last_error = "未连接到窗口或上下文未初始化"
            return False
        try:
            if not self.set_foreground():
                self.last_error = "无法激活窗口到前台"
                self.logger.error(self.last_error)
                return False

            time.sleep(0.1)
            target_pos: Optional[Tuple[int, int]] = None

            # 模板匹配逻辑
            if isinstance(pos, (str, list)):
                if not self.image_processor:
                    self.last_error = "缺少图像处理器，无法模板匹配"
                    return False
                screen = self.capture_screen(roi=roi if is_base_roi else None)
                if screen is None:
                    self.last_error = "截图失败，无法模板匹配"
                    return False

                templates = [pos] if isinstance(pos, str) else pos
                match_result = None
                matched_template = None
                for template_name in templates:
                    match_result = self.image_processor.match_template(
                        image=screen,
                        template=template_name,
                        dpi_scale=self.display_context.dpi_scale,
                        hwnd=self.hwnd,
                        threshold=0.6,
                        roi=roi,
                        is_base_roi=is_base_roi
                    )
                    if match_result is not None:
                        matched_template = template_name
                        break
                if match_result is None:
                    self.last_error = f"所有模板匹配失败: {templates}"
                    return False

                match_rect = tuple(match_result.tolist()) if isinstance(match_result, np.ndarray) else tuple(match_result)
                if len(match_rect) != 4:
                    self.last_error = f"模板结果格式错误: {match_rect}"
                    return False
                target_pos = self.image_processor.get_center(match_rect)
                target_pos = tuple(map(int, target_pos)) if isinstance(target_pos, (list, np.ndarray)) else target_pos
                if not isinstance(target_pos, tuple) or len(target_pos) != 2:
                    self.last_error = f"中心点计算失败: {target_pos}"
                    return False
                self.logger.debug(f"模板 {matched_template} 中心点（客户区逻辑坐标）: {target_pos}")
                is_base_coord = False  # 模板匹配结果已是客户区逻辑坐标

            # 直接坐标输入逻辑
            else:
                target_pos = tuple(map(int, pos))
                if not target_pos or len(target_pos) != 2:
                    self.last_error = f"无效点击位置: {target_pos}"
                    return False

            # 坐标转换：原始基准坐标 → 客户区逻辑坐标 → 屏幕全局物理坐标
            client_pos = target_pos
            if is_base_coord and self.coord_transformer:
                client_pos = self.coord_transformer.convert_original_to_current_client(*target_pos)
                self.logger.debug(f"原始坐标 {target_pos} → 客户区逻辑坐标 {client_pos}")

            # 客户区逻辑坐标 → 屏幕全局物理坐标
            screen_x, screen_y = self.coord_transformer.convert_client_logical_to_screen_physical(*client_pos)

            # 执行点击
            win32api.SetCursorPos((screen_x, screen_y))
            time.sleep(0.1)
            down_event = win32con.MOUSEEVENTF_RIGHTDOWN if right_click else win32con.MOUSEEVENTF_LEFTDOWN
            up_event = win32con.MOUSEEVENTF_RIGHTUP if right_click else win32con.MOUSEEVENTF_LEFTUP
            for _ in range(click_time):
                win32api.mouse_event(down_event, 0, 0, 0, 0)
                time.sleep(duration)
                win32api.mouse_event(up_event, 0, 0, 0, 0)
                if click_time > 1:
                    time.sleep(0.1)

            self.logger.info(
                f"点击成功 | 屏幕物理坐标: ({screen_x},{screen_y}) | "
                f"来源: {matched_template if isinstance(pos, (str, list)) else '直接坐标'}"
            )
            return True
        except Exception as e:
            self.last_error = f"点击失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    def swipe(
            self,
            start_x: int,
            start_y: int,
            end_x: int,
            end_y: int,
            duration: float = 0.3,
            steps: int = 10,
            is_base_coord: bool = False
    ) -> bool:
        """鼠标滑动操作（基于上下文和转换器）"""
        if not self.hwnd or self.state != DeviceState.CONNECTED or not self.display_context:
            self.last_error = "未连接到窗口或上下文未初始化"
            return False
        try:
            if not self.set_foreground():
                self.last_error = "无法激活窗口到前台"
                self.logger.error(self.last_error)
                return False

            time.sleep(0.1)
            start_pos = (start_x, start_y)
            end_pos = (end_x, end_y)

            # 原始基准坐标 → 客户区逻辑坐标
            if is_base_coord and self.coord_transformer:
                start_pos = self.coord_transformer.convert_original_to_current_client(*start_pos)
                end_pos = self.coord_transformer.convert_original_to_current_client(*end_pos)
                self.logger.debug(f"原始滑动坐标 → 客户区逻辑坐标: {start_pos} → {end_pos}")

            # 客户区逻辑坐标 → 屏幕全局物理坐标
            screen_start = self.coord_transformer.convert_client_logical_to_screen_physical(*start_pos)
            screen_end = self.coord_transformer.convert_client_logical_to_screen_physical(*end_pos)
            self.logger.debug(f"滑动屏幕物理坐标: {screen_start} → {screen_end}")

            # 执行滑动
            step_x = (screen_end[0] - screen_start[0]) / steps
            step_y = (screen_end[1] - screen_start[1]) / steps
            step_delay = duration / steps

            win32api.SetCursorPos(screen_start)
            time.sleep(0.1)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            for i in range(1, steps + 1):
                x = int(round(screen_start[0] + step_x * i))
                y = int(round(screen_start[1] + step_y * i))
                win32api.SetCursorPos((x, y))
                time.sleep(step_delay)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

            self.logger.debug(
                f"滑动成功 | 客户区逻辑坐标: {start_pos} → {end_pos} | 时长: {duration}s | 步数: {steps}"
            )
            return True
        except Exception as e:
            self.last_error = f"滑动失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    # 以下方法（key_press、text_input、exists、wait、get_state、sleep）保持原有逻辑，仅补充上下文校验
    def key_press(self, key: str, duration: float = 0.1) -> bool:
        if not self.hwnd or self.state != DeviceState.CONNECTED or not self.display_context:
            self.last_error = "未连接到窗口或上下文未初始化"
            return False
        try:
            if not self.set_foreground():
                self.last_error = "无法激活窗口到前台"
                self.logger.error(self.last_error)
                return False
            time.sleep(0.1)
            pydirectinput.keyDown(key)
            time.sleep(duration)
            pydirectinput.keyUp(key)
            self.logger.debug(f"按键成功: {key}（时长: {duration}s）")
            return True
        except Exception as e:
            self.last_error = f"按键失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    def text_input(self, text: str, interval: float = 0.05) -> bool:
        if not self.hwnd or self.state != DeviceState.CONNECTED or not self.display_context:
            self.last_error = "未连接到窗口或上下文未初始化"
            return False
        try:
            if not self.set_foreground():
                self.last_error = "无法激活窗口到前台"
                self.logger.error(self.last_error)
                return False
            time.sleep(0.1)
            if len(text) > 5:
                import pyperclip
                pyperclip.copy(text)
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                win32api.keybd_event(ord('V'), 0, 0, 0)
                time.sleep(0.05)
                win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(0.1)
                self.logger.debug(f"文本粘贴成功: {text[:20]}...（长度: {len(text)}）")
                return True
            for char in text:
                if char == ' ':
                    self.key_press("space", 0.02)
                elif char == '\n':
                    self.key_press("enter", 0.02)
                elif char == '\t':
                    self.key_press("tab", 0.02)
                else:
                    shift_pressed = char.isupper() or char in '~!@#$%^&*()_+{}|:"<>?'
                    if shift_pressed:
                        win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
                    win32api.keybd_event(ord(char.upper()), 0, 0, 0)
                    time.sleep(0.02)
                    win32api.keybd_event(ord(char.upper()), 0, win32con.KEYEVENTF_KEYUP, 0)
                    if shift_pressed:
                        win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)
                    time.sleep(interval)
            self.logger.debug(f"文本输入成功: {text}")
            return True
        except Exception as e:
            self.last_error = f"文本输入失败: {str(e)}"
            self.logger.error(self.last_error, exc_info=True)
            return False

    def exists(
            self,
            template_name: Union[str, List[str]],
            threshold: float = 0.8,
            roi: Optional[Tuple[int, int, int, int]] = None,
            is_base_roi: bool = False
    ) -> Optional[Tuple[int, int]]:
        try:
            if not self.hwnd or not self.display_context:
                self.last_error = "未连接到窗口或上下文未初始化"
                return None
            if not self.set_foreground():
                self.logger.debug("无法激活窗口到前台，模板检查可能不准确")
            if not self.image_processor:
                self.last_error = "缺少图像处理器"
                return None
            screen = self.capture_screen(roi=roi if is_base_roi else None)
            if screen is None:
                self.logger.debug(f"截图为空，无法检查模板: {template_name}")
                return None

            templates = [template_name] if isinstance(template_name, str) else template_name
            self.logger.debug(f"检查模板: {templates}（阈值: {threshold}）")
            for template in templates:
                match_result = self.image_processor.match_template(
                    image=screen,
                    template=template,
                    dpi_scale=self.display_context.dpi_scale,
                    hwnd=self.hwnd,
                    threshold=threshold,
                    roi=roi,
                    is_base_roi=is_base_roi
                )
                if match_result is not None:
                    match_rect = tuple(match_result.tolist()) if isinstance(match_result, np.ndarray) else tuple(match_result)
                    if len(match_rect) != 4:
                        self.logger.warning(f"模板结果格式无效: {match_rect}，模板: {template}")
                        continue
                    center_pos = self.image_processor.get_center(match_rect)
                    center_pos = tuple(map(int, center_pos)) if isinstance(center_pos, (list, np.ndarray)) else center_pos
                    if not isinstance(center_pos, tuple) or len(center_pos) != 2:
                        self.logger.warning(f"模板中心点无效: {center_pos}，模板: {template}")
                        continue
                    self.logger.debug(
                        f"模板找到: {template} | 矩形区域: {match_rect} | 中心点（客户区逻辑坐标）: {center_pos}"
                    )
                    return center_pos
            self.logger.debug(f"所有模板未找到: {templates}")
            return None
        except Exception as e:
            self.logger.error(f"模板检查异常: {str(e)}", exc_info=True)
            return None

    def wait(
            self,
            template_name: Union[str, List[str]],
            timeout: float = 10.0,
            interval: float = 0.5,
            roi: Optional[Tuple[int, int, int, int]] = None,
            is_base_roi: bool = False
    ) -> Optional[Tuple[int, int]]:
        start_time = time.time()
        templates = [template_name] if isinstance(template_name, str) else template_name
        self.logger.debug(f"开始等待模板: {templates}（超时: {timeout}s，间隔: {interval}s）")
        while time.time() - start_time < timeout:
            center_pos = self.exists(templates, threshold=0.8, roi=roi, is_base_roi=is_base_roi)
            if center_pos is not None:
                self.logger.info(
                    f"模板 {templates} 已找到（等待耗时: {time.time() - start_time:.1f}s），中心点: {center_pos}"
                )
                return center_pos
            time.sleep(interval)
        self.last_error = f"等待模板超时: {templates}（{timeout}s）"
        self.logger.error(self.last_error)
        return None

    def get_state(self) -> DeviceState:
        if not self.hwnd:
            return DeviceState.DISCONNECTED
        try:
            if not win32gui.IsWindow(self.hwnd):
                self.hwnd = None
                return DeviceState.DISCONNECTED
            if not win32gui.IsWindowVisible(self.hwnd):
                return DeviceState.INVISIBLE
            return DeviceState.CONNECTED
        except Exception as e:
            self.logger.error(f"获取设备状态失败: {e}")
            return DeviceState.ERROR

    def sleep(self, secs: float) -> bool:
        if secs <= 0:
            self.logger.warning(f"无效睡眠时间: {secs}秒")
            return False
        try:
            time.sleep(secs)
            self.logger.debug(f"设备睡眠完成: {secs}秒")
            return True
        except Exception as e:
            self.last_error = f"睡眠操作失败: {str(e)}"
            self.logger.error(self.last_error)
            return False