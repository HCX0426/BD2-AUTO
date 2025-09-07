import io
import sys

from auto_control import Auto
from auto_control.config import *
from auto_tasks.pc import *

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def console_execute(task_ids=None):
    """控制台模式执行任务，默认运行所有任务"""
    # 如果未指定任务ID，默认执行所有任务
    # if task_ids is None or not task_ids:
    #     task_ids = ["all"]
    
    auto = Auto()
    try:
        if not auto.add_device():
            auto.logger.error(f"设备添加失败: {auto.last_error}")
            return False
        auto.start()

        # auto.swipe((410, 410), (410, 180),duration=6, steps=6,is_base_coord = True)
        pos = auto.check_element_exist("public/主界面")
        if pos:
           auto.click(pos)
           print(pos)
        else:
            auto.logger.error("主界面元素未找到")
            return False



        return True
    except Exception as e:
        auto.logger.error(f"运行失败: {str(e)}", exc_info=True)
        return False
    # finally:
        # auto.stop()

# if __name__ == "__main__":
#     # 如果没有提供参数，默认执行所有任务
#     task_ids = sys.argv[1:] if len(sys.argv) > 1 else None
    
    # 显示帮助信息的情况
    # if task_ids and ("-h" in task_ids or "--help" in task_ids):
    #     print("使用方法:")
    #     print("  执行所有任务: python console_run.py")
    #     print("  执行指定任务: python console_run.py 任务1 任务2 ...")
    #     print("  查看帮助: python console_run.py -h 或 --help")
    #     print("  可用任务:", ", ".join([
    #         "login", "get_guild", "get_pvp", "get_restaurant",
    #         "intensive_decomposition", "lucky_draw", "map_collection",
    #         "pass_activity", "sweep_daily", "pass_rewards", "get_email", "daily"
    #     ]))
        # sys.exit(0)
    
console_execute()
    