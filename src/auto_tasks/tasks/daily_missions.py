"""每日任务领取模块

包含每日任务和每周任务的奖励领取功能
"""
import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import back_to_main, click_back, calculate_remaining_timeout
from src.auto_tasks.utils.roi_config import roi_config


def daily_missions(auto: Auto, timeout: int = 300) -> bool:
    """每日任务领取

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)

    Returns:
        bool: 任务是否成功完成
    """
    logger = auto.get_task_logger("daily_missions")
    logger.info("开始领取每日任务")

    start_time = time.time()

    # 使用任务链替代状态机
    chain = auto.chain()
    chain.set_total_timeout(timeout)

    remaining_timeout = calculate_remaining_timeout(timeout, start_time)

    # 1. 返回主界面
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 2. 进入任务界面
    chain.then().text_click(
        "任务",
        roi=roi_config.get_roi("daily_missions_text", "daily_missions"),
        verify={"type": "text", "target": "每日任务", "roi": roi_config.get_roi("daily_tasks", "daily_missions")},
        click_time=2
    )

    # 3. 领取每日任务奖励
    def receive_daily_rewards_step() -> bool:
        """领取每日任务奖励的自定义步骤"""
        pos = auto.text_click(
            "全部获得", 
            click=False, 
            roi=roi_config.get_roi("receive", "daily_missions"),
            verify={"type": "exist", "target": "每日任务", "roi": roi_config.get_roi("daily_tasks", "daily_missions")}
        )
        if pos:
            logger.info("点击全部获得按钮")
            for _ in range(2):
                auto.click(pos, click_time=2, coord_type="LOGICAL")
                auto.sleep(1)
            
            click_back(auto, remaining_timeout)
            logger.info("每日任务奖励领取成功")
        else:
            logger.warning("无每日任务奖励可以领取")
        return True
    chain.then().custom_step(receive_daily_rewards_step)

    # 4. 进入每周任务界面
    chain.then().text_click(
        "每周任务", 
        click_time=2, 
        roi=roi_config.get_roi("weekly_missions_text", "daily_missions"),
        verify={"type": "text", "target": "每周任务"}
    )

    # 5. 领取每周任务奖励
    chain.then().text_click(
        "全部获得", 
        click_time=2, 
        roi=roi_config.get_roi("receive", "daily_missions"),
        verify={"type": "text", "target": "每周任务"}
    )

    # 6. 返回主界面
    chain.then().custom_step(
        lambda: (
            click_back(auto, remaining_timeout) or True,  # 确保返回True，继续执行
            auto.key_press("esc"),
            auto.sleep(1),
            back_to_main(auto, remaining_timeout)
        )[3],  # 返回back_to_main的结果
        timeout=remaining_timeout
    )

    # 执行任务链
    result = chain.execute()

    if result.success:
        total_time = round(result.elapsed_time, 2)
        minutes = int(total_time // 60)
        seconds = round(total_time % 60, 2)
        logger.info(f"每日任务领取完成，用时：{minutes}分{seconds}秒")
        return True
    else:
        logger.error(f"每日任务领取失败: {result.error_msg}")
        return False