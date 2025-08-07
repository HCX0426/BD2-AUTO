import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, click_back


def pass_activity(auto: Auto, timeout: int = 600):
    """扫荡活动关"""
    try:
        logger = auto.get_task_logger("pass_activity")
        logger.info("开始扫荡活动")
        start_time = time.time()
        first = True
        second = True
        third = True
        fourth = True
        fifth = True
        sixth = True

        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            # 检测是否在主界面
            if first:
                if back_to_main(auto):
                    pos = auto.check_element_exist("pass_activity/活动关入口")
                    if pos:
                        auto.click(pos)
                        auto.sleep(2)
                        first = False
                    else:
                        logger.info("未检测到活动关入口")
                        return False
            if not first and second:
                if auto.text_click("挑战战斗"):
                    logger.info("进入挑战战斗")
                    second = False

            if not second and third:
                if auto.text_click("挑战战斗",click=False):
                    logger.info("检测到挑战战斗")
                    second = True
                    continue

                pos = auto.check_element_exist("pass_activity/困难第15关")
                if pos:
                    auto.click(pos,time=2)
                    logger.info("点击困难第15关")
                    auto.sleep(1)

                    if auto.text_click("快速战斗"):
                        logger.info("进入快速战斗")
                        third = False
            if not third and fourth:
                if auto.text_click("MAX"):
                    logger.info("点击MAX")
                    pos = auto.check_element_exist("pass_activity/战斗")
                    if pos:
                        logger.info("检测到战斗")
                        auto.click(pos)
                        auto.sleep(3)
                        fourth = False

            if not fourth and fifth:
                if click_back(auto):
                    logger.info("点击画面即可返回")
                    fifth = False
                else:
                    logger.info("未检测到点击画面即可返回")

            if not fifth and sixth:
                if back_to_main(auto):
                    logger.info("返回主界面成功")
                    return True
                else:
                    logger.info("返回主界面失败")
            
            auto.sleep(0.5)  # 每次循环添加短暂延迟

        logger.info("扫荡活动超时")
        return False
    except Exception as e:
        logger.error(f"扫荡活动过程中出错: {e}")
        return False