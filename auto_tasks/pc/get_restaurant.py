
import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, click_back


def get_restaurant(auto: Auto, timeout: int = 60):
    """餐厅领取"""
    try:
        logger = Logger("get_restaurant")
        logger.info("开始领取餐厅奖励")
        start_time = time.time()  # 记录开始时间
        first = False

        while time.time() - start_time < timeout:
            if time.time() - start_time > timeout:
                logger.error("任务总时长超时")
                return False
            
            if not first:
                # 是否在主界面
                result = back_to_main(auto)
                if result:
                    pos = auto.add_template_click_task("get_restaurant/餐馆标识").wait()
                    if pos:
                        logger.info("点击餐馆标识")
                        auto.add_sleep_task(1).wait()
                        first = True

            pos = auto.add_text_click_task("结算").wait()
            if pos:
                logger.info("点击结算")
                auto.add_sleep_task(4).wait()

                pos = click_back(auto)
                if not pos:
                    pos = auto.add_template_click_task("get_restaurant/结算X").wait()
                    if pos:
                        logger.info("点击结算X成功")
                        auto.add_sleep_task(1).wait()
                        result = back_to_main(auto)
                        if result:
                            logger.info("返回主界面成功")
                            return True

                else:
                    logger.info("领取成功")
                    return True


            pos = click_back(auto)
            if pos:
                logger.info("点击画面即可返回")
                return True
        
    except Exception as e:
        logger.error(f"领取餐馆奖励过程中出错: {e}")
        return False
