import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, click_back


def get_email(auto: Auto, timeout: int = 300):
    """领取邮箱"""
    try:
        logger = Logger("get_email")
        logger.info("开始领取邮件")
        start_time = time.time()
        first = True

        while time.time() - start_time < timeout:
            if first:
                # 检测是否在主界面
                if back_to_main(auto):
                    auto.template_click("get_email/邮箱")
                    auto.sleep(2)
                    first = False
            if not first:
                if auto.text_click("普通信箱",click=False):
                    logger.info("检测到普通信箱")

                    if not auto.check_element_exist("get_email/空邮箱标识"):
                        logger.info("未检测到空邮箱标识")
                        if auto.text_click("全部领取"):
                            logger.info("点击全部领取")
                            
                            if click_back(auto):
                                logger.info("点击画面即可返回")
                                if back_to_main(auto):
                                    logger.info("返回主界面成功")
                                    return True
                            else:
                                if back_to_main(auto):
                                    logger.info("返回主界面成功")
                                    return True
                    else:
                        logger.info("检测到空邮箱标识，尝试返回")
                        if back_to_main(auto):
                            logger.info("返回主界面成功")
                            return True
                
                else:
                    logger.info("未检测到普通信箱")
                    first = True

            auto.sleep(0.5)  # 每次循环添加短暂延迟
            
        logger.error("领取邮件超时")
        return False
    except Exception as e:
        logger.error(f"领取邮件过程中出错: {e}")
        return False