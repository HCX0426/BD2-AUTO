import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import (back_to_main, back_to_map,
                                      calculate_remaining_timeout)
from src.auto_tasks.utils.roi_config import roi_config


def login(auto: Auto, timeout: int = 300) -> bool:
    """登录

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)

    Returns:
        bool: 是否成功登录并返回主界面
    """
    logger = auto.get_task_logger("Login")
    logger.info("开始登录流程")

    start_time = time.time()
    state = "start_screen"  # 状态机: start_screen -> main_check -> popup_handling -> completed

    try:
        while True:
            if timeout > 0 and time.time() - start_time >= timeout:
                logger.error("任务执行超时")
                return False
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            if auto.text_click("确认", roi=roi_config.get_roi("login_confirm_button", "login")):
                logger.info("检测到确认按钮，点击")
                auto.sleep(2)
                continue

            # 处理开始游戏界面
            if state == "start_screen":
                if auto.template_click("login/开始游戏", roi=roi_config.get_roi("login_start_button", "login")):
                    logger.info("检测到开始游戏按钮，点击进入")
                    auto.sleep(3)

                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if back_to_main(auto, remaining_timeout):
                    logger.info("成功进入主界面")
                    state = "popup_handling"
                continue

            # 处理各种弹窗
            if state == "popup_handling":
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if back_to_map(auto, remaining_timeout):
                    logger.info("成功返回地图")
                    state = "completed"
                continue

            if state == "completed":
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if back_to_main(auto, remaining_timeout):
                    total_time = round(time.time() - start_time, 2)
                    minutes = int(total_time // 60)
                    seconds = round(total_time % 60, 2)
                    logger.info(f"登录完成，用时：{minutes}分{seconds}秒")
                    return True
                else:
                    logger.warning("返回主界面失败")
                    return False
            auto.sleep(0.5)
    except Exception as e:
        logger.error(f"登录过程中发生错误: {e}")
        return False