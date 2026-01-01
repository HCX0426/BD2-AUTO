"""每日任务领取模块

包含每日任务和每周任务的奖励领取功能
"""
import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import back_to_main, click_back, calculate_remaining_timeout
from src.auto_tasks.utils.roi_config import roi_config


def daily_missions(auto: Auto, timeout: int = 300) -> bool:
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
    state = "init"  # 状态机: init -> main_checked -> tasks_entered -> daily_received -> weekly_received -> completed

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

            # 2. 进入任务界面
            if state == "main_checked":
                logger.info("进入任务界面")
                if auto.text_click(
                    "任务",
                    roi=roi_config.get_roi("daily_missions_text", "daily_missions"),
                    verify={"type": "text", "target": "每日任务", "timeout": 5, "roi": roi_config.get_roi("daily_tasks", "daily_missions")},
                    retry=2,
                    click_time=2,
                    delay=1
                ):
                    state = "tasks_entered"
                continue

            # 3. 领取每日任务奖励
            if state == "tasks_entered":
                logger.info("领取每日任务奖励")
                pos = auto.text_click(
                    "全部获得", 
                    click=False, 
                    roi=roi_config.get_roi("receive", "daily_missions"),
                    verify={"type": "exist", "target": "每日任务", "timeout": 5, "roi": roi_config.get_roi("daily_tasks", "daily_missions")},
                    retry=1
                )
                if pos:
                    logger.info("点击全部获得按钮")
                    for _ in range(2):
                        auto.click(pos, click_time=2, coord_type="LOGICAL")
                        auto.sleep(1)
                    
                    click_back(auto, remaining_timeout)
                    logger.info("每日任务奖励领取成功")
                else:
                    logger.warning("无每日任务奖励可以领取")
                state = "daily_received"
                continue

            # 4. 领取每周任务奖励
            if state == "daily_received":
                logger.info("领取每周任务奖励")
                if auto.text_click(
                    "每周任务", 
                    click_time=2, 
                    roi=roi_config.get_roi("weekly_missions_text", "daily_missions"),
                    verify={"type": "text", "target": "每周任务", "timeout": 5},
                    retry=1
                ):
                    logger.info("进入每周任务界面")
                    if auto.text_click(
                        "全部获得", 
                        click_time=2, 
                        roi=roi_config.get_roi("receive", "daily_missions"),
                        verify={"type": "text", "target": "每周任务", "timeout": 5},
                        retry=1
                    ):
                        logger.info("成功领取每周任务奖励")
                        auto.sleep(2)
                    else:
                        logger.warning("无每周任务奖励可以领取")
                    
                    click_back(auto, remaining_timeout)
                else:
                    logger.warning("无法进入每周任务界面")
                state = "weekly_received"
                continue

            # 5. 返回主界面
            if state == "weekly_received":
                logger.info("返回主界面")
                auto.key_press("esc")
                auto.sleep(1)
                if back_to_main(auto, remaining_timeout):
                    total_time = round(time.time() - start_time, 2)
                    minutes = int(total_time // 60)
                    seconds = round(total_time % 60, 2)
                    logger.info(f"每日任务领取完成，用时：{minutes}分{seconds}秒")
                    return True
                else:
                    logger.warning("返回主界面失败")
                    return False

    except Exception as e:
        logger.error(f"领取每日任务过程中出错: {e}")
        return False