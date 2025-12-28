import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.pc.public import back_to_main, click_back
from src.auto_tasks.utils.roi_config import roi_config


def daily_missions(auto: Auto, timeout: int = 60) -> bool:
    """每日任务领取

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)

    Returns:
        bool: 任务是否成功完成
    """
    logger = auto.get_task_logger("daily_missions")
    logger.info("开始领取每日任务")

    start_time = time.time()
    state = "init"  # init -> main_checked -> daily_received -> weekly_received -> completed

    try:
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            # 初始状态：检查主界面
            if state == "init":
                if back_to_main(auto):
                    if pos := auto.text_click(
                        "任务", click=False, roi=roi_config.get_roi("daily_missions_text", "daily_missions")
                    ):
                        logger.info(f"进入任务界面, next: main_checked")
                        auto.click(pos, click_time=2, coord_type="LOGICAL")
                        auto.sleep(2)
                        state = "main_checked"
                continue

            # 领取每日任务奖励
            if state == "main_checked":
                if not auto.text_click("每日任务", click=False, roi=roi_config.get_roi("daily_tasks", "daily_missions")):
                    logger.info("未在任务界面，返回主界面重试")
                    state = "init"
                    continue

                if pos := auto.text_click("全部获得", click=False, roi=roi_config.get_roi("receive", "daily_missions")):
                    logger.info("领取每日任务奖励")
                    auto.click(pos, click_time=2, coord_type="LOGICAL")
                    auto.sleep(1)
                    auto.click(pos, click_time=2, coord_type="LOGICAL")
                    auto.sleep(1)
                    if click_back(auto):
                        logger.info("每日任务奖励领取成功")
                    else:
                        logger.info("无每日任务奖励")
                else:
                    logger.warning("无奖励可以领取")
                
                logger.info("领取每日任务奖励完成, next: daily_received")
                state = "daily_received"
                continue

            # 领取每周任务奖励
            if state == "daily_received":
                if click_back(auto):
                    logger.info("领取成功")
                if auto.text_click("每周任务", click_time=2, roi=roi_config.get_roi("weekly_missions_text", "daily_missions")):
                    logger.info("进入每周任务界面")
                    if auto.text_click("全部获得", click_time=2, roi=roi_config.get_roi("receive", "daily_missions")):
                        logger.info("成功领取每周任务奖励")
                        auto.sleep(2)

                    if click_back(auto):
                        logger.warning("领取成功")
                    else:
                        logger.info("无奖励可领取")
                    
                    logger.info("领取每周任务奖励完成, next: weekly_received")
                    state = "weekly_received"
                continue

            # 返回主界面
            if state == "weekly_received":
                auto.key_press("esc")
                auto.sleep(1)
                if back_to_main(auto):
                    logger.info("成功返回主界面")
                    return True
                logger.warning("返回主界面失败，重试中...")
                continue

            auto.sleep(0.5)

        logger.warning("领取每日任务超时")
        return False

    except Exception as e:
        logger.error(f"领取每日任务过程中出错: {e}")
        return False
