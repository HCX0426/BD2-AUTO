import io
import sys

from auto_control.auto import Auto
from auto_control.config import *
from auto_tasks.pc.daily_missions import daily_missions
from auto_tasks.pc.get_email import get_email
from auto_tasks.pc.get_guild import get_guild
from auto_tasks.pc.get_pvp import get_pvp
from auto_tasks.pc.get_restaurant import get_restaurant
from auto_tasks.pc.intensive_decomposition import intensive_decomposition
from auto_tasks.pc.login import login
from auto_tasks.pc.lucky_draw import lucky_draw
from auto_tasks.pc.map_collection import map_collection
from auto_tasks.pc.pass_activity import pass_activity
from auto_tasks.pc.pass_rewards import pass_rewards
from auto_tasks.pc.sweep_daily import sweep_daily

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# 移除原有的run()函数和主程序入口

# 保留任务函数导入和定义

# 添加一个新的执行函数供界面调用
def execute_selected_tasks(task_ids, task_manager):
    auto = Auto()
    try:
        # 检查设备添加是否成功
        if not auto.add_device():
            print(f"设备添加失败: {auto.last_error}")
            return False
        auto.start()

        # 登录游戏
        if not login(auto):
            print("登录失败")
            return False

        # 执行选中的任务
        for task_id in task_ids:
            task_info = task_manager.tasks.get(task_id)
            if not task_info:
                continue

            task_func = globals().get(task_info['function'])
            if not task_func:
                continue

            params = task_info['params'].copy()
            success = task_func(auto, **params)
            print(f"{task_info['name']} {'成功' if success else '失败'}")

        return True
    except Exception as e:
        print(f"运行失败: {e}")
        return False
    finally:
        generate_report(__file__)
        auto.stop()



# 保留原有的main入口但修改为调用新界面
if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication

    from main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
