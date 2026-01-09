"""活动关卡扫荡模块

包含活动关卡的扫荡功能
"""
import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import (
                                      back_to_main,
                                      calculate_remaining_timeout, click_back)


def pass_activity(auto: Auto, timeout: int = 600, level_name: str = "第15关") -> bool:
    """活动关卡扫荡

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)
        level_name: 活动关卡名称
    Returns:
        bool: 是否成功完成活动关卡扫荡
    """
    logger = auto.get_task_logger("pass_activity")
    logger.info("开始活动关卡扫荡流程")

    start_time = time.time()

    # 使用任务链替代状态机
    chain = auto.chain()
    chain.set_total_timeout(timeout)

    # 1. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 2. 点击活动关卡坐标
    chain.then().click(
        (1700, 480),
        click_time=2,
        coord_type="BASE",
        verify={"type": "text", "target": "挑战战斗"},
    )

    # 3. 点击挑战战斗
    chain.then().text_click(
        "挑战战斗",
        click_time=3,
        verify={"type": "exist", "target": f"pass_activity/{level_name}"},
    )

    # 4. 选择特定关卡
    chain.then().template_click(
        f"pass_activity/{level_name}",
        verify={"type": "text", "target": "快速战斗"},
    )

    # 5. 点击快速战斗
    chain.then().text_click(
        "快速战斗",
        coord_type="PHYSICAL",
        verify={"type": "text", "target": "MAX"},
    )

    # 6. 设置MAX次数并开始战斗
    def quick_battle_step() -> bool:
        """快速战斗设置的自定义步骤"""
        if pos := auto.text_click("MAX", click=False):
            logger.info("设置MAX战斗次数")
            auto.click(pos, click_time=2)
            auto.sleep(1)
            if auto.template_click(
                "pass_activity/战斗",
                click_time=2,
                verify={"type": "exist", "target": "public/返回键1"},
            ):
                logger.info("开始战斗")
                auto.sleep(3)
                return True
        elif pos := auto.text_click("补充", click=False):
            logger.info("AP不足")
            if auto.text_click(
                "取消", 
                click_time=2,
                verify={"type": "exist", "target": "pass_activity/挑战战斗"},
            ):
                logger.info("取消补充AP")
                return True
        return True  # 无论成功与否都继续后续步骤
    chain.then().custom_step(quick_battle_step)

    # 7. 返回并按键返回
    def return_and_esc_step() -> bool:
        """返回并按键返回的自定义步骤"""
        click_back(auto, remaining_timeout)
        logger.info("从战斗界面返回")
        auto.key_press("esc")
        return True
    chain.then().custom_step(return_and_esc_step)

    # 8. 处理魔物追踪者
    def handle_boss_step() -> bool:
        """处理魔物追踪者的自定义步骤"""
        # 点击魔物追踪者
        auto.text_click(
            "魔物追踪者",
            click_time=2,
            verify={"type": "text", "target": "快速战斗"},
        )
        logger.info("进入魔物追踪者界面")
        auto.sleep(2)
        
        # 点击快速战斗
        if auto.text_click(
            "快速战斗",
            verify={"type": "text", "target": "确认"},
        ):
            logger.info("点击快速战斗")
            auto.sleep(1)
            if pos := auto.text_click("确认", click=False):
                logger.info("确认战斗")
                auto.click(pos, click_time=2)
                auto.sleep(3)
        else:
            logger.info("未找到快速战斗按钮,跳过")
        
        # 返回
        remaining_timeout = calculate_remaining_timeout(timeout, start_time)
        click_back(auto, remaining_timeout)
        logger.info("领取奖励")
        return True
    chain.then().custom_step(handle_boss_step)

    # 9. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 执行任务链
    result = chain.execute()

    if result.success:
        total_time = round(result.elapsed_time, 2)
        minutes = int(total_time // 60)
        seconds = round(total_time % 60, 2)
        logger.info(f"活动关卡扫荡完成，用时：{minutes}分{seconds}秒")
        return True
    else:
        logger.error(f"活动关卡扫荡失败: {result.error_msg}")
        return False