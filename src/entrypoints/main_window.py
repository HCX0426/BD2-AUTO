# 首先初始化路径，确保所有模块可以被正确导入
import os
import sys

# 获取项目根目录（src的父目录）
current_file = os.path.abspath(__file__)
project_root = os.path.abspath(os.path.join(current_file, "..", "..", ".."))

# 添加项目根目录到sys.path
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    print(f"项目根目录已添加到sys.path: {project_root}")

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# 现在可以导入src模块了
from src.core.path_manager import path_manager
from src.core.task_loader import load_task_modules
from src.ui.controls.main_interface import MainInterface
from src.ui.controls.settings_interface import SettingsInterface
from src.ui.controls.sidebar import Sidebar
from src.ui.core.settings import AppSettingsManager
from src.ui.core.task_config import TaskConfigManager


class MainWindow(QMainWindow):
    """
    主窗口类，负责组装所有UI组件和后台线程
    使用信号总线实现组件之间的解耦通信
    """

    def __init__(self, settings_manager, config_manager, task_mapping):
        """
        初始化主窗口

        Args:
            settings_manager: 应用设置管理器
            config_manager: 任务配置管理器
            task_mapping: 任务映射字典
        """
        super().__init__()

        # 初始化管理器
        self.settings_manager = settings_manager
        self.config_manager = config_manager

        # 任务映射和工作线程
        self.task_mapping = task_mapping
        self.auto_instance = None
        self.task_worker = None
        self.auto_init_thread = None
        self.task_running = False

        # 任务线程管理
        self.task_worker = None

        # 任务停止相关变量
        self.stop_timer = None
        self.stop_attempts = 0
        self.max_stop_attempts = 20  # 最大停止尝试次数(约10秒)

        # 侧边栏状态
        self.sidebar_hidden = False
        self.sidebar_dragging = False
        self.sidebar_hovered = False

        # 初始化UI
        self.init_ui()

        # 连接信号
        self.connect_signals()
        # 注意：自动初始化线程不在__init__中启动，而是在QApplication创建完成后启动

        # 初始化时设置开始按钮为"初始化中..."
        self.main_interface.enable_task_controls(start_enabled=True, stop_enabled=False, start_text="初始化中...")

    def init_ui(self):
        """初始化主窗口UI"""
        self.setWindowTitle("自动任务控制系统")

        # 设置窗口大小
        self.resize(*self.settings_manager.get_setting("window_size", [1280, 720]))
        self.setMinimumSize(1024, 600)

        # 如果设置了记住窗口位置，则加载位置，否则居中显示
        if self.settings_manager.get_setting("remember_window_pos", True):
            window_pos = self.settings_manager.get_setting("window_pos", None)
            if window_pos:
                self.move(window_pos[0], window_pos[1])
            else:
                # 如果没有保存的位置，则居中显示
                self.center_window()
        else:
            # 如果不记住位置，则居中显示
            self.center_window()

        # 主窗口布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 侧边栏
        self.stacked_widget = QStackedWidget()
        self.sidebar = Sidebar(self.settings_manager, self.stacked_widget)
        main_layout.addWidget(self.sidebar)

        # 主内容区域
        self.init_main_interface()
        self.init_settings_interface()
        main_layout.addWidget(self.stacked_widget, 1)

    def center_window(self):
        """
        将窗口居中显示在屏幕上
        """
        # 获取屏幕的几何信息
        screen_geometry = self.screen().geometry()
        # 获取窗口的几何信息
        window_geometry = self.frameGeometry()
        # 计算居中位置
        window_geometry.moveCenter(screen_geometry.center())
        # 移动窗口到居中位置
        self.move(window_geometry.topLeft())

    def init_main_interface(self):
        """初始化主界面组件"""
        self.main_interface = MainInterface(self.config_manager, self.task_mapping)
        self.stacked_widget.addWidget(self.main_interface)

    def init_settings_interface(self):
        """初始化设置界面组件"""
        self.settings_interface = SettingsInterface(self.settings_manager)
        self.stacked_widget.addWidget(self.settings_interface)

    def connect_signals(self):
        """连接所有信号"""
        # 确保信号总线已经初始化
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        # 信号总线连接
        signal_bus.init_completed.connect(self.on_auto_init_completed)
        signal_bus.init_failed.connect(self.on_auto_init_failed)
        signal_bus.task_status_updated.connect(self.on_task_status_updated)
        signal_bus.device_status_updated.connect(self.on_device_status_updated)
        signal_bus.task_finished.connect(self.on_task_finished)

    def start_auto_init_thread(self):
        """
        启动自动初始化线程
        """
        import os

        from src.ui.background.auto_initializer import AutoInitThread

        # 从设置中获取设备参数
        device_type = self.settings_manager.get_setting("device_type", "windows")
        device_path = self.settings_manager.get_setting("device_path", "")
        ocr_engine = self.settings_manager.get_setting("ocr_engine", "easyocr")
        device_uri = None

        # 根据设备类型和路径生成device_uri
        if device_path:
            if device_type == "windows":
                # 如果是EXE文件，提取文件名作为标题匹配
                if device_path.endswith(".exe"):
                    exe_name = os.path.basename(device_path)
                    # 使用标题正则表达式匹配
                    device_uri = f"Windows:///?title_re=.*{exe_name[:-4]}.*"
                else:
                    # 否则直接作为URI
                    device_uri = device_path
            else:  # adb
                device_uri = device_path

        self.auto_init_thread = AutoInitThread(
            device_type=device_type,
            device_uri=device_uri,
            ocr_engine=ocr_engine,
            settings_manager=self.settings_manager,
        )
        self.auto_init_thread.finished.connect(self.auto_init_thread.deleteLater)
        self.auto_init_thread.start()

    @pyqtSlot(object)
    def on_auto_init_completed(self, auto_instance):
        """自动初始化完成槽函数"""
        self.auto_instance = auto_instance
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        # 应用设置中的截图模式和点击模式到设备
        device = self.auto_instance.device_manager.get_active_device()
        if device:
            # 获取截图模式设置
            screenshot_mode_setting = self.settings_manager.get_setting("screenshot_mode", "自动选择")
            # 转换为设备支持的截图模式
            screenshot_mode_map = {
                "自动选择": None,  # 使用设备自动检测的最优策略
                "PrintWindow": "printwindow",
                "BitBlt": "bitblt",
                "DXCam": "dxcam",
                "临时激活": "temp_foreground",
            }
            screenshot_mode = screenshot_mode_map.get(screenshot_mode_setting)
            if screenshot_mode:
                device.screenshot_mode = screenshot_mode
                signal_bus.emit_log(f"已设置截图模式: {screenshot_mode_setting}")

            # 获取点击模式设置
            click_mode_setting = self.settings_manager.get_setting("click_mode", "前台点击")
            # 转换为设备支持的点击模式
            click_mode_map = {"前台点击": "foreground", "后台点击": "background"}
            click_mode = click_mode_map.get(click_mode_setting)
            if click_mode:
                device.click_mode = click_mode
                signal_bus.emit_log(f"已设置点击模式: {click_mode_setting}")

        signal_bus.emit_log("自动化核心初始化完成，系统就绪")
        self.main_interface.enable_task_controls(start_enabled=True, stop_enabled=False)

    @pyqtSlot(str)
    def on_auto_init_failed(self, error_msg):
        """自动初始化失败槽函数"""
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        signal_bus.emit_log(f"自动化核心初始化失败: {error_msg}")
        QMessageBox.warning(self, "初始化失败", f"自动化核心初始化失败:\n{error_msg}")
        self.main_interface.enable_task_controls(start_enabled=True, stop_enabled=False)

    @pyqtSlot(str, bool)
    def on_task_status_updated(self, task_type, is_running):
        """任务状态更新槽函数"""
        if task_type == "main":
            if is_running:
                self.start_task()
            else:
                self.stop_task()

    @pyqtSlot(str, bool)
    def on_device_status_updated(self, action, is_running):
        """设备状态更新槽函数"""
        if action == "launch_game" and is_running:
            self.launch_game()

    def start_task(self):
        """
        开始执行任务
        """
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        if not self.auto_instance:
            if self.auto_init_thread and self.auto_init_thread.isRunning():
                signal_bus.emit_log("自动化核心正在后台初始化，请稍候...")
                self.main_interface.enable_task_controls(
                    start_enabled=True, stop_enabled=False, start_text="初始化中..."
                )
                return
            else:
                # 启动初始化线程
                signal_bus.emit_log("正在初始化自动化核心...")
                self.start_auto_init_thread()
                self.main_interface.enable_task_controls(
                    start_enabled=True, stop_enabled=False, start_text="初始化中..."
                )
                return

        # 检查任务是否已经在运行
        if self.task_running:
            signal_bus.emit_log("警告：任务已经在运行中")
            return

        # 获取选中的任务
        selected_tasks = self.main_interface.get_selected_tasks()
        if not selected_tasks:
            signal_bus.emit_log("错误：未选择任何任务")
            self.main_interface.enable_task_controls(start_enabled=True, stop_enabled=False)
            return

        # 启动任务前，强制重置所有停止标志
        self.auto_instance.set_should_stop(False)  # 重置Auto实例的停止标志

        # 设置任务运行状态
        self.task_running = True
        signal_bus.emit_log(f"开始执行 {len(selected_tasks)} 个任务")

        # 导入TaskWorker
        from src.ui.background.task_worker import TaskWorker

        # 创建任务工作器
        self.task_worker = TaskWorker(self.auto_instance, selected_tasks, self.config_manager, self.task_mapping)

        # 连接信号
        self.task_worker.task_finished.connect(self.on_task_finished)

        # 启动任务线程
        self.task_worker.start()

        signal_bus.emit_log("任务已开始执行")

    def stop_task(self):
        """
        停止执行任务
        """
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        if not self.task_running:
            return

        # 使用QTimer确保在主线程中执行UI操作
        QTimer.singleShot(0, lambda: signal_bus.emit_log("收到停止指令，正在终止任务..."))
        # 立即发送任务终止开始的日志
        QTimer.singleShot(0, lambda: signal_bus.emit_log("任务终止开始"))

        self.stop_attempts = 0  # 重置尝试次数

        # 通知任务停止
        if self.auto_instance:
            self.auto_instance.set_should_stop(True)

        # 通知worker停止
        if self.task_worker:
            self.task_worker.stop()

        # 启动定时器，轮询检查任务是否已终止
        if self.stop_timer and self.stop_timer.isActive():
            self.stop_timer.stop()

        # 创建新的定时器，确保在主线程中执行
        def start_check_timer():
            self.stop_timer = QTimer()
            self.stop_timer.setInterval(500)  # 每500ms检查一次
            self.stop_timer.timeout.connect(self.check_task_stopped)
            self.stop_timer.start()

        QTimer.singleShot(0, start_check_timer)

    def check_task_stopped(self):
        """
        轮询检查任务是否已停止
        """
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        self.stop_attempts += 1

        # 检查任务线程是否已停止
        worker_stopped = not (self.task_worker and self.task_worker.isRunning())

        if worker_stopped:
            if self.stop_timer:
                self.stop_timer.stop()
                self.stop_timer = None
            # 只有在任务仍在运行状态时才进行清理，避免重复
            if self.task_running:
                signal_bus.emit_log("任务已完全终止")
                self.reset_task_state()
        else:
            # 显示任务终止进度
            remaining_seconds = (self.max_stop_attempts - self.stop_attempts) * 0.5
            signal_bus.emit_log(f"任务终止进行中... (剩余约 {remaining_seconds:.1f} 秒)")

            # 达到最大尝试次数，强制终止
            if self.stop_attempts >= self.max_stop_attempts:
                signal_bus.emit_log(f"超过最大等待次数 ({self.max_stop_attempts}次)，将强制终止任务")
                if self.stop_timer:
                    self.stop_timer.stop()
                    self.stop_timer = None

                # 强制终止任务
                self.auto_instance.set_should_stop(True)
                if self.task_worker and self.task_worker.isRunning():
                    self.task_worker.terminate()
                    self.task_worker.wait(1000)  # 等待1秒
                signal_bus.emit_log("任务已强制终止")
                self.reset_task_state(force=True)

    def reset_task_state(self, force=False):
        """
        重置任务状态
        """
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        self.task_running = False
        self.main_interface.enable_task_controls(start_enabled=True, stop_enabled=False)

        # 清理任务工作器
        if self.task_worker:
            try:
                # 断开信号连接
                self.task_worker.task_finished.disconnect(self.on_task_finished)
            except:
                pass  # 忽略已经断开的连接

            # 如果线程仍在运行，尝试停止
            if self.task_worker.isRunning():
                if force:
                    signal_bus.emit_log("正在强制终止任务线程...")
                    self.task_worker.terminate()
                    self.task_worker.wait(1000)  # 等待1秒
                else:
                    self.task_worker.stop()

            # 清理任务工作器引用
            self.task_worker = None

        signal_bus.emit_log("任务状态已重置")

    def on_task_finished(self):
        """
        任务完成槽函数
        """
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        signal_bus.emit_log("所有任务执行完成")
        self.reset_task_state()

    def launch_game(self):
        """启动游戏"""
        import os
        import shlex
        import subprocess

        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        # 从设备设置中获取游戏路径和启动参数
        device_type = self.settings_manager.get_setting("device_type", "windows")
        device_path = self.settings_manager.get_setting("device_path", "")
        device_args = self.settings_manager.get_setting("device_args", "")

        # 如果是Windows设备且设备路径包含EXE文件，则启动该游戏
        if device_type == "windows":
            try:
                # 检查路径是否存在
                if not os.path.exists(device_path):
                    QMessageBox.critical(self, "错误", f"游戏路径不存在: {device_path}")
                    signal_bus.emit_log(f"错误：游戏路径不存在: {device_path}")
                    return

                # 组合游戏路径和启动参数
                full_cmd = f"{device_path} {device_args}"

                # 解析命令行
                cmd = shlex.split(full_cmd)

                # 启动游戏
                subprocess.Popen(cmd)
                signal_bus.emit_log(f"已启动游戏: {full_cmd}")

            except Exception as e:
                signal_bus.emit_log(f"启动游戏失败: {str(e)}")
                QMessageBox.critical(self, "错误", f"启动游戏失败: {str(e)}")
        else:
            # 否则使用旧的游戏路径设置（兼容旧版本）
            pc_game_path = self.settings_manager.get_setting("pc_game_path", "")
            if pc_game_path:
                try:
                    # 处理带有命令行参数的情况
                    if ".exe" in pc_game_path:
                        # 查找EXE文件的结束位置
                        exe_end_index = pc_game_path.index(".exe") + 4
                        exe_path = pc_game_path[:exe_end_index]

                        if not os.path.exists(exe_path):
                            QMessageBox.critical(self, "错误", f"游戏路径不存在: {exe_path}")
                            signal_bus.emit_log(f"错误：游戏路径不存在: {exe_path}")
                            return

                        # 解析命令行参数
                        cmd = shlex.split(pc_game_path)

                        # 启动游戏
                        subprocess.Popen(cmd)
                        signal_bus.emit_log(f"已启动游戏: {pc_game_path}")

                except Exception as e:
                    signal_bus.emit_log(f"启动游戏失败: {str(e)}")
                    QMessageBox.critical(self, "错误", f"启动游戏失败: {str(e)}")
            else:
                QMessageBox.warning(self, "警告", "请先在设备设置中配置PC游戏路径")
                signal_bus.emit_log("警告：未配置PC游戏路径")

    def closeEvent(self, event: QCloseEvent):
        """
        关闭窗口事件处理，确保任务完全终止后再关闭窗口
        """
        # 保存窗口大小
        self.settings_manager.set_setting("window_size", [self.width(), self.height()])

        # 如果设置了记住窗口位置，则保存位置
        if self.settings_manager.get_setting("remember_window_pos", True):
            self.settings_manager.set_setting("window_pos", [self.x(), self.y()])

        self.settings_manager.save_settings()
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        # 停止正在运行的任务
        if self.task_running:
            signal_bus.emit_log("检测到正在运行的任务，尝试终止后再关闭窗口...")
            self.stop_task()

            # 不阻塞主线程，改为使用定时器检查任务是否已终止
            self.close_event = event
            self.close_timer = QTimer()
            self.close_timer.setInterval(200)  # 每200ms检查一次
            self.close_timer.timeout.connect(self.check_task_stopped_before_close)
            self.close_timer.start()
            self.close_wait_time = 0
            event.ignore()  # 先忽略关闭事件，等待任务终止
            return

        # 停止自动化核心
        if self.auto_instance:
            signal_bus.emit_log("正在停止自动化核心...")
            self.auto_instance.set_should_stop(True)
            # 只设置标志，不调用stop()方法，避免重复清理和logger问题
            # self.auto_instance.stop()  # 会在perform_close中调用

        # 任务未运行，直接关闭
        self.perform_close(event)

    def check_task_stopped_before_close(self):
        """
        检查任务是否已停止，用于窗口关闭前的异步等待
        """
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        self.close_wait_time += 1

        if not self.task_running:
            # 任务已终止，执行关闭
            self.close_timer.stop()
            self.perform_close(self.close_event)
        elif self.close_wait_time > 25:  # 5秒超时
            # 超时，直接强制关闭
            self.close_timer.stop()
            signal_bus.emit_log("等待任务终止超时，强制关闭窗口")
            self.reset_task_state(force=True)
            self.perform_close(self.close_event)

    def perform_close(self, event):
        """
        执行窗口关闭操作
        """
        from src.ui.core.signals import get_signal_bus_instance

        signal_bus = get_signal_bus_instance()

        signal_bus.emit_log("窗口正在关闭...")

        # 异步清理资源，避免阻塞主线程
        def cleanup_resources():
            # 清理自动化核心
            if self.auto_instance:
                try:
                    signal_bus.emit_log("正在停止自动化核心...")
                    self.auto_instance.set_should_stop(True)
                    # 不调用stop()方法，避免阻塞，直接断开设备
                    self.auto_instance.device_manager.disconnect_all()
                    signal_bus.emit_log("自动化核心资源已清理")
                except Exception as e:
                    signal_bus.emit_log(f"清理自动化核心时发生异常: {str(e)}")
                finally:
                    self.auto_instance = None

            # 确保应用程序完全退出
            signal_bus.emit_log("正在退出应用程序...")
            QApplication.quit()

        # 使用QTimer在主线程中异步执行清理
        QTimer.singleShot(0, cleanup_resources)

        # 接受关闭事件
        event.accept()


