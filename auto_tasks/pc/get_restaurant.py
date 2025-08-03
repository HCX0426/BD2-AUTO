import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, click_back


def get_restaurant(auto: Auto, timeout: int = 600):
    """餐厅领取"""
    try:
        logger = Logger("get_restaurant")
        logger.info("开始领取餐厅奖励")
        start_time = time.time()
        first = True
        second = True
        thrid = True
        fourth = True

        while time.time() - start_time < timeout:
            if first:
                # 是否在主界面
                if back_to_main(auto):
                    if auto.template_click("get_restaurant/餐馆标识"):
                        logger.info("点击餐馆标识")
                        auto.sleep(1)
                        first = False
            
            if not first and second:
                if auto.text_click("结算"):
                    logger.info("点击结算")
                    auto.sleep(6)

                    if click_back(auto):
                        logger.info("领取成功")
                        first = True
                    else:
                        logger.info("领取失败")
                        second = False
                else:
                    logger.info("未检测到结算按钮")
                    first = True

            if not second and thrid:
                pos = auto.check_element_exist("get_restaurant/进入餐厅")
                if pos:
                    logger.info("点击进入餐厅")
                    auto.click(pos)
                    auto.sleep(12)
                    thrid = False

            if not thrid and fourth:
                if auto.text_click("常客"):
                    logger.info("点击常客")
                    auto.click(pos)
                    auto.sleep(1)
                    fourth = False

                    if back_to_main(auto):
                        logger.info("返回主界面成功")
                        return True
                    else:
                        logger.info("返回主界面失败")
                        return False
            
            auto.sleep(0.5)  # 每次循环添加短暂延迟
        
        logger.info("领取餐馆奖励超时")
        return False
    except Exception as e:
        logger.error(f"领取餐馆奖励过程中出错: {e}")
        return False