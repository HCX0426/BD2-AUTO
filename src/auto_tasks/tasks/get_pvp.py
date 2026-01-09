"""PVP奖励领取模块

包含PVP竞技场的奖励领取和战斗功能
"""

import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import back_to_main, calculate_remaining_timeout, click_back, enter_map_select
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

    # 记录任务开始时间，用于计算剩余超时
    start_time = time.time()

    # 使用任务链替代状态机
    chain = auto.chain()
    chain.set_total_timeout(timeout)

    # 1. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 2. 进入地图选择
    chain.then().custom_step(lambda: enter_map_select(auto, remaining_timeout, is_swipe=False), timeout=remaining_timeout)

    # 3. 点击PVP地图
    chain.then().template_click(
        ["get_pvp/pvp地图", "get_pvp/pvp地图2"],
        roi=roi_config.get_roi("pvp_map", "get_pvp"),
        verify={
            "type": "text",
            "target": "进入竞技场",
            "roi": roi_config.get_roi("enter_arena", "get_pvp"),
        }
    )

    # 4. 领取赛季奖励（点击返回键）
    chain.then().custom_step(lambda: click_back(auto, remaining_timeout), timeout=remaining_timeout)

    # 5. 进入竞技场
    chain.then().template_click(
        "get_pvp/进入竞技场",
        roi=roi_config.get_roi("enter_arena", "get_pvp"),
        verify={
            "type": "text",
            "target": "自动战斗",
            "roi": roi_config.get_roi("auto_battle", "get_pvp"),
        }
    )

    # 6. 处理可能的确认弹窗
    chain.then().text_click(
        "确认",
        roi=roi_config.get_roi("confirm_button_pvp"),
        verify={
            "type": "text",
            "target": "MAX",
            "roi": roi_config.get_roi("max_battle_count", "get_pvp"),
        }
    )

    # 7. 设置自动战斗
    chain.then().template_click(
        "get_pvp/自动战斗",
        roi=roi_config.get_roi("auto_battle", "get_pvp"),
        verify={
            "type": "text",
            "target": "MAX",
            "roi": roi_config.get_roi("max_battle_count", "get_pvp"),
        }
    )

    # 8. 设置MAX次数并开始战斗
    def set_max_battle_step() -> bool:
        """设置MAX战斗次数并开始战斗的自定义步骤"""
        # 设置MAX次数
        if pos := auto.text_click("MAX", click=False, roi=roi_config.get_roi("max_battle_count", "get_pvp")):
            logger.info("设置MAX战斗次数")
            auto.click(pos, click_time=2, coord_type="PHYSICAL")
            auto.sleep(1)
            if pos := auto.wait_element(
                "get_pvp/选项完成", roi=roi_config.get_roi("option_completed", "get_pvp"), wait_timeout=0
            ):
                logger.info("开始战斗")
                auto.click(pos, click_time=2, coord_type="LOGICAL")
                auto.click(pos, click_time=2, coord_type="LOGICAL")
                return True
        return False
    chain.then().custom_step(set_max_battle_step)

    # 9. 战斗处理（等待战斗完成）
    def wait_battle_complete_step() -> bool:
        """等待战斗完成的自定义步骤"""
        battle_wait_time = 0
        max_battle_wait = 300  # 最大战斗等待时间5分钟
        
        while battle_wait_time < max_battle_wait:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            
            # 检查是否仍在战斗中
            if pos := auto.text_click("MAX", click=False, roi=roi_config.get_roi("max_battle_count", "get_pvp")):
                # 重新设置MAX次数并开始战斗
                logger.info("重新设置MAX战斗次数")
                auto.click(pos, click_time=2, coord_type="PHYSICAL")
                auto.sleep(1)
                if pos := auto.wait_element(
                    "get_pvp/选项完成", roi=roi_config.get_roi("option_completed", "get_pvp"), wait_timeout=0
                ):
                    logger.info("重新开始战斗")
                    auto.click(pos, click_time=2, coord_type="LOGICAL")
                    auto.click(pos, click_time=2, coord_type="LOGICAL")
            
            # 处理战斗结果
            if pos := auto.text_click(
                "反复战斗结果", click=False, roi=roi_config.get_roi("repeat_battle_result", "get_pvp")
            ):
                logger.info("战斗结果已显示")
                return True
            
            logger.info("战斗进行中")
            auto.sleep(10)
            battle_wait_time += 10
        
        logger.warning("战斗等待超时")
        return True  # 超时也返回True，继续后续步骤
    chain.then().custom_step(wait_battle_complete_step, timeout=300)

    # 10. 关闭战斗结果
    chain.then().template_click(
        "get_pvp/X",
        roi=roi_config.get_roi("close_battle_result", "get_pvp"),
        click_time=2,
        coord_type="LOGICAL",
        verify={
            "type": "text",
            "target": "离开",
            "roi": roi_config.get_roi("leave_battle", "get_pvp"),
        }
    )

    # 11. 离开战斗
    chain.then().text_click(
        "离开",
        roi=roi_config.get_roi("leave_battle", "get_pvp"),
        click_time=3,
        coord_type="PHYSICAL",
        verify={
            "type": "text",
            "target": "确认",
            "roi": roi_config.get_roi("confirm_button_pvp"),
        }
    )

    # 12. 处理可能的确认弹窗（战斗结束）
    chain.then().text_click(
        "确认",
        roi=roi_config.get_roi("confirm_button_pvp"),
        verify={"type": "exist", "target": "public/主界面"}
    )

    # 13. 按键返回并返回主界面
    def return_main_step() -> bool:
        """按键返回并返回主界面的自定义步骤"""
        auto.key_press("h")
        auto.sleep(2)
        remaining_timeout = calculate_remaining_timeout(timeout, start_time)
        return back_to_main(auto, remaining_timeout)
    chain.then().custom_step(return_main_step)

    # 执行任务链
    result = chain.execute()

    if result.success:
        total_time = round(result.elapsed_time, 2)
        minutes = int(total_time // 60)
        seconds = round(total_time % 60, 2)
        logger.info(f"PVP奖励领取完成，用时：{minutes}分{seconds}秒")
        return True
    else:
        logger.error(f"PVP奖励领取失败: {result.error_msg}")
        return False
