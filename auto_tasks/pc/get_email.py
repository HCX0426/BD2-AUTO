
import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main


def get_email(auto: Auto, timeout: int = 300):
    """领取邮箱"""
    try:
        logger = Logger("get_email")
        logger.info("开始领取邮件")
        start_time = time.time()  # 记录开始时间

        while time.time() - start_time < timeout:

            if time.time() - start_time > timeout:
                logger.error("任务总时长超时")
                return False

            # 检测是否在主界面
            result = back_to_main(auto)
            if result:
                auto.add_template_click_task("get_email/邮箱")
                auto.add_sleep_task(2)

            pos = auto.add_check_element_exist_task("get_email/邮件未领数").wait()
            if pos:
                logger.info("检测到邮件未领数已完，回到主界面")
                auto.add_text_click_task("全部领取").wait()
                result = auto.add_key_task("esc").wait()
                if result:
                    auto.add_sleep_task(2)
                    # 检测是否在主界面
                    pos = auto.add_check_element_exist_task("主界面")
                    if pos:
                        logger.info("检测到主界面，领取邮件完成")
                        return True
            else:
                logger.info("检测到邮件未领数，点击全部领取")
                auto.add_text_click_task("全部领取").wait()

            pos = auto.add_text_click_task("点击画面即可返回").wait()
            if pos:
                logger.info("检测到点击画面即可返回，进行点击")
                result = auto.add_click_task(pos).wait()
                if result:
                    auto.add_key_task("esc").wait()

                    result = back_to_main(auto)
                    if result:
                        return True
                else:
                    logger.error("点击画面即可返回失败")
                    return False

    except Exception as e:
        logger.error(f"领取邮件过程中出错: {e}")
        return False
