"""地图奖励收集模块

包含地图探索和奖励收集功能
"""
import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import (
                                      back_to_main,
                                      calculate_remaining_timeout,
                                      enter_map_select)


def map_collection(auto: Auto, timeout: int = 600) -> bool:
    """地图奖励收集

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)

    Returns:
        bool: 是否成功完成地图奖励收集
    """
    logger = auto.get_task_logger("get_map_collection")
    logger.info("开始地图奖励收集流程")

    start_time = time.time()

    # 使用任务链替代状态机
    chain = auto.chain()
    chain.set_total_timeout(timeout)

    # 1. 返回主界面并进入地图选择
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    def enter_map_step() -> bool:
        """进入地图选择的自定义步骤"""
        return back_to_main(auto, remaining_timeout) and enter_map_select(auto, remaining_timeout)
    chain.then().custom_step(enter_map_step, timeout=remaining_timeout)

    # 2. 选择第七章地图（包含滑动寻找逻辑）
    def select_chapter_step() -> bool:
        """选择第七章地图的自定义步骤"""
        # 尝试找到第七章地图
        if auto.template_click(
            "map_collection/第七章1",
            verify={"type": "exist", "target": "map_collection/探寻"},
        ):
            logger.info("进入第七章1")
            auto.sleep(5)
            return True
        elif auto.template_click(
            "map_collection/第七章2",
            verify={"type": "exist", "target": "map_collection/探寻"},
        ):
            logger.info("进入第七章2")
            auto.sleep(5)
            return True
        else:
            # 滑动地图寻找第七章
            logger.info("滑动寻找第七章")
            auto.swipe((1666, 266), (833, 266), duration=5, steps=4, coord_type="BASE")
            auto.sleep(2)
            return False  # 返回False会触发重试
    chain.then().custom_step(select_chapter_step)

    # 3. 开始探寻
    chain.then().template_click(
        "map_collection/探寻",
        click_time=2,
        verify={"type": "exist", "target": "map_collection/材料吸收"},
    )

    # 4. 收集材料
    chain.then().template_click(
        "map_collection/材料吸收",
        click_time=2,
        verify={"type": "exist", "target": "map_collection/吸收材料完成"},
    )

    # 5. 收集金币
    chain.then().template_click(
        "map_collection/金币吸收",
        click_time=2,
        verify={"type": "exist", "target": "map_collection/金币吸收完成"},
    )

    # 6. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 执行任务链
    result = chain.execute()

    if result.success:
        total_time = round(result.elapsed_time, 2)
        minutes = int(total_time // 60)
        seconds = round(total_time % 60, 2)
        logger.info(f"地图奖励收集完成，用时：{minutes}分{seconds}秒")
        return True
    else:
        logger.error(f"地图奖励收集失败: {result.error_msg}")
        return False