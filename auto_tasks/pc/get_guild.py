import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main


def get_guild(auto: Auto, timeout: int = 60):
    """公会领取"""
    try:
        logger = Logger("get_guild")
        logger.info("开始领取公会奖励")
        start_time = time.time()
        first = True

        while time.time() - start_time < timeout:
            # 检测是否在主界面
            if first:
                if back_to_main(auto):
                    auto.template_click("get_guild/公会标识")
                    auto.sleep(4)
                    first = False

            if not first:
                if auto.check_element_exist("get_guild/公会商店"):
                    logger.info("检测到公会商店")
                    if auto.template_click("public/返回键1"):
                        logger.info("检测到返回键1，点击返回")
                        auto.sleep(2)
                        first = True
                        if back_to_main(auto):
                            logger.info("返回主界面成功")
                            return True
                else:
                    logger.info("未检测到公会商店")
                    first = True
                    
            auto.sleep(0.5)  # 每次循环添加短暂延迟

        logger.info("领取公会奖励超时")
        return False
    except Exception as e:
        logger.error(f"领取公会奖励过程中出错: {e}")
        return False