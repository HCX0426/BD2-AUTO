import inspect

from PyQt6.QtCore import QThread, pyqtSignal


class TaskWorker(QThread):
    """
    任务工作器，继承自QThread，实现任务执行逻辑
    使用信号总线与UI通信，不直接引用UI组件
    """

    # 定义信号
    task_finished = pyqtSignal()
    progress_updated = pyqtSignal(int)
    log_updated = pyqtSignal(str)

    def __init__(self, auto_instance, task_ids, config_manager, task_mapping):
        """
        初始化任务工作器

        Args:
            auto_instance: Auto核心控制实例
            task_ids: 要执行的任务ID列表
            config_manager: 配置管理器实例
            task_mapping: 任务映射字典
        """
        super().__init__()
        self.auto_instance = auto_instance
        self.task_ids = task_ids
        self.config_manager = config_manager
        self.task_mapping = task_mapping
        self.should_stop = False

    def run(self):
        """
        执行任务主逻辑，包含可中断点
        继承自QThread，在后台线程中执行
        """
        # 延迟导入signal_bus，确保它已经被初始化
        from src.ui.core.signals import signal_bus

        total_tasks = len(self.task_ids)
        success = True

        try:
            # 设备添加和启动操作
            self.log_updated.emit("开始添加设备...")
            signal_bus.emit_log("开始添加设备...")
            if not self.auto_instance.add_device():
                error_msg = f"设备添加失败: {getattr(self.auto_instance, 'last_error', '未知错误')}"
                self.log_updated.emit(error_msg)
                signal_bus.emit_log(error_msg)
                raise Exception(error_msg)
            self.log_updated.emit("设备添加成功，正在连接设备...")
            signal_bus.emit_log("设备添加成功，正在连接设备...")
            self.auto_instance.start()
            self.log_updated.emit("设备连接成功，准备执行任务")
            signal_bus.emit_log("设备连接成功，准备执行任务")

            for i, task_id in enumerate(self.task_ids):
                # 检查是否需要停止
                if self.check_stop():
                    log_msg = f"任务执行已被中断，已完成 {i}/{total_tasks} 个任务"
                    self.log_updated.emit(log_msg)
                    signal_bus.emit_log(log_msg)
                    success = False
                    break

                task_info = self.task_mapping.get(task_id)
                if not task_info:
                    log_msg = f"警告：任务 {task_id} 不存在，已跳过"
                    self.log_updated.emit(log_msg)
                    signal_bus.emit_log(log_msg)
                    continue

                # 更新进度
                progress = int((i / total_tasks) * 100)
                self.progress_updated.emit(progress)
                signal_bus.emit_progress(progress)
                log_msg = f"开始执行任务：{task_info['name']}"
                self.log_updated.emit(log_msg)
                signal_bus.emit_log(log_msg)

                # 获取任务参数
                task_params = self.config_manager.get_task_config(task_id) or {}

                # 执行任务
                task_func = task_info.get("function")
                if task_func:
                    try:
                        # 只传递函数定义中声明的参数（auto和有效参数）
                        sig = inspect.signature(task_func)
                        valid_params = {k: v for k, v in task_params.items() if k in sig.parameters}

                        # 如果任务函数支持check_stop参数，传递check_stop方法
                        if "check_stop" in sig.parameters:
                            valid_params["check_stop"] = self.check_stop

                        task_func(self.auto_instance, **valid_params)

                        # 任务函数执行完成后立即检查是否需要停止
                        if self.check_stop():
                            # 任务被中断，不应该显示为正常完成
                            log_msg = f"任务 {task_info['name']} 执行被中断"
                            self.log_updated.emit(log_msg)
                            signal_bus.emit_log(log_msg)
                            log_msg = f"任务执行已被中断，已完成 {i+1}/{total_tasks} 个任务"
                            self.log_updated.emit(log_msg)
                            signal_bus.emit_log(log_msg)
                            success = False
                            break
                        else:
                            # 任务正常完成
                            log_msg = f"任务 {task_info['name']} 执行完成"
                            self.log_updated.emit(log_msg)
                            signal_bus.emit_log(log_msg)
                    except Exception as e:
                        log_msg = f"任务 {task_info['name']} 执行出错: {str(e)}"
                        self.log_updated.emit(log_msg)
                        signal_bus.emit_log(log_msg)
                        if self.check_stop():
                            success = False
                            break
                else:
                    log_msg = f"警告：任务 {task_info['name']} 没有执行函数，已跳过"
                    self.log_updated.emit(log_msg)
                    signal_bus.emit_log(log_msg)

                # 再次检查是否需要停止，防止在任务执行过程中收到停止信号
                if self.check_stop():
                    log_msg = f"任务执行已被中断，已完成 {i+1}/{total_tasks} 个任务"
                    self.log_updated.emit(log_msg)
                    signal_bus.emit_log(log_msg)
                    success = False
                    break

            # 全部完成或中途停止，更新进度为100%
            self.progress_updated.emit(100)
            signal_bus.emit_progress(100)
            signal_bus.emit_task_finished()
            self.task_finished.emit()

            if success:
                log_msg = f"所有 {total_tasks} 个任务执行完成"
                self.log_updated.emit(log_msg)
                signal_bus.emit_log(log_msg)

        except Exception as e:
            log_msg = f"任务执行发生未捕获异常: {str(e)}"
            self.log_updated.emit(log_msg)
            signal_bus.emit_log(log_msg)
            # 确保发送任务完成信号
            signal_bus.emit_task_finished()
            self.task_finished.emit()
        finally:
            # 清理资源，只设置停止标志，不调用stop()方法避免阻塞
            log_msg = "任务执行完成，正在清理资源..."
            self.log_updated.emit(log_msg)
            signal_bus.emit_log(log_msg)
            # 只设置停止标志，不调用stop()方法，避免阻塞
            self.auto_instance.set_should_stop(True)
            # 不调用self.auto_instance.stop()，避免阻塞，由主窗口在关闭时统一处理资源清理
            # 添加资源清理完成的提示
            log_msg = "资源清理完成"
            self.log_updated.emit(log_msg)
            signal_bus.emit_log(log_msg)

    def check_stop(self):
        """
        检查是否需要停止任务

        Returns:
            bool: 是否需要停止
        """
        return self.should_stop or self.auto_instance.check_should_stop()

    def stop(self):
        """
        请求任务停止
        """
        # 延迟导入signal_bus，确保它已经被初始化
        from src.ui.core.signals import signal_bus

        self.should_stop = True
        self.auto_instance.set_should_stop(True)
        log_msg = "已发送任务停止请求"
        self.log_updated.emit(log_msg)
        signal_bus.emit_log(log_msg)
