import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import (back_to_main,
                                      calculate_remaining_timeout, click_back)
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
    state = "init"  # 状态机: init -> entered -> checking -> claiming -> completed

    try:
        while True:
            if timeout > 0 and time.time() - start_time >= timeout:
                logger.error("任务执行超时")
                return False
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            # 初始状态：进入邮箱界面
            if state == "init":
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if back_to_main(auto, remaining_timeout):
                    if auto.template_click("get_email/邮箱", roi=roi_config.get_roi("email_box", "get_email")):
                        logger.info("entered: 尝试进入邮箱界面")
                        auto.sleep(2)
                        state = "entered"
                continue

            # 检查普通信箱
            if state == "entered":
                if not auto.text_click("普通邮箱", click=False, roi=roi_config.get_roi("regular_email", "get_email")):
                    logger.warning("未找到普通邮箱，next: init")
                    state = "init"
                    continue

                logger.info("检测到普通邮箱, next: checking")
                state = "checking"
                continue

            # 检查邮箱是否为空
            if state == "checking":
                if auto.check_element_exist("get_email/空邮箱标识", roi=roi_config.get_roi("empty_email", "get_email")):
                    logger.info("邮箱为空，无需领取, next: completed")
                    state = "completed"
                else:
                    logger.info("邮箱有内容可领取, next: claiming")
                    state = "claiming"
                continue

            # 领取邮件
            if state == "claiming":
                if auto.text_click("全部领取", roi=roi_config.get_roi("claim_all", "get_email")):
                    logger.info("成功点击全部领取, next: completed")
                    # 无论领取成功与否都尝试返回
                    state = "completed"
                else:
                    logger.warning("领取邮件失败, next: checking")
                    state = "checking"  # 重新尝试
                continue

            # 完成状态：返回主界面
            if state == "completed":
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if click_back(auto, remaining_timeout):
                    logger.info("从邮箱界面返回成功")
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if back_to_main(auto, remaining_timeout):
                    total_time = round(time.time() - start_time, 2)
                    minutes = int(total_time // 60)
                    seconds = round(total_time % 60, 2)
                    logger.info(f"邮件领取完成，用时：{minutes}分{seconds}秒")
                    return True

                logger.warning("返回主界面失败，next: completed")
                state = "completed"
                continue

            auto.sleep(0.5)

    except Exception as e:
        logger.error(f"领取邮件过程中出错: {e}")
        return False