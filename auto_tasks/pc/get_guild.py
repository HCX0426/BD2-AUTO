
import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main


def get_guild(auto: Auto, timeout: int = 60):
    """公会领取"""
    try:
        logger = Logger("get_guild")
        logger.info("开始领取公会奖励")
        start_time = time.time()  # 记录开始时间
        flag = False

        while time.time() - start_time < timeout:
            if time.time() - start_time > timeout:
                logger.error("任务总时长超时")
                return False
            
            if flag:
                result = back_to_main(auto)
                if result:
                    logger.info("返回主界面成功")
                    return True
                else:
                    logger.error("返回主界面失败")
                    return False

            # 检测是否在主界面
            if not flag:
                result = back_to_main(auto)
                if result:
                    auto.add_template_click_task("get_guild/公会标识").wait()
                    auto.add_sleep_task(2).wait()
            
            pos = auto.add_check_element_exist_task("get_guild/公会商店")
            if pos:
                logger.info("检测到公会商店")
                pos = auto.add_template_click_task("public/返回键1").wait()
                if pos:
                    logger.info("检测到返回键1，点击返回")
                    auto.add_sleep_task(2).wait()
                    flag = True
                    result = back_to_main(auto)
                    if result:
                        logger.info("返回主界面成功")
                        return True
    except Exception as e:
        logger.error(f"领取邮件过程中出错: {e}")
        return False