def main():
    """
    主函数
    """

    # 2. 初始化非阻塞组件
    settings_manager = AppSettingsManager()  # 应用设置管理器
    config_manager = TaskConfigManager()  # 任务配置管理器
    task_mapping = load_task_modules()  # 加载任务模块映射

    # 3. 启动GUI，Auto实例将在后台线程中初始化
    try:
        print("[DEBUG] 创建QApplication实例...")
        app = QApplication(sys.argv)
        app.setApplicationName("BD2-AUTO")
        print("[DEBUG] QApplication实例创建成功")

        # 初始化信号总线（必须在QApplication创建后）
        print("[DEBUG] 初始化信号总线...")
        from src.ui.core.signals import get_signal_bus_instance, init_signal_bus

        bus_instance = init_signal_bus()

        # 确保全局signal_bus变量已经初始化
        global_signal_bus = get_signal_bus_instance()
        print(f"[DEBUG] 信号总线初始化结果: {bus_instance}")
        print(f"[DEBUG] 全局signal_bus变量: {global_signal_bus}")
        print("[DEBUG] 信号总线初始化完成")

        print("[DEBUG] 创建MainWindow实例...")
        window = MainWindow(settings_manager=settings_manager, config_manager=config_manager, task_mapping=task_mapping)
        print("[DEBUG] MainWindow实例创建成功")

        print("[DEBUG] 调用window.show()...")
        window.show()
        print("[DEBUG] window.show()调用成功")

        # 在QApplication完全初始化后启动自动初始化线程
        print("[DEBUG] 启动自动初始化线程...")
        window.start_auto_init_thread()
        print("[DEBUG] 自动初始化线程启动成功")

        print("[DEBUG] 启动事件循环...")
        result = app.exec()
        print(f"[DEBUG] 事件循环退出，退出码: {result}")
        sys.exit(result)
    except Exception as e:
        print(f"[ERROR] GUI启动过程中发生异常: {type(e).__name__}: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
