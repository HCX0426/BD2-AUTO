"""餐厅奖励领取模块

包含餐厅奖励的领取和升级功能
"""

import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import back_to_main, calculate_remaining_timeout, click_back
from src.auto_tasks.utils.roi_config import roi_config


def get_restaurant(auto: Auto, timeout: int = 600, is_upgrade: bool = False) -> bool:
    """餐厅领取奖励
    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)
        is_upgrade: 是否升级餐厅
    Returns:
        bool: 是否成功领取奖励
    """

    logger = auto.get_task_logger("get_restaurant")
    logger.info("开始领取餐厅奖励")
    start_time = time.time()

    # 使用任务链替代状态机
    chain = auto.chain()
    chain.set_total_timeout(timeout)

    remaining_timeout = calculate_remaining_timeout(timeout, start_time)

    # 1. 返回主界面
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 2. 点击经营管理
    chain.then().click(
        (163, 257),
        coord_type="BASE",
        verify={
            "type": "text",
            "target": "获得",
            "roi": roi_config.get_roi("obtain_restaurant_reward", "get_restaurant"),
        },
    )

    # 3. 点击获得
    def get_reward_step() -> bool:
        """点击获得奖励的自定义步骤"""
        if auto.text_click(
            "获得",
            roi=roi_config.get_roi("obtain_restaurant_reward", "get_restaurant"),
        ):
            logger.info("点击获得")
            remaining_timeout = calculate_remaining_timeout(timeout, start_time)
            if click_back(auto, remaining_timeout):
                logger.info("领取成功")
            else:
                logger.info("无需结算")
            return True
        else:
            logger.info("未检测到一键获得按钮")
            return False
    chain.then().custom_step(get_reward_step)

    # 4. 点击立刻前往
    chain.then().text_click(
        "立刻前往",
        roi=roi_config.get_roi("immediate_go", "get_restaurant"),
        verify={
            "type": "text",
            "target": "常客",
            "roi": roi_config.get_roi("frequent_visitor", "get_restaurant"),
        },
    )

    # 5. 处理常客界面（包括升级逻辑）
    def handle_frequent_visitor_step() -> bool:
        """处理常客界面的自定义步骤"""
        if pos_1 := auto.text_click(
            "常客", click=False, roi=roi_config.get_roi("frequent_visitor", "get_restaurant")
        ):
            if is_upgrade:
                # 尝试点击下一阶段
                auto.template_click(
                    "get_restaurant/下一阶段",
                    click_time=2,
                    verify={"type": "exist", "target": "get_restaurant/下一阶段"},
                )
                logger.info("点击下一阶段")
                auto.sleep(1)
                
                # 尝试点击升级
                auto.template_click(
                    "get_restaurant/升级",
                    click_time=2,
                    verify={"type": "exist", "target": "get_restaurant/升级"},
                )
                logger.info("点击升级")
                auto.sleep(1)
            
            logger.info("点击常客")
            auto.click(pos_1, click_time=2, coord_type="LOGICAL")
            auto.sleep(1)
            auto.key_press("h")
            remaining_timeout = calculate_remaining_timeout(timeout, start_time)
            return back_to_main(auto, remaining_timeout)
        else:
            # 处理画面关闭和返回
            if pos := auto.text_click("点击画面关闭", click=False):
                logger.info("点击画面关闭")
                auto.click(pos, click_time=2)
            else:
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                click_back(auto, remaining_timeout)
                logger.info("点击返回")
                auto.sleep(1)
            return True
    chain.then().custom_step(handle_frequent_visitor_step)

    # 执行任务链
    result = chain.execute()

    if result.success:
        total_time = round(result.elapsed_time, 2)
        minutes = int(total_time // 60)
        seconds = round(total_time % 60, 2)
        logger.info(f"餐厅奖励领取完成，用时：{minutes}分{seconds}秒")
        return True
    else:
        logger.error(f"餐厅奖励领取失败: {result.error_msg}")
        return False
