import io
import sys

from auto_control import Auto
from auto_control.config import *
from auto_tasks.pc import *

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def console_execute(task_ids=None):
    """控制台模式执行任务，默认运行所有任务"""
    # 如果未指定任务ID，默认执行所有任务
    if task_ids is None or not task_ids:
        task_ids = ["all"]
    
    auto = Auto()
    try:
        if not auto.add_device():
            auto.logger.error(f"设备添加失败: {auto.last_error}")
            return False
        auto.start()

        # 登录游戏（确保只登录一次）
        if not login(auto):
            auto.logger.error("登录失败")
            return False

        # 定义所有任务映射
        task_mapping = {
            "get_guild": get_guild,
            "get_pvp": get_pvp,
            "get_restaurant": get_restaurant,
            "intensive_decomposition": intensive_decomposition,
            "lucky_draw": lucky_draw,
            "map_collection": map_collection,
            "pass_activity": pass_activity,
            "sweep_daily": sweep_daily,
            "pass_rewards": pass_rewards,
            "get_email": get_email,
            "daily": daily_missions,
        }
        
        # 处理"all"指令，执行所有任务（排除login避免重复登录）
        if "all" in task_ids:
            # 获取所有任务ID并排除login
            all_task_ids = [tid for tid in task_mapping.keys() if tid != "login"]
            tasks_to_run = [(tid, task_mapping[tid]) for tid in all_task_ids]
        else:
            # 筛选指定的有效任务
            tasks_to_run = [
                (tid, func) for tid, func in task_mapping.items()
                if tid in task_ids
            ]

        # 顺序执行任务
        for task_id, task_func in tasks_to_run:
            # 检查是否需要停止
            if auto.check_should_stop():
                auto.logger.info("任务被中断")
                break
                
            # 执行任务
            auto.logger.info(f"开始执行任务: {task_id}")
            try:
                success = task_func(auto)
                logger = auto.get_task_logger(task_id)
                logger.info(f"{task_id} 任务 {'成功' if success else '失败'}")
            except Exception as e:
                auto.logger.error(f"{task_id} 任务执行出错: {str(e)}", exc_info=True)
                # 遇到错误继续执行下一个任务

        return True
    except Exception as e:
        auto.logger.error(f"运行失败: {str(e)}", exc_info=True)
        return False
    finally:
        auto.stop()

if __name__ == "__main__":
    # 如果没有提供参数，默认执行所有任务
    task_ids = sys.argv[1:] if len(sys.argv) > 1 else None
    
    # 显示帮助信息的情况
    if task_ids and ("-h" in task_ids or "--help" in task_ids):
        print("使用方法:")
        print("  执行所有任务: python console_run.py")
        print("  执行指定任务: python console_run.py 任务1 任务2 ...")
        print("  查看帮助: python console_run.py -h 或 --help")
        print("  可用任务:", ", ".join([
            "login", "get_guild", "get_pvp", "get_restaurant",
            "intensive_decomposition", "lucky_draw", "map_collection",
            "pass_activity", "sweep_daily", "pass_rewards", "get_email", "daily"
        ]))
        sys.exit(0)
    
    console_execute(task_ids)
    