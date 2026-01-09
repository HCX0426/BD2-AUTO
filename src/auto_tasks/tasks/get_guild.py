import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import back_to_main, calculate_remaining_timeout
from src.auto_tasks.utils.roi_config import roi_config


def get_guild(auto: Auto, timeout: int = 300) -> bool:
    """公会奖励领取

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)

    Returns:
        bool: 是否成功完成领取
    """
    logger = auto.logger.create_task_logger("get_guild")
    logger.info("开始领取公会奖励")

    # 记录任务开始时间，用于计算剩余超时
    start_time = time.time()

    # 使用任务链替代状态机
    chain = auto.chain()
    chain.set_total_timeout(timeout)

    # 1. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 2. 点击公会标识，进入公会界面
    chain.then().template_click("get_guild/公会标识", roi=roi_config.get_roi("guild_icon", "get_guild"))

    # 3. 点击返回键
    chain.then()\
    .with_pre_verify(verify_type="wait_element", template="get_guild/公会商店", roi=roi_config.get_roi("guild_shop", "get_guild"))\
    .template_click("public/返回键1", roi=roi_config.get_roi("back_button"))

    # 6. 最终返回主界面确认
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, min(10, remaining_timeout)), timeout=min(10, remaining_timeout))

    # 执行任务链
    result = chain.execute()

    if result.success:
        total_time = round(result.elapsed_time, 2)
        minutes = int(total_time // 60)
        seconds = round(total_time % 60, 2)
        logger.info(f"公会奖励领取完成，用时：{minutes}分{seconds}秒")
        return True
    else:
        logger.error(f"公会奖励领取失败: {result.error_msg}")
        return False
