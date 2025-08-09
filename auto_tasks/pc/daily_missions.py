import time

from auto_control.auto import Auto
from auto_tasks.pc.public import back_to_main, click_back


def daily_missions(auto: Auto, timeout: int = 60):
    """每日任务"""
    try:
        logger = auto.get_task_logger("daily_missions")
        logger.info("开始领取每日任务")
        start_time = time.time()
        first = True
        second = True
        third = True


        while time.time() - start_time < timeout:

            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            # 检测是否在主界面
            if first:
                if back_to_main(auto):
                    if pos := auto.text_click("任务",click=False):
                        logger.info(f"点击任务,pos:{pos}")
                        auto.click(pos)
                        first = False

            if not first and second:
                if auto.text_click("全部获得"):
                    logger.info("点击全部获得")
                    auto.sleep(4)
                    second = False
                else:
                    logger.info("点击每日任务失败")
                    first = True

                if click_back(auto):
                    logger.info("点击返回")
                else:
                    logger.info("点击返回失败")
                    second = True

                
            
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

        logger.info("领取每日任务超时")
        return False
    except Exception as e:
        logger.error(f"领取每日任务过程中出错: {e}")
        return False