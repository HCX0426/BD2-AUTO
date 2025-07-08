import time
from typing import Optional

from auto_control.device_base import BaseDevice
from bd2_auto import BD2Auto


class Login:
    def __init__(self, bd2auto: BD2Auto):
        self.bd2auto = bd2auto
        self.task_id = None
        self.executor = bd2auto.task_executor

    def run(self, *args, **kwargs):
        """执行登录流程"""
        print("开始执行登录流程")
        self.task_id = self.executor.add_task(
            self._execute_login_flow,
            *args,
            priority=kwargs.get('priority', 5),
            **kwargs
        )
        return self.task_id

    def _execute_login_flow(self, *args, **kwargs):
        """登录流程主函数"""
        try:
            # 验证设备连接
            device = self.bd2auto.device_manager.get_active_device()
            if not device or not device.connected:
                print("错误：没有可用的已连接设备")
                return False

            # 步骤1: 点击登录按钮
            if not self._click_login_button(kwargs.get('login_pos', (0.5, 0.8))):
                return False

            # 步骤2: 输入账号
            if not self._input_username(kwargs.get('username')):
                return False

            # 步骤3: 输入密码
            if not self._input_password(kwargs.get('password')):
                return False

            # 步骤4: 点击确认
            if not self._click_confirm(kwargs.get('confirm_pos', (0.5, 0.9))):
                return False

            return True
        except Exception as e:
            print(f"登录流程执行失败: {str(e)}")
            return False

    def _click_login_button(self, pos: tuple) -> bool:
        """点击登录按钮"""
        try:
            # 使用bd2auto的统一点击方法
            return self.bd2auto.add_click_task(pos, is_relative=True)
        except Exception as e:
            print(f"点击登录按钮失败: {str(e)}")
            return False

    def _input_username(self, username: str) -> bool:
        """输入用户名"""
        if not username:
            return False

        try:
            # 使用bd2auto的统一输入方法
            device = self.bd2auto.device_manager.get_active_device()
            if not device.set_foreground():
                return False
            return device.text_input(username)
        except Exception as e:
            print(f"输入用户名失败: {str(e)}")
            return False

    def _input_password(self, password: str) -> bool:
        """输入密码"""
        if not password:
            return False

        try:
            # 使用bd2auto的统一输入方法
            device = self.bd2auto.device_manager.get_active_device()
            if not device.set_foreground():
                return False
            return device.text_input(password)
        except Exception as e:
            print(f"输入密码失败: {str(e)}")
            return False

    def _click_confirm(self, pos: tuple) -> bool:
        """点击确认按钮"""
        try:
            # 使用bd2auto的统一点击方法
            return self.bd2auto.add_click_task(pos, is_relative=True)
        except Exception as e:
            print(f"点击确认按钮失败: {str(e)}")
            return False

    def _task_function(self, *args, **kwargs):
        """任务实际执行的函数"""
        try:
            # 模拟任务执行过程
            for i in range(5):
                print(f"示例任务执行中... {i+1}/5")
                time.sleep(1)
            print("示例任务执行完成")
            return True
        except Exception as e:
            print(f"示例任务执行失败: {str(e)}")
            return False
