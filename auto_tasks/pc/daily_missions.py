import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, click_back


def daily_missions(auto: Auto, timeout: int = 60):
    """每日任务"""
    try:
        logger = Logger("daily_missions")
        logger.info("开始领取每日任务")
        start_time = time.time()
        first = True
        second = True
        third = True


        while time.time() - start_time < timeout:
            # 检测是否在主界面
            if first:
                if back_to_main(auto):
                    if auto.text_click("任务"):
                        logger.info("点击任务")
                        first = False

            if not first and second:
                if auto.text_click("每日任务"):
                    logger.info("点击每日任务")
                    if auto.text_click("全部获得"):
                        logger.info("点击全部获得")
                        auto.sleep(4)
                        second = False

                if click_back(auto):
                    logger.info("点击返回")

                
            
            if not second and third:
                if auto.text_click("每周任务"):
                    logger.info("点击每周任务")
                    if auto.text_click("全部获得"):
                        logger.info("点击全部获得")
                        auto.sleep(4)
                    if click_back(auto):
                        logger.info("点击返回")
                        third = False
                    
                    result = back_to_main(auto)
                    if result:
                        logger.info("返回主界面成功")
                        return True
                    else:
                        logger.info("返回主界面失败")
            auto.sleep(0.5)  # 每次循环添加短暂延迟

        logger.info("领取公会奖励超时")
        return False
    except Exception as e:
        logger.error(f"领取公会奖励过程中出错: {e}")
        return False