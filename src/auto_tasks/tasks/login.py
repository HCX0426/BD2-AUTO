"""登录模块

包含游戏登录和返回主界面的功能
"""
import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import back_to_main, back_to_map, calculate_remaining_timeout
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
    state = "init"  # 状态机: init -> confirm_checked -> game_started -> main_returned -> map_returned -> completed

    try:
        while True:
            if timeout > 0 and time.time() - start_time >= timeout:
                logger.error("任务执行超时")
                return False
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            remaining_timeout = calculate_remaining_timeout(timeout, start_time)
            
            # 1. 处理确认按钮
            if state == "init":
                logger.info("检查是否有确认按钮")
                auto.text_click(
                    "确认", 
                    roi=roi_config.get_roi("login_confirm_button", "login"),
                    verify={"type": "exist", "target": "login/开始游戏", "timeout": 5, "roi": roi_config.get_roi("login_start_button", "login")},
                    retry=1,
                    delay=1
                )
                auto.sleep(2)
                state = "confirm_checked"
                continue

            # 2. 点击开始游戏按钮，验证进入游戏
            if state == "confirm_checked":
                logger.info("点击开始游戏按钮")
                if auto.template_click(
                    "login/开始游戏",
                    roi=roi_config.get_roi("login_start_button", "login"),
                    verify={
                        "type": "exist",
                        "target": "main_ui/主界面",
                        "timeout": 20
                    },
                    retry=2,
                    delay=1
                ):
                    auto.sleep(3)
                    state = "game_started"
                continue

            # 3. 返回主界面
            if state == "game_started":
                logger.info("返回主界面")
                if back_to_main(auto, remaining_timeout):
                    state = "main_returned"
                continue

            # 4. 处理弹窗，返回地图
            if state == "main_returned":
                logger.info("处理弹窗，返回地图")
                if back_to_map(auto, remaining_timeout):
                    state = "map_returned"
                continue

            # 5. 返回主界面，完成登录
            if state == "map_returned":
                logger.info("返回主界面，完成登录")
                if back_to_main(auto, remaining_timeout):
                    total_time = round(time.time() - start_time, 2)
                    minutes = int(total_time // 60)
                    seconds = round(total_time % 60, 2)
                    logger.info(f"登录完成，用时：{minutes}分{seconds}秒")
                    return True
                continue

    except Exception as e:
        logger.error(f"登录过程中发生错误: {e}")
        return False