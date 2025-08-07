import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, click_back


def pass_rewards(auto: Auto, timeout: int = 600):
    """通行证奖励"""
    try:
        logger = auto.get_task_logger("pass_rewards")
        logger.info("开始领取奖励")
        start_time = time.time()
        first = True
        second = True
        third = True
        fourth = True
        fifth = True

        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            # 检测是否在主界面
            if first:
                if back_to_main(auto):
                    pos = auto.check_element_exist("pass_rewards/通行证标识")
                    if auto.click(pos):
                        logger.info("点击通行证")
                        auto.sleep(2)
                        first = False
            if not first and second:
                if auto.click((420,330),time=2):
                    if auto.click((1590,680)):
                        if auto.text_click("全部获得"):
                            logger.info("点击全部获得")
                            auto.sleep(2)

                            if click_back(auto):
                                logger.info("点击返回")
                                second = False
                            else:
                                logger.info("未点击到返回")
                                second = False
            if not second and third:
                if auto.click((420,430),time=2):
                    if auto.click((1590,680)):
                        if auto.text_click("全部获得"):
                            logger.info("点击全部获得")
                            auto.sleep(2)

                            if click_back(auto):
                                logger.info("点击返回")
                                third = False
                            else:
                                logger.info("未点击到返回")
                                third = False
            
            if not third and fourth:
                if auto.click((420,530),time=2):
                    if auto.click((1590,680)):
                        if auto.text_click("全部获得"):
                            logger.info("点击全部获得")
                            auto.sleep(2)

                            if click_back(auto):
                                logger.info("点击返回")
                                fourth = False
                            else:
                                logger.info("未点击到返回")
                                fourth = False
            if not fourth and fifth:
                if auto.click((420,630),time=2):
                    if auto.click((1590,680)):
                        if auto.text_click("全部获得"):
                            logger.info("点击全部获得")
                            auto.sleep(2)

                            if click_back(auto):
                                logger.info("点击返回")
                                fifth = False
                            else:
                                logger.info("未点击到返回")
                                fifth = False
                            
                            if back_to_main(auto):
                                logger.info("返回主界面")
                                return True
                            else:
                                logger.info("未返回主界面")
                                return False
            
            auto.sleep(0.5)  # 每次循环添加短暂延迟

        logger.info("扫荡活动超时")
        return False
    except Exception as e:
        logger.error(f"扫荡活动过程中出错: {e}")
        return False