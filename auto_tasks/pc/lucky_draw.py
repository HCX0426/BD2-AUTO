import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main


def lucky_draw(auto: Auto, timeout: int = 60):
    """抽抽乐"""
    try:
        logger = Logger("lucky_draw")
        logger.info("开始抽抽乐")
        start_time = time.time()
        first = True

        while time.time() - start_time < timeout:
            # 检测是否在主界面
            if first:
                if back_to_main(auto):
                    auto.text_click("抽抽乐")
                    auto.sleep(4)
                    first = False

            if not first:
                if auto.text_click("免费"):
                    logger.info("检测到免费")
                    auto.sleep(2)
                    if auto.text_click("购买"):
                        logger.info("点击购买")
                        auto.sleep(2)
                        
                else:
                    logger.info("未检测到抽抽乐")
                    first = True
                    
            auto.sleep(0.5)  # 每次循环添加短暂延迟

        logger.info("领取公会奖励超时")
        return False
    except Exception as e:
        logger.error(f"领取公会奖励过程中出错: {e}")
        return False