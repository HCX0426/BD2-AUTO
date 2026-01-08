import ctypes
import time
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import win32con
import win32gui
import win32ui
from PIL import Image


class ScreenshotManager:
    """
    截图管理器：负责Windows窗口的截图策略检测和多种截图方法实现。
    """

    def __init__(self, device):
        """
        初始化截图管理器。

        Args:
            device: 所属的WindowsDevice实例
        """
        self.device = device
        self.logger = device.logger
        self.hwnd = None

        # 截图策略与模式
        self._best_screenshot_strategy: Optional[str] = None  # printwindow/bitblt/dxcam/temp_foreground
        self._screenshot_mode: Optional[str] = None  # 截图模式：foreground/background 或具体方法名称
        self._available_screenshot_methods: List[str] = []  # 所有可用的截图方法列表

        # 临时置顶相关状态
        self._original_window_ex_style: Optional[int] = None
        self._is_temp_topmost = False

    class _DCCtxManager:
        """
        DC资源上下文管理器，自动处理DC和位图资源的获取和释放。
        """

        def __init__(self, hwnd, width, height):
            self.hwnd = hwnd
            self.width = width
            self.height = height
            self.hwnd_dc = None
            self.mfc_dc = None
            self.mem_dc = None
            self.bitmap = None

        def __enter__(self):
            """获取资源"""
            self.hwnd_dc = win32gui.GetDC(self.hwnd)
            self.mfc_dc = win32ui.CreateDCFromHandle(self.hwnd_dc)
            self.mem_dc = self.mfc_dc.CreateCompatibleDC()
            self.bitmap = win32ui.CreateBitmap()
            self.bitmap.CreateCompatibleBitmap(self.mfc_dc, self.width, self.height)
            self.mem_dc.SelectObject(self.bitmap)
            return self.mem_dc, self.bitmap

        def __exit__(self, exc_type, exc_val, exc_tb):
            """释放资源"""
            if self.mem_dc:
                self.mem_dc.DeleteDC()
            if self.mfc_dc:
                self.mfc_dc.DeleteDC()
            if self.hwnd_dc:
                win32gui.ReleaseDC(self.hwnd, self.hwnd_dc)
            if self.bitmap:
                win32gui.DeleteObject(self.bitmap.GetHandle())

    def _calculate_similarity(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """
        计算两张截图的相似度（使用SSIM算法）。

        Args:
            img1: 第一张截图
            img2: 第二张截图

        Returns:
            float: 相似度值（0.0-1.0）
        """
        try:
            if img1 is None or img2 is None:
                return 0.0

            if img1.shape != img2.shape:
                img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))

            gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

            from skimage.metrics import structural_similarity as ssim

            similarity = ssim(gray1, gray2)
            return float(similarity)
        except ImportError:
            self.logger.debug("scikit-image未安装，无法计算截图相似度")
            return 0.95
        except Exception as e:
            self.logger.debug(f"截图相似度计算失败: {e}")
            return 0.0

    def _select_best_method(
        self, method_priority: List[str], available_methods: List[str], default_method: str = None
    ) -> str:
        """
        根据优先级列表选择最优可用方法。

        Args:
            method_priority: 方法优先级列表，按优先级从高到低排列
            available_methods: 可用方法列表
            default_method: 默认方法，当没有匹配方法时使用

        Returns:
            str: 最优可用方法
        """
        for method in method_priority:
            if method in available_methods:
                return method
        return default_method or method_priority[-1]

    def _detect_best_screenshot_strategy(self) -> str:
        """
        检测并选择最优截图策略，使用截图相似度比较和性能评估。

        Returns:
            str: 最优截图策略名称
        """
        SIMILARITY_THRESHOLD = 0.85

        window_manager = self.device.window_manager
        if not window_manager._is_window_ready():
            self.logger.warning("窗口未就绪，默认使用temp_foreground（foreground模式）")
            self._screenshot_mode = "foreground"
            self._available_screenshot_methods = ["temp_foreground"]
            return "temp_foreground"

        self.device._update_dynamic_window_info()
        client_w_phys, client_h_phys = self.device.display_context.client_physical_res
        if client_w_phys <= 0 or client_h_phys <= 0:
            self.logger.warning("窗口尺寸无效，默认使用temp_foreground（foreground模式）")
            self._screenshot_mode = "foreground"
            self._available_screenshot_methods = ["temp_foreground"]
            return "temp_foreground"

        try:
            from skimage.metrics import structural_similarity as ssim

            has_ssim_support = True
        except ImportError:
            has_ssim_support = False
            self.logger.warning("scikit-image未安装，将使用原有检测逻辑")

        if not has_ssim_support:
            return self._detect_best_screenshot_strategy_fallback()

        # 1. 根据截图模式选择测试方法
        is_background_mode = self._screenshot_mode == "background"
        is_foreground_mode = self._screenshot_mode == "foreground" or not self._screenshot_mode

        method_results = {}
        reference_img = None

        if is_background_mode:
            # 后台模式：只测试printwindow
            self.logger.info("后台模式，只测试printwindow方法")

            # 测试printwindow
            try:
                start_time = time.time()
                screenshot = self._try_print_window(client_w_phys, client_h_phys)
                elapsed_time = time.time() - start_time

                if screenshot is not None:
                    # 后台模式使用自身作为参考
                    similarity = 1.0
                    method_results["printwindow"] = {
                        "screenshot": screenshot,
                        "similarity": similarity,
                        "time": elapsed_time,
                    }
                    self.logger.info(f"printwindow截图成功 | 耗时: {elapsed_time*1000:.1f}ms")
            except Exception as e:
                self.logger.info(f"printwindow测试失败: {e}")

            # 后台模式总是添加printwindow作为可用方法
            if "printwindow" not in method_results:
                method_results["printwindow"] = {"screenshot": None, "similarity": 0.0, "time": 0.0}

        else:  # 前台模式
            self.logger.info("前台模式，测试bitblt、dxcam、temp_foreground方法")

            # 2. 前台模式：确保窗口在前台
            if win32gui.GetForegroundWindow() != window_manager.hwnd:
                self.logger.info("前台模式，测试前激活窗口到前台")
                if not window_manager._activate_window(temp_activation=False, max_attempts=2):
                    self.logger.warning("窗口激活失败，部分截图方法可能无法正常测试")
                else:
                    # 添加窗口激活后的延迟，确保窗口有足够时间渲染和稳定
                    time.sleep(0.3)  # 增加到300ms延迟，确保窗口状态完全稳定
                    self.logger.info("窗口激活成功并已稳定")

            # 3. 先获取参考截图（temp_foreground），确保基础功能正常
            reference_img = self._try_temp_foreground_screenshot(client_w_phys, client_h_phys)
            if reference_img is None:
                self.logger.warning("temp_foreground截图失败，无法进行相似度比较，使用原有检测逻辑")
                return self._detect_best_screenshot_strategy_fallback()
            else:
                self.logger.info("temp_foreground截图成功，窗口状态稳定，开始测试其他方法")

            # 4. 测试前台适用的方法
            test_methods = [
                ("bitblt", self._try_bitblt),
                ("dxcam", self._try_dxcam),
            ]

            # 初始化所有测试方法的结果
            for method_name, _ in test_methods:
                method_results[method_name] = {"screenshot": None, "similarity": 0.0, "time": 0.0}

            for method_name, method_func in test_methods:
                try:
                    # 在每个方法测试前添加短暂延迟，确保窗口状态稳定
                    time.sleep(0.1)  # 100ms延迟

                    start_time = time.time()
                    screenshot = method_func(client_w_phys, client_h_phys)
                    elapsed_time = time.time() - start_time

                    if screenshot is not None:
                        similarity = self._calculate_similarity(screenshot, reference_img)
                        method_results[method_name] = {
                            "screenshot": screenshot,
                            "similarity": similarity,
                            "time": elapsed_time,
                        }
                        self.logger.info(
                            f"{method_name}截图成功 | 相似度: {similarity:.3f} | 耗时: {elapsed_time*1000:.1f}ms"
                        )
                    else:
                        # 提高日志级别，确保能在日志中看到
                        self.logger.info(f"{method_name}截图返回空结果")
                except Exception as e:
                    # 提高日志级别，确保能在日志中看到
                    self.logger.info(f"{method_name}测试失败: {e}")

            # 添加temp_foreground到结果
            method_results["temp_foreground"] = {"screenshot": reference_img, "similarity": 1.0, "time": 0.0}

        reliable_methods = []
        unreliable_methods = []

        for method, data in method_results.items():
            if data["similarity"] >= SIMILARITY_THRESHOLD:
                reliable_methods.append((method, data))
                self.logger.info(
                    f"方法[{method}]通过相似度检测 | 相似度: {data['similarity']:.3f} >= {SIMILARITY_THRESHOLD}"
                )
            else:
                unreliable_methods.append((method, data))
                self.logger.warning(
                    f"方法[{method}]相似度较低 | 相似度: {data['similarity']:.3f} < {SIMILARITY_THRESHOLD}，可能存在截图异常"
                )

        # 6. 选择最优方法
        if is_background_mode:
            # 后台模式：只能选择printwindow
            best_method = "printwindow"
            available_methods = ["printwindow"]
            self._screenshot_mode = "background"
        else:
            # 前台模式：根据相似度和性能选择
            if not reliable_methods:
                self.logger.warning("所有截图方法相似度均低于阈值，使用temp_foreground作为兜底")
                best_method = "temp_foreground"
                available_methods = ["temp_foreground"]
            else:
                reliable_methods.sort(key=lambda x: (1 - x[1]["similarity"], x[1]["time"]))
                best_method = reliable_methods[0][0]
                available_methods = [m[0] for m in reliable_methods]

                # 确保temp_foreground始终在可用方法列表中作为兜底
                if "temp_foreground" not in available_methods:
                    available_methods.append("temp_foreground")

            self._screenshot_mode = "foreground"

        self._available_screenshot_methods = available_methods
        self.logger.info(
            f"截图策略检测完成 | 最优方法: {best_method} | 可靠方法数: {len(reliable_methods)}/{len(method_results)} | 所有可用方法: {available_methods}"
        )

        return best_method

    def _detect_best_screenshot_strategy_fallback(self) -> str:
        """
        降级检测逻辑：当无法使用相似度比较时使用原有检测逻辑。

        Returns:
            str: 最优截图策略名称
        """
        window_manager = self.device.window_manager
        if not window_manager._is_window_ready():
            self.logger.warning("窗口未就绪，默认使用temp_foreground（foreground模式）")
            self._screenshot_mode = "foreground"
            self._available_screenshot_methods = ["temp_foreground"]
            return "temp_foreground"

        self.device._update_dynamic_window_info()
        client_w_phys, client_h_phys = self.device.display_context.client_physical_res
        if client_w_phys <= 0 or client_h_phys <= 0:
            self.logger.warning("窗口尺寸无效，默认使用temp_foreground（foreground模式）")
            self._screenshot_mode = "foreground"
            self._available_screenshot_methods = ["temp_foreground"]
            return "temp_foreground"

        def test_printwindow():
            try:
                hwnd_dc = win32gui.GetWindowDC(window_manager.hwnd)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                mem_dc = mfc_dc.CreateCompatibleDC()
                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, client_w_phys, client_h_phys)
                mem_dc.SelectObject(bitmap)

                result = ctypes.windll.user32.PrintWindow(window_manager.hwnd, mem_dc.GetSafeHdc(), 0)
                if not result:
                    raise RuntimeError("PrintWindow调用失败")

                bmp_str = bitmap.GetBitmapBits(True)
                img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                img_np = np.array(img_pil)
                mean_val = np.mean(img_np)

                mem_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(window_manager.hwnd, hwnd_dc)
                win32gui.DeleteObject(bitmap.GetHandle())

                return mean_val > 10
            except Exception as e:
                self.logger.debug(f"PrintWindow检测失败: {e}")
                return False

        def test_bitblt():
            try:
                is_already_foreground = win32gui.GetForegroundWindow() == window_manager.hwnd
                original_foreground = None

                if not is_already_foreground:
                    original_foreground = window_manager._temp_activate_window()

                hwnd_dc = win32gui.GetWindowDC(window_manager.hwnd)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                mem_dc = mfc_dc.CreateCompatibleDC()
                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, client_w_phys, client_h_phys)
                mem_dc.SelectObject(bitmap)

                mem_dc.BitBlt((0, 0), (client_w_phys, client_h_phys), mfc_dc, (0, 0), win32con.SRCCOPY)

                bmp_str = bitmap.GetBitmapBits(True)
                img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                img_np = np.array(img_pil)
                mean_val = np.mean(img_np)

                mem_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(window_manager.hwnd, hwnd_dc)
                win32gui.DeleteObject(bitmap.GetHandle())

                if not is_already_foreground and original_foreground and original_foreground != window_manager.hwnd:
                    window_manager._restore_foreground(original_foreground)

                return mean_val > 10
            except Exception as e:
                self.logger.debug(f"BitBlt检测失败: {e}")
                return False

        def test_dxcam():
            try:
                import dxcam

                is_already_foreground = win32gui.GetForegroundWindow() == window_manager.hwnd
                original_foreground = None

                if not is_already_foreground:
                    original_foreground = window_manager._temp_activate_window()

                camera = dxcam.create()
                if not camera:
                    raise RuntimeError("DXCam无法创建摄像头实例")

                client_origin_x, client_origin_y = win32gui.ClientToScreen(window_manager.hwnd, (0, 0))
                client_end_x = client_origin_x + client_w_phys
                client_end_y = client_origin_y + client_h_phys

                img_np = camera.grab(region=(client_origin_x, client_origin_y, client_end_x, client_end_y))
                if img_np is None:
                    raise RuntimeError("DXCam返回空图像")

                mean_val = np.mean(img_np)

                if not is_already_foreground and original_foreground and original_foreground != window_manager.hwnd:
                    window_manager._restore_foreground(original_foreground)

                return mean_val > 10
            except ImportError:
                self.logger.debug("dxcam未安装，跳过硬件加速截图检测")
                return False
            except Exception as e:
                self.logger.debug(f"DXCam检测失败: {e}")
                return False

        # 根据截图模式选择测试方法
        is_background_mode = self._screenshot_mode == "background"
        is_foreground_mode = self._screenshot_mode == "foreground" or not self._screenshot_mode

        available_methods = []

        if is_background_mode:
            # 后台模式：只测试printwindow
            self.logger.info("后台模式（降级），只测试printwindow方法")
            if test_printwindow():
                available_methods.append("printwindow")
            else:
                # 后台模式下printwindow失败，使用temp_foreground作为兜底
                available_methods.append("temp_foreground")

        else:  # 前台模式
            self.logger.info("前台模式（降级），测试bitblt、dxcam、temp_foreground方法")

            # 前台模式：确保窗口在前台
            if not win32gui.GetForegroundWindow() == window_manager.hwnd:
                self.logger.info("前台模式（降级），测试前激活窗口到前台")
                if not window_manager._activate_window(temp_activation=True):
                    self.logger.warning("窗口激活失败，部分截图方法可能无法正常测试")

            is_already_foreground = win32gui.GetForegroundWindow() == window_manager.hwnd

            if is_already_foreground or self._screenshot_mode == "foreground":
                if test_bitblt():
                    available_methods.append("bitblt")
                if test_dxcam():
                    available_methods.append("dxcam")
            else:
                self.logger.debug("窗口不在前台，跳过bitblt和dxcam检测，优先使用temp_foreground")

            available_methods.append("temp_foreground")

        self._available_screenshot_methods = available_methods
        self.logger.info(f"检测到可用的截图方法（降级模式）: {available_methods}")

        if is_background_mode:
            # 后台模式：只能选择printwindow
            best_method = "printwindow" if "printwindow" in available_methods else "temp_foreground"
            self._screenshot_mode = "background"
        else:
            # 前台模式：根据优先级选择
            if self._screenshot_mode == "foreground":
                best_method = self._select_best_method(["bitblt", "dxcam", "temp_foreground"], available_methods)
            else:
                best_method = self._select_best_method(["bitblt", "dxcam", "temp_foreground"], available_methods)

            self._screenshot_mode = "foreground"

        self.logger.info(f"截图策略检测结果（降级模式）：{best_method}（{self._screenshot_mode}模式）")
        return best_method

    def _try_print_window(self, client_w_phys: int, client_h_phys: int) -> Optional[np.ndarray]:
        """
        使用PrintWindow方法进行后台截图。

        Args:
            client_w_phys: 客户区物理宽度
            client_h_phys: 客户区物理高度

        Returns:
            Optional[np.ndarray]: 截图图像，失败返回None
        """
        try:
            window_manager = self.device.window_manager
            with self._DCCtxManager(window_manager.hwnd, client_w_phys, client_h_phys) as (mem_dc, bitmap):
                PW_CLIENTONLY = 1
                PW_RENDERFULLCONTENT = 0x00000002
                print_flags = PW_CLIENTONLY | PW_RENDERFULLCONTENT

                result = ctypes.windll.user32.PrintWindow(window_manager.hwnd, mem_dc.GetSafeHdc(), print_flags)
                if not result:
                    raise RuntimeError("PrintWindow调用返回失败")

                bmp_str = bitmap.GetBitmapBits(True)
                img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                img_np = np.array(img_pil)
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            if np.mean(img_np) < 10:
                raise RuntimeError("PrintWindow截图为黑屏")
            self.logger.debug("使用PrintWindow后台截图成功（仅客户区）")
            return img_np
        except Exception as e:
            self.logger.debug(f"PrintWindow执行失败: {e}")
            return None

    def _try_bitblt(self, client_w_phys: int, client_h_phys: int) -> Optional[np.ndarray]:
        """
        使用BitBlt方法进行前台截图。

        Args:
            client_w_phys: 客户区物理宽度
            client_h_phys: 客户区物理高度

        Returns:
            Optional[np.ndarray]: 截图图像，失败返回None
        """
        window_manager = self.device.window_manager
        original_foreground = None
        try:
            # 确保窗口在前台
            if win32gui.GetForegroundWindow() != window_manager.hwnd:
                original_foreground = window_manager._temp_activate_window()
                # 等待窗口稳定
                time.sleep(window_manager.TEMP_FOREGROUND_DELAY)

            # 发送WM_PAINT消息强制窗口重绘，避免获取缓存图像
            win32gui.InvalidateRect(window_manager.hwnd, None, True)
            win32gui.UpdateWindow(window_manager.hwnd)
            # 短暂延迟确保窗口重绘完成
            time.sleep(0.05)

            # 直接使用设备上下文进行截图，不嵌套使用DCCtxManager
            hwnd_dc = win32gui.GetDC(window_manager.hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            mem_dc = mfc_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, client_w_phys, client_h_phys)
            mem_dc.SelectObject(bitmap)

            # 使用BitBlt复制图像，直接使用CAPTUREBLT常量值确保获取最新内容
            CAPTUREBLT = 0x40000000  # win32con中没有这个常量，直接使用值
            mem_dc.BitBlt((0, 0), (client_w_phys, client_h_phys), mfc_dc, (0, 0), win32con.SRCCOPY | CAPTUREBLT)

            # 获取图像数据
            bmp_str = bitmap.GetBitmapBits(True)
            img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
            img_np = np.array(img_pil)
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            # 释放资源
            mem_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(window_manager.hwnd, hwnd_dc)
            win32gui.DeleteObject(bitmap.GetHandle())

            if np.mean(img_np) < 10:
                self.logger.debug("BitBlt截图为黑屏")
                return None

            self.logger.debug("使用BitBlt截图成功（仅客户区）")
            return img_np
        except Exception as e:
            self.logger.info(f"BitBlt执行失败: {e}")
            return None
        finally:
            # 恢复原始前台窗口
            if original_foreground and original_foreground != window_manager.hwnd:
                window_manager._restore_foreground(original_foreground)

    def _try_dxcam(self, client_w_phys: int, client_h_phys: int) -> Optional[np.ndarray]:
        """
        使用DXCam方法进行硬件加速截图。

        Args:
            client_w_phys: 客户区物理宽度
            client_h_phys: 客户区物理高度

        Returns:
            Optional[np.ndarray]: 截图图像，失败返回None
        """
        window_manager = self.device.window_manager
        original_foreground = None
        try:
            import dxcam

            # 确保窗口在前台
            if win32gui.GetForegroundWindow() != window_manager.hwnd:
                original_foreground = window_manager._temp_activate_window()
                # 等待窗口稳定
                time.sleep(window_manager.TEMP_FOREGROUND_DELAY)

            # 创建DXCam相机实例
            camera = dxcam.create()
            if not camera:
                self.logger.info("DXCam无法初始化，无可用显卡")
                return None

            # 获取客户区的屏幕坐标
            client_origin_x, client_origin_y = win32gui.ClientToScreen(window_manager.hwnd, (0, 0))
            client_end_x = client_origin_x + client_w_phys
            client_end_y = client_origin_y + client_h_phys

            # 验证坐标是否有效
            if (
                client_origin_x < 0
                or client_origin_y < 0
                or client_end_x <= client_origin_x
                or client_end_y <= client_origin_y
            ):
                self.logger.info(
                    f"DXCam截图区域无效: ({client_origin_x}, {client_origin_y}, {client_end_x}, {client_end_y})"
                )
                return None

            # 尝试多次截图，提高成功率
            for attempt in range(3):
                img_np = camera.grab(region=(client_origin_x, client_origin_y, client_end_x, client_end_y))
                if img_np is not None:
                    break
                # 每次尝试后短暂延迟
                time.sleep(0.05)

            if img_np is None:
                self.logger.info("DXCam多次尝试截图均返回空图像")
                return None

            # 转换颜色空间并验证截图
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            if np.mean(img_np) < 10:
                self.logger.info("DXCam截图为黑屏")
                return None

            self.logger.debug("使用DXCam硬件加速截图成功（仅客户区）")
            return img_np
        except ImportError:
            self.logger.info("dxcam未安装，跳过硬件加速截图")
            return None
        except Exception as e:
            self.logger.info(f"DXCam执行失败: {e}")
            return None
        finally:
            # 恢复原始前台窗口
            if original_foreground and original_foreground != window_manager.hwnd:
                window_manager._restore_foreground(original_foreground)

    def _try_temp_foreground_screenshot(self, client_w_phys: int, client_h_phys: int) -> Optional[np.ndarray]:
        """
        使用临时置顶窗口方法进行截图。

        Args:
            client_w_phys: 客户区物理宽度
            client_h_phys: 客户区物理高度

        Returns:
            Optional[np.ndarray]: 截图图像，失败返回None
        """
        window_manager = self.device.window_manager
        self.logger.debug(
            f"开始temp_foreground截图 | 窗口句柄: {window_manager.hwnd} | 尺寸: {client_w_phys}x{client_h_phys}"
        )
        original_foreground = window_manager._get_original_foreground()
        try:
            # 使用SwitchToThisWindow激活窗口（绕过SetForegroundWindow限制）
            try:
                ctypes.windll.user32.SwitchToThisWindow(window_manager.hwnd, True)
                self.logger.debug("SwitchToThisWindow成功")
            except Exception as e1:
                self.logger.debug(f"SwitchToThisWindow失败: {e1}")
                try:
                    win32gui.SetForegroundWindow(window_manager.hwnd)
                    self.logger.debug("SetForegroundWindow成功")
                except Exception as e2:
                    self.logger.debug(f"SetForegroundWindow失败: {e2}")

            # 等待窗口置顶，确保截图成功
            time.sleep(window_manager.TEMP_FOREGROUND_DELAY)

            # 确保窗口是当前前台窗口
            if win32gui.GetForegroundWindow() != window_manager.hwnd:
                self.logger.warning(
                    f"窗口未成功置顶，当前前台句柄: {win32gui.GetForegroundWindow()}，目标句柄: {window_manager.hwnd}"
                )
                # 再次尝试激活
                try:
                    win32gui.SetForegroundWindow(window_manager.hwnd)
                    time.sleep(window_manager.TEMP_FOREGROUND_DELAY)
                except Exception:
                    pass

            client_origin_x, client_origin_y = win32gui.ClientToScreen(window_manager.hwnd, (0, 0))
            client_end_x = client_origin_x + client_w_phys
            client_end_y = client_origin_y + client_h_phys
            self.logger.debug(f"客户区屏幕坐标: ({client_origin_x}, {client_origin_y})")

            hdc_screen = win32gui.GetDC(0)
            mfc_dc = win32ui.CreateDCFromHandle(hdc_screen)
            mem_dc = mfc_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, client_w_phys, client_h_phys)
            mem_dc.SelectObject(bitmap)

            result = mem_dc.BitBlt(
                (0, 0),
                (client_w_phys, client_h_phys),
                mfc_dc,
                (client_origin_x, client_origin_y),
                win32con.SRCCOPY,
            )
            self.logger.debug(f"BitBlt结果: {result}")

            bmp_str = bitmap.GetBitmapBits(True)
            img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
            img_np = np.array(img_pil)
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            mem_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(0, hdc_screen)
            win32gui.DeleteObject(bitmap.GetHandle())

            window_manager._restore_foreground(original_foreground)
            self.logger.debug("使用临时置顶屏幕截图成功（仅客户区，终极兜底）")
            return img_np
        except Exception as e:
            self.logger.debug(f"临时置顶屏幕截图失败: {e}")
            if original_foreground:
                try:
                    window_manager._restore_foreground(original_foreground)
                except Exception:
                    pass
            return None

    def capture_screen(self, roi: Optional[Tuple[int, int, int, int]] = None) -> Optional[np.ndarray]:
        """
        屏幕截图，支持多种截图策略和ROI裁剪。

        Args:
            roi: 可选，感兴趣区域，格式为(x, y, width, height)

        Returns:
            Optional[np.ndarray]: 截图图像（BGR格式），失败返回None
        """
        self.device.clear_last_error()
        window_manager = self.device.window_manager
        if not window_manager._is_window_ready():
            self.device._record_error("capture_screen", "窗口未连接/最小化，无法截图")
            self.logger.error(self.device.last_error)
            return None

        if not self.device._update_dynamic_window_info():
            self.logger.warning("窗口动态信息更新失败，使用缓存尺寸")

        client_w_phys, client_h_phys = self.device.display_context.client_physical_res
        self.logger.debug(f"截图客户区尺寸: {client_w_phys}x{client_h_phys}")

        # 如果客户区尺寸无效，直接使用窗口矩形进行截图
        if client_w_phys <= 0 or client_h_phys <= 0:
            self.logger.warning(f"窗口客户区尺寸无效({client_w_phys}x{client_h_phys})，使用窗口矩形进行截图")
            try:
                window_rect = win32gui.GetWindowRect(window_manager.hwnd)
                self.logger.debug(f"兜底窗口矩形: {window_rect}")
                if all(coord == 0 for coord in window_rect):
                    self.device._record_error("capture_screen", f"窗口矩形无效: {window_rect}")
                    self.logger.error(self.device.last_error)
                    return None

                client_w_phys = window_rect[2] - window_rect[0]
                client_h_phys = window_rect[3] - window_rect[1]
                self.logger.debug(f"兜底客户区尺寸: {client_w_phys}x{client_h_phys}")
            except Exception as e:
                self.device._record_error("capture_screen", f"获取窗口矩形失败: {str(e)}")
                self.logger.error(self.device.last_error)
                return None

        # 最终兜底：使用屏幕分辨率
        if client_w_phys <= 0 or client_h_phys <= 0:
            self.logger.warning("窗口尺寸仍无效，使用屏幕分辨率作为最终兜底")
            screen_res = self.device._get_screen_hardware_res()
            client_w_phys, client_h_phys = screen_res
            self.logger.debug(f"兜底屏幕分辨率: {client_w_phys}x{client_h_phys}")

        # -------------------------- 各策略实现 --------------------------
        def try_print_window():
            try:
                with self._DCCtxManager(window_manager.hwnd, client_w_phys, client_h_phys) as (mem_dc, bitmap):
                    PW_CLIENTONLY = 1
                    PW_RENDERFULLCONTENT = 0x00000002
                    print_flags = PW_CLIENTONLY | PW_RENDERFULLCONTENT

                    result = ctypes.windll.user32.PrintWindow(window_manager.hwnd, mem_dc.GetSafeHdc(), print_flags)
                    if not result:
                        raise RuntimeError("PrintWindow调用返回失败")

                    bmp_str = bitmap.GetBitmapBits(True)
                    img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                    img_np = np.array(img_pil)
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                if np.mean(img_np) < 10:
                    raise RuntimeError("PrintWindow截图为黑屏")
                self.logger.debug("使用PrintWindow后台截图成功（仅客户区）")
                return img_np
            except Exception as e:
                self.logger.debug(f"PrintWindow执行失败: {e}")
                return None

        def try_bitblt():
            """增强版bitblt：添加临时激活窗口逻辑"""
            original_foreground = None
            try:
                # 临时激活窗口
                original_foreground = window_manager._temp_activate_window()

                with self._DCCtxManager(window_manager.hwnd, client_w_phys, client_h_phys) as (mem_dc, bitmap):
                    # 获取原始DC用于BitBlt操作
                    hwnd_dc = win32gui.GetDC(window_manager.hwnd)
                    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)

                    mem_dc.BitBlt((0, 0), (client_w_phys, client_h_phys), mfc_dc, (0, 0), win32con.SRCCOPY)

                    # 释放原始DC资源
                    win32gui.ReleaseDC(window_manager.hwnd, hwnd_dc)
                    mfc_dc.DeleteDC()

                    bmp_str = bitmap.GetBitmapBits(True)
                    img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                    img_np = np.array(img_pil)
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                if np.mean(img_np) < 10:
                    raise RuntimeError("BitBlt截图为黑屏")

                self.logger.debug("使用BitBlt截图成功（仅客户区）")
                return img_np
            except Exception as e:
                self.logger.debug(f"BitBlt执行失败: {e}")
                return None
            finally:
                # 恢复原始前台窗口
                if original_foreground and original_foreground != window_manager.hwnd:
                    window_manager._restore_foreground(original_foreground)

        def try_dxcam():
            """增强版dxcam：添加临时激活窗口逻辑"""
            original_foreground = None
            try:
                import dxcam

                # 临时激活窗口
                original_foreground = window_manager._temp_activate_window()

                camera = dxcam.create()
                if not camera:
                    raise RuntimeError("DXCam无法初始化，无可用显卡")

                client_origin_x, client_origin_y = win32gui.ClientToScreen(window_manager.hwnd, (0, 0))
                client_end_x = client_origin_x + client_w_phys
                client_end_y = client_origin_y + client_h_phys

                img_np = camera.grab(region=(client_origin_x, client_origin_y, client_end_x, client_end_y))
                if img_np is None:
                    raise RuntimeError("DXCam截图返回空图像")

                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                self.logger.debug("使用DXCam硬件加速截图成功（仅客户区）")
                return img_np
            except ImportError:
                self.logger.debug("dxcam未安装，跳过硬件加速截图")
                return None
            except Exception as e:
                self.logger.debug(f"DXCam执行失败: {e}")
                return None
            finally:
                # 恢复原始前台窗口
                if original_foreground and original_foreground != window_manager.hwnd:
                    window_manager._restore_foreground(original_foreground)

        def try_temp_foreground_screenshot():
            self.logger.debug(
                f"开始temp_foreground截图 | 窗口句柄: {window_manager.hwnd} | 尺寸: {client_w_phys}x{client_h_phys}"
            )
            original_foreground = window_manager._get_original_foreground()
            try:
                # 使用SwitchToThisWindow激活窗口（绕过SetForegroundWindow限制）
                try:
                    ctypes.windll.user32.SwitchToThisWindow(window_manager.hwnd, True)
                    self.logger.debug("SwitchToThisWindow成功")
                except Exception as e1:
                    self.logger.debug(f"SwitchToThisWindow失败: {e1}")
                    try:
                        win32gui.SetForegroundWindow(window_manager.hwnd)
                        self.logger.debug("SetForegroundWindow成功")
                    except Exception as e2:
                        self.logger.debug(f"SetForegroundWindow失败: {e2}")

                # 等待窗口置顶，确保截图成功
                time.sleep(window_manager.TEMP_FOREGROUND_DELAY)

                # 确保窗口是当前前台窗口
                if win32gui.GetForegroundWindow() != window_manager.hwnd:
                    self.logger.warning(
                        f"窗口未成功置顶，当前前台句柄: {win32gui.GetForegroundWindow()}，目标句柄: {window_manager.hwnd}"
                    )
                    # 再次尝试激活
                    try:
                        win32gui.SetForegroundWindow(window_manager.hwnd)
                        time.sleep(window_manager.TEMP_FOREGROUND_DELAY)
                    except Exception:
                        pass

                client_origin_x, client_origin_y = win32gui.ClientToScreen(window_manager.hwnd, (0, 0))
                client_end_x = client_origin_x + client_w_phys
                client_end_y = client_origin_y + client_h_phys
                self.logger.debug(f"客户区屏幕坐标: ({client_origin_x}, {client_origin_y})")

                hdc_screen = win32gui.GetDC(0)
                mfc_dc = win32ui.CreateDCFromHandle(hdc_screen)
                mem_dc = mfc_dc.CreateCompatibleDC()
                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, client_w_phys, client_h_phys)
                mem_dc.SelectObject(bitmap)

                result = mem_dc.BitBlt(
                    (0, 0),
                    (client_w_phys, client_h_phys),
                    mfc_dc,
                    (client_origin_x, client_origin_y),
                    win32con.SRCCOPY,
                )
                self.logger.debug(f"BitBlt结果: {result}")

                bmp_str = bitmap.GetBitmapBits(True)
                img_pil = Image.frombuffer("RGB", (client_w_phys, client_h_phys), bmp_str, "raw", "BGRX", 0, 1)
                img_np = np.array(img_pil)
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                mem_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(0, hdc_screen)
                win32gui.DeleteObject(bitmap.GetHandle())

                window_manager._restore_foreground(original_foreground)
                self.logger.debug("使用临时置顶屏幕截图成功（仅客户区，终极兜底）")
                return img_np
            except Exception as e:
                self.logger.debug(f"临时置顶屏幕截图失败: {e}")
                if original_foreground:
                    try:
                        window_manager._restore_foreground(original_foreground)
                    except Exception:
                        pass
                return None

        # -------------------------- 模式适配：执行截图策略 --------------------------
        img_np = None

        # 检查窗口是否在前台
        is_foreground = win32gui.GetForegroundWindow() == window_manager.hwnd

        # 窗口在前台时，优先使用更可靠的截图方法，避免BitBlt缓存问题
        if is_foreground:
            self.logger.debug("窗口在前台，优先使用更可靠的截图方法")
            # 优先使用dxcam（硬件加速，无缓存问题），失败再尝试bitblt，最后尝试printwindow
            img_np = self._try_dxcam(client_w_phys, client_h_phys)
            if img_np is None:
                img_np = self._try_bitblt(client_w_phys, client_h_phys)
                # BitBlt可能有缓存问题，添加验证
                if img_np is not None:
                    self.logger.debug("BitBlt截图完成，注意：可能存在缓存问题")
            if img_np is None:
                img_np = self._try_print_window(client_w_phys, client_h_phys)

        # 如果temp_foreground失败或者窗口不在前台，再尝试其他截图方法
        if img_np is None:
            # 如果设置了具体的截图方法，尝试该方法
            if self._screenshot_mode in ["temp_foreground", "bitblt", "dxcam", "printwindow"]:
                self.logger.debug(f"使用已设置的截图方法: {self._screenshot_mode}")
                if self._screenshot_mode == "temp_foreground":
                    img_np = self._try_temp_foreground_screenshot(client_w_phys, client_h_phys)
                elif self._screenshot_mode == "bitblt":
                    img_np = self._try_bitblt(client_w_phys, client_h_phys)
                elif self._screenshot_mode == "dxcam":
                    img_np = self._try_dxcam(client_w_phys, client_h_phys)
                elif self._screenshot_mode == "printwindow":
                    img_np = self._try_print_window(client_w_phys, client_h_phys)
            # background截图模式：强制使用PrintWindow，失败则降级
            elif self._screenshot_mode == "background":
                img_np = self._try_print_window(client_w_phys, client_h_phys)
            # foreground截图模式：优先使用更可靠的截图方法，避免BitBlt缓存问题
            elif self._screenshot_mode == "foreground":
                self.logger.debug("foreground截图模式优先使用更可靠的截图方法")
                # 优先使用dxcam（硬件加速，无缓存问题），失败再尝试bitblt，最后尝试printwindow和temp_foreground
                img_np = self._try_dxcam(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_bitblt(client_w_phys, client_h_phys)
                    # BitBlt可能有缓存问题，添加验证
                    if img_np is not None:
                        self.logger.debug("BitBlt截图完成，注意：可能存在缓存问题")
                if img_np is None:
                    img_np = self._try_print_window(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_temp_foreground_screenshot(client_w_phys, client_h_phys)
            else:
                # 兜底：优先使用更稳定的截图方法，避免temp_foreground导致的闪烁
                self.logger.warning(f"未知截图模式: {self._screenshot_mode}，使用更稳定的截图方法兜底")
                img_np = self._try_print_window(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_bitblt(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_dxcam(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_temp_foreground_screenshot(client_w_phys, client_h_phys)

            # 如果指定的截图方法失败，执行降级流程
            if img_np is None:
                self.logger.debug(f"指定截图方法 {self._screenshot_mode} 失败，执行降级流程")
                # 尝试所有其他可用方法，按优先级排序
                img_np = self._try_temp_foreground_screenshot(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_bitblt(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_dxcam(client_w_phys, client_h_phys)
                if img_np is None:
                    img_np = self._try_print_window(client_w_phys, client_h_phys)

        # 所有策略均失败
        if img_np is None:
            self.device._record_error("capture_screen", "所有截图策略均失败")
            self.logger.error(self.device.last_error)
            return None

        # -------------------------- ROI裁剪处理 --------------------------
        if roi:
            is_valid, err_msg = self.device.coord_transformer.validate_roi_format(roi)
            if not is_valid:
                self.logger.warning(f"ROI无效: {err_msg}")
            else:
                screen_phys_rect = self.device.coord_transformer.convert_client_logical_rect_to_screen_physical(
                    roi, is_base_coord=True
                )
                if screen_phys_rect:
                    phys_x, phys_y, phys_w, phys_h = screen_phys_rect

                    # 全屏/窗口模式区分处理
                    ctx = self.device.display_context
                    if ctx.is_fullscreen:
                        # 全屏模式：截图直接对应屏幕物理坐标，无需考虑客户区原点
                        crop_x = max(0, phys_x)
                        crop_y = max(0, phys_y)
                        # 使用屏幕物理尺寸作为边界
                        screen_w, screen_h = ctx.screen_physical_res
                        crop_w = min(phys_w, screen_w - crop_x)
                        crop_h = min(phys_h, screen_h - crop_y)
                        self.logger.debug(
                            f"全屏模式ROI裁剪 | 屏幕物理坐标: ({phys_x},{phys_y},{phys_w},{phys_h}) → 裁剪区域: ({crop_x},{crop_y},{crop_w},{crop_h})"
                        )
                    else:
                        # 窗口模式：计算相对客户区的裁剪坐标
                        crop_x = max(0, phys_x - self.device.display_context.client_screen_origin[0])
                        crop_y = max(0, phys_y - self.device.display_context.client_screen_origin[1])
                        crop_w = min(phys_w, client_w_phys - crop_x)
                        crop_h = min(phys_h, client_h_phys - crop_y)
                        self.logger.debug(
                            f"窗口模式ROI裁剪 | 屏幕物理坐标: ({phys_x},{phys_y},{phys_w},{phys_h}) → 客户区: ({crop_x},{crop_y},{crop_w},{crop_h})"
                        )

                    if crop_w > 0 and crop_h > 0:
                        img_np = img_np[crop_y : crop_y + crop_h, crop_x : crop_x + crop_w]
                        self.logger.debug(
                            f"截图ROI裁剪完成 | 原始: {roi} → 实际裁剪: ({crop_x},{crop_y},{crop_w},{crop_h})"
                        )
                    else:
                        self.logger.warning(f"ROI转换后无效: {roi}")

        return img_np
