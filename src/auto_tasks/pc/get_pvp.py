import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.pc.public import back_to_main, click_back, enter_map_select
from src.auto_tasks.utils.roi_config import roi_config


def get_pvp(auto: Auto, timeout: int = 600) -> bool:
    """PVP奖励领取

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)

    Returns:
        bool: 是否成功完成PVP奖励领取
    """
    logger = auto.get_task_logger("get_pvp")
    logger.info("开始PVP奖励领取流程")

    start_time = time.time()
    state = "init"  # 状态机: init -> arena_entered -> battle_prepared -> battle_completed -> returning

    try:
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            # 初始状态：进入PVP地图
            if state == "init":
                if back_to_main(auto) and enter_map_select(auto, is_swipe=False):
                    if auto.template_click(
                        ["get_pvp/pvp地图", "get_pvp/pvp地图2"], roi=roi_config.get_roi("pvp_map", "get_pvp")
                    ):
                        logger.info("进入PVP地图, next: arena_entered")
                    else:
                        logger.warning("未找到PVP地图")
                        continue

                    auto.sleep(5)
                    state = "arena_entered"
                continue

            # 进入竞技场
            if state == "arena_entered":
                if auto.text_click("游戏卡珍藏集", click=False, roi=roi_config.get_roi("game_collection_text")):
                    logger.debug("未进入PVP地图, next: init")
                    state = "init"
                    continue
                if click_back(auto):
                    logger.info("领取赛季奖励")
                    auto.sleep(2)

                if auto.template_click("get_pvp/进入竞技场", roi=roi_config.get_roi("enter_arena", "get_pvp")):
                    logger.info("进入竞技场")
                    auto.sleep(5)

                # 处理可能的确认弹窗
                if auto.text_click("确认", roi=roi_config.get_roi("confirm_button_pvp")):
                    logger.info("点击确认弹窗")
                    auto.sleep(1)

                # 设置自动战斗
                if auto.template_click("get_pvp/自动战斗", roi=roi_config.get_roi("auto_battle", "get_pvp")):
                    logger.info("进去自动战斗设置界面")
                    auto.sleep(1)

                # 设置MAX次数
                if pos := auto.text_click("MAX", click=False, roi=roi_config.get_roi("max_battle_count", "get_pvp")):
                    logger.info("设置MAX战斗次数")
                    auto.click(pos, click_time=2, coord_type="PHYSICAL")
                    auto.sleep(1)
                    if pos := auto.check_element_exist(
                        "get_pvp/选项完成", roi=roi_config.get_roi("option_completed", "get_pvp")
                    ):
                        logger.info("开始战斗, next: battle_prepared")
                        auto.click(pos, click_time=2, coord_type="LOGICAL")
                        auto.click(pos, click_time=2, coord_type="LOGICAL")
                        state = "battle_prepared"
                continue

            # 战斗处理
            if state == "battle_prepared":
                # 检查是否仍在战斗中
                # 设置MAX次数
                if pos := auto.text_click("MAX", click=False, roi=roi_config.get_roi("max_battle_count", "get_pvp")):
                    logger.info("设置MAX战斗次数")
                    auto.click(pos, click_time=2, coord_type="PHYSICAL")
                    auto.sleep(1)
                    if pos := auto.check_element_exist(
                        "get_pvp/选项完成", roi=roi_config.get_roi("option_completed", "get_pvp")
                    ):
                        logger.info("开始战斗")
                        auto.click(pos, click_time=2, coord_type="LOGICAL")
                        auto.click(pos, click_time=2, coord_type="LOGICAL")
                    continue

                # 处理战斗结果
                if pos := auto.text_click(
                    "反复战斗结果", click=False, roi=roi_config.get_roi("repeat_battle_result", "get_pvp")
                ):
                    if pos := auto.check_element_exist(
                        "get_pvp/X", roi=roi_config.get_roi("close_battle_result", "get_pvp")
                    ):
                        logger.info("关闭战斗结果")
                        auto.click(pos, click_time=2, coord_type="LOGICAL")
                        auto.sleep(1)

                # 离开战斗
                if pos := auto.text_click("离开", click=False, roi=roi_config.get_roi("leave_battle", "get_pvp")):
                    logger.info("离开战斗界面, next: battle_completed")
                    auto.click(pos, click_time=3, coord_type="PHYSICAL")
                    auto.sleep(3)
                    state = "battle_completed"
                else:
                    logger.info("战斗进行中")
                    auto.sleep(10)
                continue

            # 返回主界面
            if state == "battle_completed":
                # 处理可能未点击到离开战斗的情况
                if auto.text_click("离开", click=False, roi=roi_config.get_roi("leave_battle", "get_pvp")):
                    logger.info("未离开战斗界面, next: battle_prepared")
                    state = "battle_prepared"
                    continue
                else:
                    # 处理可能的确认弹窗
                    if pos := auto.text_click("确认", click=False, roi=roi_config.get_roi("confirm_button_pvp")):
                        logger.info("点击确认弹窗（战斗结束）")
                        auto.click(pos)
                        auto.sleep(2)

                    auto.key_press("h")
                    auto.sleep(2)

                    if back_to_main(auto):
                        logger.info("成功返回主界面")
                        return True

                logger.warning("返回主界面失败，next: battle_completed")
                state = "battle_completed"
                continue

            auto.sleep(0.5)

        logger.error("PVP奖励领取超时")
        return False

    except Exception as e:
        logger.error(f"PVP奖励领取过程中出错: {e}")
        return False
