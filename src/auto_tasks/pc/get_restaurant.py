import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.pc.public import (back_to_main,
                                      calculate_remaining_timeout, click_back)
from src.auto_tasks.utils.roi_config import roi_config


def get_restaurant(auto: Auto, timeout: int = 600, is_upgrade: bool = False) -> bool:
    """餐厅领取奖励
    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)
    Returns:
        bool: 是否成功领取奖励
    """

    logger = auto.get_task_logger("get_restaurant")
    logger.info("开始领取餐厅奖励")
    start_time = time.time()

    # 状态定义
    state = "first"  # first -> second -> third -> fourth

    try:
        while True:
            if timeout > 0 and time.time() - start_time >= timeout:
                logger.error("任务执行超时")
                return False
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            if state == "first":
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if back_to_main(auto, remaining_timeout):
                    if auto.click((163, 257), coord_type="BASIC"):
                        logger.info("点击经营管理, next: second")
                        auto.sleep(2)
                        state = "second"
                        continue

            elif state == "second":
                if auto.text_click("获得", roi=roi_config.get_roi("obtain_restaurant_reward", "get_restaurant")):
                    logger.info("点击获得, next: third")
                    auto.sleep(3)
                    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                    if click_back(auto, remaining_timeout):
                        logger.info("领取成功")
                    else:
                        logger.info("无需结算")
                    state = "third"
                    continue
                else:
                    logger.info("未检测到一键获得按钮, next: first")
                    state = "first"  # 回到初始状态
                    continue

            elif state == "third":
                if auto.text_click("立刻前往", roi=roi_config.get_roi("immediate_go", "get_restaurant")):
                    logger.info("点击立刻前往, next: fourth")
                    auto.sleep(3)
                    state = "fourth"
                    continue

            elif state == "fourth":
                if pos_1 := auto.text_click(
                    "常客", click=False, roi=roi_config.get_roi("frequent_visitor", "get_restaurant")
                ):
                    if is_upgrade:
                        if pos := auto.check_element_exist("get_restaurant/下一阶段"):
                            logger.info("点击下一阶段")
                            auto.click(pos, click_time=2)
                            auto.sleep(1)
                            continue

                        if pos := auto.check_element_exist("get_restaurant/升级"):
                            logger.info("点击升级")
                            auto.click(pos, click_time=2)
                            auto.sleep(1)
                            continue

                    logger.info("点击常客, next: fifth")
                    auto.click(pos_1, click_time=2, coord_type="LOGICAL")
                    auto.sleep(1)
                    auto.key_press("h")
                    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                    if back_to_main(auto, remaining_timeout):
                        total_time = round(time.time() - start_time, 2)
                        minutes = int(total_time // 60)
                        seconds = round(total_time % 60, 2)
                        logger.info(f"餐厅奖励领取完成，用时：{minutes}分{seconds}秒")
                        return True
                    return False
                else:
                    if pos := auto.text_click("点击画面关闭", click=False):
                        logger.info("点击画面关闭")
                        auto.click(pos, click_time=2)
                        continue

                    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                    if click_back(auto, remaining_timeout):
                        logger.info("点击返回")
                        auto.sleep(1)
                        continue

                    if auto.text_click("立刻前往", roi=roi_config.get_roi("immediate_go", "get_restaurant")):
                        logger.info("点击立刻前往")
                        auto.sleep(3)
                        continue

            auto.sleep(0.5)

    except Exception as e:
        logger.error(f"餐厅奖励领取出错: {e}")
        return False