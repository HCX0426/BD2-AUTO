"""邮件领取模块

包含邮件的检查和奖励领取功能
"""

import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import back_to_main, calculate_remaining_timeout, click_back
from src.auto_tasks.utils.roi_config import roi_config


def get_email(auto: Auto, timeout: int = 300) -> bool:
    """邮件领取

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)

    Returns:
        bool: 邮件是否成功领取
    """
    logger = auto.get_task_logger("get_email")
    logger.info("开始领取邮件")

    # 记录任务开始时间，用于计算剩余超时
    start_time = time.time()

    # 使用任务链替代状态机
    chain = auto.chain()
    chain.set_total_timeout(timeout)

    # 1. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 2. 进入邮箱界面
    chain.then().template_click(
        "get_email/邮箱",
        roi=roi_config.get_roi("email_box", "get_email"),
        verify={
            "type": "text",
            "target": "普通邮箱",
            "roi": roi_config.get_roi("regular_email", "get_email"),
        }
    )

    # 3. 领取邮件（包含检查邮箱是否为空的逻辑）
    def claim_email_step() -> bool:
        """领取邮件的自定义步骤，处理邮箱为空的情况"""
        # 检查邮箱是否为空
        if auto.wait_element("get_email/空邮箱标识", roi=roi_config.get_roi("empty_email", "get_email"), wait_timeout=0):
            logger.info("邮箱为空，无需领取")
            return True
        # 领取邮件
        logger.info("邮箱有内容，尝试领取")
        return auto.text_click(
            "全部领取",
            roi=roi_config.get_roi("claim_all", "get_email"),
            verify={
                "type": "exist",
                "target": "get_email/空邮箱标识",
                "roi": roi_config.get_roi("empty_email", "get_email"),
            }
        )
    chain.then().custom_step(claim_email_step)

    # 4. 从邮箱界面返回
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: click_back(auto, remaining_timeout), timeout=remaining_timeout)

    # 5. 最终返回主界面确认
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, min(10, remaining_timeout)), timeout=min(10, remaining_timeout))

    # 执行任务链
    result = chain.execute()

    if result.success:
        total_time = round(result.elapsed_time, 2)
        minutes = int(total_time // 60)
        seconds = round(total_time % 60, 2)
        logger.info(f"邮件领取完成，用时：{minutes}分{seconds}秒")
        return True
    else:
        logger.error(f"邮件领取失败: {result.error_msg}")
        return False
