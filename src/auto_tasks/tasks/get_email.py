"""邮件领取模块

包含邮件的检查和奖励领取功能
"""

import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import back_to_main, calculate_remaining_timeout, click_back
from src.auto_tasks.utils.roi_config import roi_config


def get_email(auto: Auto, timeout: int = 300) -> bool:
    """邮件领取

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)

    Returns:
        bool: 邮件是否成功领取
    """
    logger = auto.get_task_logger("get_email")
    logger.info("开始领取邮件")

    start_time = time.time()
    state = "init"  # 状态机: init -> main_checked -> email_entered -> emails_checked -> emails_received -> completed

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

            # 2. 进入邮箱界面
            if state == "main_checked":
                logger.info("尝试进入邮箱界面")
                if auto.template_click(
                    "get_email/邮箱",
                    roi=roi_config.get_roi("email_box", "get_email"),
                    verify={
                        "type": "text",
                        "target": "普通邮箱",
                        "roi": roi_config.get_roi("regular_email", "get_email"),
                    },
                ):
                    state = "email_entered"
                continue

            # 3. 检查邮箱是否为空
            if state == "email_entered":
                logger.info("检查邮箱是否为空")
                if auto.wait_element("get_email/空邮箱标识", roi=roi_config.get_roi("empty_email", "get_email"), wait_timeout=0):
                    logger.info("邮箱为空，无需领取")
                    state = "emails_received"
                else:
                    state = "emails_checked"
                continue

            # 4. 领取邮件
            if state == "emails_checked":
                logger.info("邮箱有内容，尝试领取")
                auto.text_click(
                    "全部领取",
                    roi=roi_config.get_roi("claim_all", "get_email"),
                    verify={
                        "type": "exist",
                        "target": "get_email/空邮箱标识",
                        "roi": roi_config.get_roi("empty_email", "get_email"),
                    },
                )
                state = "emails_received"
                continue

            # 5. 返回主界面
            if state == "emails_received":
                logger.info("从邮箱界面返回")
                click_back(auto, remaining_timeout)
                logger.info("从邮箱界面返回成功")
                state = "completed"
                continue

            # 6. 返回主界面，完成任务
            if state == "completed":
                if back_to_main(auto, remaining_timeout):
                    total_time = round(time.time() - start_time, 2)
                    minutes = int(total_time // 60)
                    seconds = round(total_time % 60, 2)
                    logger.info(f"邮件领取完成，用时：{minutes}分{seconds}秒")
                    return True
                else:
                    logger.error("返回主界面失败")
                    return False

    except Exception as e:
        logger.error(f"领取邮件过程中出错: {e}")
        return False
