"""登录模块

包含游戏登录和返回主界面的功能
"""
import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import back_to_main, back_to_map, calculate_remaining_timeout
from src.auto_tasks.utils.roi_config import roi_config


def login(auto: Auto, timeout: int = 300) -> bool:
    """登录

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)

    Returns:
        bool: 是否成功登录并返回主界面
    """
    logger = auto.get_task_logger("Login")
    logger.info("开始登录流程")

    # 记录任务开始时间，用于计算剩余超时
    start_time = time.time()

    # 使用任务链替代状态机
    chain = auto.chain()
    chain.set_total_timeout(timeout)

    # 1. 处理确认按钮
    chain.then().text_click(
        "确认", 
        roi=roi_config.get_roi("login_confirm_button", "login"),
        verify={"type": "exist", "target": "login/开始游戏", "roi": roi_config.get_roi("login_start_button", "login")}
    )

    # 2. 点击开始游戏按钮，验证进入游戏
    chain.then().template_click(
        "login/开始游戏",
        roi=roi_config.get_roi("login_start_button", "login"),
        verify={
            "type": "exist",
            "target": "main_ui/主界面"
        }
    )

    # 3. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 4. 处理弹窗，返回地图
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_map(auto, remaining_timeout), timeout=remaining_timeout)

    # 5. 返回主界面，完成登录
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 执行任务链
    result = chain.execute()

    if result.success:
        total_time = round(result.elapsed_time, 2)
        minutes = int(total_time // 60)
        seconds = round(total_time % 60, 2)
        logger.info(f"登录完成，用时：{minutes}分{seconds}秒")
        return True
    else:
        logger.error(f"登录失败: {result.error_msg}")
        return False