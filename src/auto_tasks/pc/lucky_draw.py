import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.pc.public import back_to_main, calculate_remaining_timeout


def lucky_draw(auto: Auto, timeout: int = 400, target_count: int = 7):
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
        last_count = target_count

        while True:
            if timeout > 0 and time.time() - start_time >= timeout:
                logger.error("任务执行超时")
                return False
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            # 检测是否在主界面
            if first:
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if back_to_main(auto, remaining_timeout):
                    auto.text_click("抽抽乐")
                    auto.sleep(3)
                    first = False

            if not first:
                if auto.text_click("免费1次"):
                    logger.info("检测到免费1次")
                    auto.sleep(2)
                else:
                    if last_count != target_count:
                        last_count = target_count
                        if auto.swipe((410, 410), (410, 203), duration=2, steps=2, coord_type="BASE"):
                            logger.info("滑动抽抽乐")
                            auto.sleep(2)
                    else:
                        if auto.swipe((410, 310), (410, 203), duration=1, steps=2, coord_type="BASE"):
                            logger.info("滑动抽抽乐")
                            auto.sleep(1)

                    if auto.click((410, 310), click_time=2, coord_type="BASE"):
                        auto.click((410, 310), click_time=2, coord_type="BASE")
                        auto.sleep(1)
                        auto.click((410, 310), click_time=2, coord_type="BASE")
                        auto.sleep(1)
                        logger.info("点击抽抽乐")

                if auto.text_click("购买", click_time=2):
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
                    auto.key_press("esc")
                    auto.sleep(1)
                    target_count -= 1
            else:
                logger.info("进入抽抽乐")
                first = True
            if target_count <= 0:
                logger.info("抽抽乐次数已达上限")
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if back_to_main(auto, remaining_timeout):
                    logger.info("返回主界面成功")
                else:
                    logger.info("返回主界面失败")
                total_time = round(time.time() - start_time, 2)
                minutes = int(total_time // 60)
                seconds = round(total_time % 60, 2)
                logger.info(f"抽抽乐完成，用时：{minutes}分{seconds}秒")
                return True

            auto.sleep(0.5)  # 每次循环添加短暂延迟

    except Exception as e:
        logger.error(f"抽抽乐过程中出错: {e}")
        return False