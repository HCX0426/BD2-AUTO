import time

from auto_control import Auto
from auto_tasks.pc.public import back_to_main


def lucky_draw(auto: Auto, timeout: int = 900, target_count: int = 6):
    """抽抽乐
    
    Args:
        timeout: 任务超时时间(秒)
        target_count: 目标抽奖次数
    
    Returns:
        bool: 是否成功完成抽抽乐流程
    """
    try:
        logger = auto.get_task_logger("lucky_draw")
        logger.info("开始抽抽乐")
        start_time = time.time()
        first = True
        last_count = 0

        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            # 检测是否在主界面
            if first:
                if back_to_main(auto):
                    auto.text_click("抽抽乐")
                    auto.sleep(4)
                    first = False

            if not first:
                if auto.text_click("免费1次"):
                    logger.info("检测到免费1次")
                    auto.sleep(2)
                else:
                    if last_count != target_count:
                        last_count = target_count
                        if auto.swipe((410, 410), (410, 180), duration=6, steps=6):
                            logger.info("滑动抽抽乐")
                            auto.sleep(2)
                    else:
                        if auto.swipe((410, 310), (410, 185), duration=4, steps=4):
                            logger.info("滑动抽抽乐")
                            auto.sleep(2)

                    if auto.click((410, 310), time=2):
                        logger.info("点击抽抽乐")
                        auto.sleep(2)

                if auto.text_click("购买"):
                    logger.info("点击购买")
                    auto.sleep(2)
                pos = None
                if pos := auto.check_element_exist("public/跳过"):
                    logger.info("点击跳过")
                    auto.click(pos)
                    auto.sleep(1)
                if auto.check_element_exist("lucky_draw/抽完标识"):
                    logger.info("检测到抽完标识")
                    auto.sleep(1)
                    auto.key_press('esc')
                    auto.sleep(1)
                    target_count -= 1
            else:
                logger.info("进入抽抽乐")
                first = True
            if target_count <= 0:
                logger.info("抽抽乐次数已达上限")
                if back_to_main(auto):
                    logger.info("返回主界面成功")
                else:
                    logger.info("返回主界面失败")
                return True

            auto.sleep(0.5)  # 每次循环添加短暂延迟

        logger.info("领取公会奖励超时")
        return False
    except Exception as e:
        logger.error(f"领取公会奖励过程中出错: {e}")
        return False
