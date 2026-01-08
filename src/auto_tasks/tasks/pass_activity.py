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
    state = "init"  # 状态机: init -> entered -> challenge_selected -> quick_battle -> battle_confirmed -> returning

    try:
        while True:
            if timeout > 0 and time.time() - start_time >= timeout:
                logger.error("任务执行超时")
                return False
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            remaining_timeout = calculate_remaining_timeout(timeout, start_time)
            
            # 初始状态：进入活动界面
            if state == "init":
                if back_to_main(auto, remaining_timeout):
                    if auto.click(
                        (1700, 480),
                        click_time=2,
                        coord_type="BASE",
                        verify={"type": "text", "target": "挑战战斗"},
                    ):
                        logger.info("进入活动关卡")
                    auto.sleep(2)
                    state = "entered"
                continue

            # 进入挑战战斗
            if state == "entered":
                if auto.text_click(
                    "挑战战斗",
                    click_time=3,
                    verify={"type": "exist", "target": f"pass_activity/{level_name}"},
                ):
                    logger.info("进入挑战战斗界面")
                    state = "challenge_selected"
                else:
                    logger.error("未找到挑战战斗按钮,尝试点击坐标")
                    auto.click((1700, 480), click_time=2, coord_type="BASE")
                continue

            # 选择特定关卡
            if state == "challenge_selected":
                # 检查是否仍在挑战战斗界面
                if auto.text_click("行程", click=False):
                    logger.info("仍在挑战战斗界面")
                    state = "entered"
                    continue

                if auto.template_click(
                    f"pass_activity/{level_name}",
                    verify={"type": "text", "target": "快速战斗"},
                ):
                    logger.info(f"选择{level_name}")
                    auto.sleep(1)

                    if auto.text_click(
                        "快速战斗",
                        coord_type="PHYSICAL",
                        verify={"type": "text", "target": "MAX"},
                    ):
                        logger.info("进入快速战斗界面")
                        state = "quick_battle"
                    else:
                        logger.error("未找到快速战斗按钮,跳过")
                        state = "battle_confirmed"

                continue

            # 快速战斗设置
            if state == "quick_battle":
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
                        state = "battle_confirmed"
                elif pos := auto.text_click("补充", click=False):
                    logger.info("AP不足")
                    if auto.text_click(
                        "取消", 
                        click_time=2,
                        verify={"type": "exist", "target": "pass_activity/挑战战斗"},
                    ):
                        logger.info("取消补充AP")
                        state = "battle_confirmed"
                continue

            # 战斗确认后返回
            if state == "battle_confirmed":
                if click_back(auto, remaining_timeout):
                    logger.info("从战斗界面返回")
                auto.key_press("esc")

                # 检查是否在挑战战斗界面
                if auto.text_click("行程", click=False):
                    logger.info("已在挑战战斗界面")
                    state = "boss"
                continue

            if state == "boss":
                if auto.text_click(
                    "魔物追踪者",
                    click_time=2,
                    verify={"type": "text", "target": "快速战斗"},
                ):
                    logger.info("进入魔物追踪者界面")
                    auto.sleep(2)
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
                        logger.error("无法点击确认")
                        state = "returning"
                else:
                    logger.info("未找到快速战斗按钮,跳过")
                    state = "returning"

                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if click_back(auto, remaining_timeout):
                    logger.info("领取奖励")
                    state = "returning"
                continue

            if state == "back":
                if auto.text_click(
                    "返回",
                    click_time=2,
                    verify={"type": "exist", "target": "pass_activity/挑战战斗", "timeout": 5},
                    retry=1
                ):
                    logger.info("返回魔兽界面")
                    state = "returning"

            # 返回主界面
            if state == "returning":
                if back_to_main(auto, remaining_timeout):
                    total_time = round(time.time() - start_time, 2)
                    minutes = int(total_time // 60)
                    seconds = round(total_time % 60, 2)
                    logger.info(f"活动关卡扫荡完成，用时：{minutes}分{seconds}秒")
                    return True

                logger.warning("返回主界面失败，重试中...")
                state = "init"  # 返回失败则重新开始流程
                continue

            auto.sleep(0.5)

    except Exception as e:
        logger.error(f"活动关卡扫荡过程中出错: {e}")
        return False