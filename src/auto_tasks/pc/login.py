import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.pc.public import back_to_main, back_to_map
from src.auto_tasks.utils.roi_config import rois


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
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            if auto.text_click("确认", roi=rois["login_confirm_button"]):
                logger.info("检测到确认按钮，点击")
                auto.sleep(2)
                continue

            # 处理开始游戏界面
            if state == "start_screen":
                if pos := auto.check_element_exist("login/开始游戏"):
                    logger.info("检测到开始游戏按钮，点击进入")
                    auto.click(pos, click_time=3)
                    auto.sleep(3)

                if back_to_main(auto):
                    logger.info("成功进入主界面")
                    state = "popup_handling"
                continue

            # 处理各种弹窗
            if state == "popup_handling":
                if back_to_map(auto):
                    logger.info("成功返回地图")
                    state = "completed"
                    continue

            if state == "completed":
                if back_to_main(auto):
                    logger.info("所有弹窗处理完成，返回主界面成功")
                    return True
                else:
                    logger.warning("返回主界面失败")
                    return False
            auto.sleep(0.5)
        logger.error("登录流程超时")
        return False
    except Exception as e:
        logger.error(f"登录过程中发生错误: {e}")
        return False
