import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, click_back


def get_restaurant(auto: Auto, timeout: int = 60):
    """餐厅领取"""
    try:
        logger = Logger("get_restaurant")
        logger.info("开始领取餐厅奖励")
        start_time = time.time()
        first = True

        while time.time() - start_time < timeout:
            if first:
                # 是否在主界面
                if back_to_main(auto):
                    if auto.template_click("get_restaurant/餐馆标识"):
                        logger.info("点击餐馆标识")
                        auto.sleep(1)
                        first = False
            
            if not first:
                if auto.text_click("结算"):
                    logger.info("点击结算")
                    auto.sleep(2)

                    if click_back(auto):
                        logger.info("领取成功")
                        return True
                    else:
                        pos = auto.check_element_exist("get_restaurant/结算X")
                        if pos:
                            auto.click(pos)
                            logger.info("点击结算X成功")
                            auto.sleep(1)
                            if back_to_main(auto):
                                logger.info("返回主界面成功")
                                return True
                else:
                    logger.info("未检测到结算按钮")
                    first = True

                if click_back(auto):
                    logger.info("点击画面即可返回")
                    return True
                
            auto.sleep(0.5)  # 每次循环添加短暂延迟
        
        logger.info("领取餐馆奖励超时")
        return False
    except Exception as e:
        logger.error(f"领取餐馆奖励过程中出错: {e}")
        return False