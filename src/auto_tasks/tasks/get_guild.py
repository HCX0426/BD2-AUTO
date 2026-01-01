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
    logger = auto.get_task_logger("get_guild")
    logger.info("开始领取公会奖励")

    start_time = time.time()
    state = "init"  # 状态机: init -> entered -> checking -> completed

    try:
        while True:
            if timeout > 0 and time.time() - start_time >= timeout:
                logger.error("任务执行超时")
                return False
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            # 初始状态：进入公会界面
            if state == "init":
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if back_to_main(auto, remaining_timeout):
                    if auto.template_click("get_guild/公会标识", roi=roi_config.get_roi("guild_icon", "get_guild")):
                        logger.info("成功进入公会界面")
                        auto.sleep(4)
                        state = "entered"
                continue

            # 检查公会商店
            if state == "entered":
                if auto.check_element_exist("get_guild/公会商店", roi=roi_config.get_roi("guild_shop", "get_guild")):
                    logger.info("检测到公会商店")
                    state = "checking"
                else:
                    logger.warning("未检测到公会商店，重新尝试")
                    state = "init"
                continue

            # 返回处理
            if state == "checking":
                if auto.template_click("public/返回键1", roi=roi_config.get_roi("back_button")):
                    logger.info("成功点击返回键")
                    auto.sleep(2)
                    state = "completed"
                else:
                    logger.warning("返回失败，重新尝试")
                    state = "entered"
                continue

            # 完成状态：返回主界面
            if state == "completed":
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if back_to_main(auto, remaining_timeout):
                    total_time = round(time.time() - start_time, 2)
                    minutes = int(total_time // 60)
                    seconds = round(total_time % 60, 2)
                    logger.info(f"公会奖励领取完成，用时：{minutes}分{seconds}秒")
                    return True
                logger.warning("返回主界面失败，重试中...")
                state = "init"
                continue

            auto.sleep(0.5)

    except Exception as e:
        logger.error(f"领取公会奖励过程中出错: {e}")
        return False