"""每日任务领取模块

包含每日任务和每周任务的奖励领取功能
"""

import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import back_to_main, calculate_remaining_timeout, click_back
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
        click_time=2,
    )

    # 3. 领取每日任务奖励 - 使用纯链式操作
    # 设计：识别到"全部获得"时点击，然后执行click_back，click_back结果不影响步骤，识别不到目标时直接继续
    def receive_rewards_step():
        # 尝试点击"全部获得"，不重试，识别不到就返回
        click_result = auto.text_click(
            "全部获得", roi=roi_config.get_roi("receive", "daily_missions"), click_time=2, retry=0
        )
        # 如果点击成功，执行click_back，结果不影响步骤
        if click_result.success:
            auto.logger.info("点击全部获得按钮")
            click_back(auto, remaining_timeout)  # 执行click_back，结果忽略
        else:
            auto.logger.warning("无每日任务奖励可以领取")
        return True  # 无论如何都返回成功，继续下一个步骤

    chain.then().custom_step(
        func=receive_rewards_step, timeout=remaining_timeout, retry_on_failure=False  # 确保步骤永远成功，不影响后续执行
    )

    # 4. 进入每周任务界面 - 识别到目标时点击，结果不影响后续步骤
    chain.then().text_click(
        "每周任务",
        click_time=2,
        roi=roi_config.get_roi("weekly_missions_text", "daily_missions"),
        retry_on_failure=False,  # 识别不到时直接继续
    )

    # 5. 领取每周任务奖励 - 识别到目标时点击，结果不影响后续步骤
    def receive_weekly_rewards_step():
        # 尝试点击"全部获得"，不重试，识别不到就返回
        click_result = auto.text_click(
            "全部获得", roi=roi_config.get_roi("receive", "daily_missions"), click_time=2, retry=0
        )
        # 如果点击成功，执行click_back，结果不影响步骤
        if click_result.success:
            auto.logger.info("点击每周任务全部获得按钮")
            click_back(auto, remaining_timeout)  # 执行click_back，结果忽略
        else:
            auto.logger.warning("无每周任务奖励可以领取")
        return True  # 无论如何都返回成功，继续下一个步骤

    chain.then().custom_step(
        func=receive_weekly_rewards_step,
        timeout=remaining_timeout,
        retry_on_failure=False,  # 确保步骤永远成功，不影响后续执行
    )

    # 6. 返回主界面 - 直接调用back_to_main函数，它已包含完整返回逻辑
    chain.then().custom_step(
        func=lambda: back_to_main(auto, remaining_timeout),
        timeout=remaining_timeout,
        retry_on_failure=False,  # 失败时直接继续
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
