import time
from auto_control.auto import Auto
from auto_control.logger import Logger


def get_email(auto: Auto):
    """领取邮箱"""
    logger = Logger("GetEmail")
    logger.info("开始领取邮箱")
    while True:
        pos = auto.add_check_element_exist_task("加载中").wait()
        if pos:
            logger.info("检测到加载中，等待加载完成")
            time.sleep(5)
            continue
        pos = auto.add_check_element_exist_task("邮箱").wait()
        if pos:
            logger.info("检测到邮箱，点击邮箱")
            auto.add_click_task(pos).wait()

        
        pos = auto.add_check_element_exist_task("邮箱未领数").wait()
        if pos:
            logger.info("检测到邮箱未领数已完，回到主界面")
            auto.add_key_task("esc").wait()
            return True
        else:
            logger.info("检测到邮箱未领数，点击全部领取")
            auto.add_text_click_task("全部领取").wait()
        
        pos = auto.add_check_element_exist_task("确认").wait()
        if pos:
            logger.info("检测到确认，点击确认")
            auto.add_click_task(pos).wait()

        


