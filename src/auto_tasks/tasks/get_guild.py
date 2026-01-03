"""公会奖励领取模块

包含公会奖励的领取功能
"""

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

    start_time = time.time()
    state = "init"  # 状态机: init -> main_checked -> guild_entered -> completed

    try:
        while True:
            if timeout > 0 and time.time() - start_time >= timeout:
                logger.error("任务执行超时")
                return False
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            remaining_timeout = calculate_remaining_timeout(timeout, start_time)

            # 1. 返回主界面
            if state == "init":
                logger.info("返回主界面")
                if back_to_main(auto, remaining_timeout):
                    state = "main_checked"
                continue

            # 2. 点击公会标识，进入公会界面
            if state == "main_checked":
                logger.info("点击公会标识，进入公会界面")
                if auto.template_click(
                    "get_guild/公会标识",
                    roi=roi_config.get_roi("guild_icon", "get_guild"),
                    verify={
                        "type": "exist",
                        "target": "get_guild/公会商店",
                        "timeout": 10,
                        "roi": roi_config.get_roi("guild_shop", "get_guild"),
                    },
                    retry=2,
                    delay=1,
                ):
                    auto.sleep(2)
                    state = "guild_entered"
                continue

            # 3. 点击返回键
            if state == "guild_entered":
                logger.info("点击返回键")
                if auto.template_click(
                    "public/返回键1",
                    roi=roi_config.get_roi("back_button"),
                    verify={"type": "exist", "target": "public/主界面", "timeout": 10},
                    retry=2,
                    delay=1,
                ):
                    auto.sleep(2)
                    state = "completed"
                continue

            # 4. 返回主界面，完成任务
            if state == "completed":
                logger.info("返回主界面，完成任务")
                if back_to_main(auto, 10):
                    total_time = round(time.time() - start_time, 2)
                    minutes = int(total_time // 60)
                    seconds = round(total_time % 60, 2)
                    logger.info(f"公会奖励领取完成，用时：{minutes}分{seconds}秒")
                    return True
                else:
                    logger.warning("返回主界面失败，但任务已完成")
                    return True

    except Exception as e:
        logger.error(f"领取公会奖励过程中出错: {e}")
        return False
