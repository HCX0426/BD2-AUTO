# 任务注册模块
from .pc import *  # 导入PC端所有任务函数


def register_all_tasks(task_manager):
    """注册所有自动化任务到任务管理器
    
    Args:
        task_manager: 任务管理器实例，需要支持register_task方法
    """
    # 注册PC端所有任务
    task_manager.register_task('login', login)
    task_manager.register_task('get_email', get_email)
    task_manager.register_task('get_restaurant', get_restaurant)
    task_manager.register_task('get_guild', get_guild)
    task_manager.register_task('sweep_daily', sweep_daily)
    task_manager.register_task('pass_rewards', pass_rewards)
    task_manager.register_task('pass_activity', pass_activity)
    task_manager.register_task('daily_missions', daily_missions)
    task_manager.register_task('intensive_decomposition', intensive_decomposition)
    task_manager.register_task('lucky_draw', lucky_draw)
    task_manager.register_task('get_pvp', get_pvp)
    task_manager.register_task('map_collection', map_collection)
