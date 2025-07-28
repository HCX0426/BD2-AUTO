
from auto_control.auto import Auto
from auto_control.logger import Logger


def get_email(auto: Auto):
    """领取邮箱"""
    try:
        logger = Logger("GetEmail")
        logger.info("开始领取邮件")
        has_entered_email = False  # 状态标记

        while True:
            pos = auto.add_check_element_exist_task("加载中").wait()
            if pos:
                logger.info("检测到加载中，等待加载完成")
                auto.add_sleep_task(2)
                continue

            # 仅在未进入邮箱时检测邮箱入口
            if not has_entered_email:
                pos = auto.add_check_element_exist_task("邮箱").wait()
                if pos:
                    logger.info("检测到邮箱，点击邮箱")
                    auto.add_click_task(pos).wait()
                    has_entered_email = True  # 更新状态标记
                    continue  # 跳过后续检测直接进入下一轮循环

            pos = auto.add_check_element_exist_task("邮件未领数").wait()
            if pos:
                logger.info("检测到邮件未领数已完，回到主界面")
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
                    result = auto.add_key_task("esc").wait()
                    if result:
                        auto.add_sleep_task(2)
                        # 检测是否在主界面
                        pos = auto.add_check_element_exist_task("主界面")
                        if pos:
                            logger.info("检测到主界面，领取邮件完成")
                            return True
                else:
                    logger.error("点击画面即可返回失败")
                    return False
                
    except Exception as e:
        logger.error(f"领取邮件过程中出错: {e}")
        return False
