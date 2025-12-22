import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.pc.public import back_to_main, click_back


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
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            # 初始状态：进入邮箱界面
            if state == "init":
                if back_to_main(auto):
                    if auto.template_click("get_email/邮箱"):
                        logger.info("成功进入邮箱界面")
                        auto.sleep(2)
                        state = "entered"
                continue

            # 检查普通信箱
            if state == "entered":
                if not auto.text_click("普通邮箱", click=False):
                    logger.warning("未找到普通邮箱，重新尝试")
                    state = "init"
                    continue

                logger.info("检测到普通邮箱")
                state = "checking"
                continue

            # 检查邮箱是否为空
            if state == "checking":
                if auto.check_element_exist("get_email/空邮箱标识"):
                    logger.info("邮箱为空，无需领取")
                    state = "completed"
                else:
                    logger.info("邮箱有内容可领取")
                    state = "claiming"
                continue

            # 领取邮件
            if state == "claiming":
                if auto.text_click("全部领取"):
                    logger.info("成功点击全部领取")
                    # 无论领取成功与否都尝试返回
                    state = "completed"
                else:
                    logger.warning("领取邮件失败")
                    state = "checking"  # 重新尝试
                continue

            # 完成状态：返回主界面
            if state == "completed":
                if click_back(auto):
                    logger.info("从邮箱界面返回成功")
                if back_to_main(auto):
                    logger.info("成功返回主界面")
                    return True

                logger.warning("返回主界面失败，重试中...")
                state = "init"  # 如果返回失败，重新开始流程
                continue

            auto.sleep(0.5)

        logger.error("领取邮件超时")
        return False

    except Exception as e:
        logger.error(f"领取邮件过程中出错: {e}")
        return False
