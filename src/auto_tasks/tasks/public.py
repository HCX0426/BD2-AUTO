"""公共任务函数模块

包含各种任务共享的函数，如超时计算、返回主界面、返回地图等
"""

import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.utils.roi_config import roi_config


def calculate_remaining_timeout(timeout: int, start_time: float) -> int:
    """
    计算剩余超时时间

    Args:
        timeout: 原始超时时间(秒)
        start_time: 任务开始时间戳

    Returns:
        int: 剩余超时时间(秒)，最小值为0
    """
    return max(0, timeout - int(time.time() - start_time)) if timeout > 0 else 0


def back_to_main(auto: Auto, timeout: int = 30) -> bool:
    """
    返回主界面

    Args:
        auto: Auto控制实例
        timeout: 剩余超时时间(秒)

    Returns:
        bool: 是否成功返回主界面
    """
    logger = auto.logger.create_task_logger("back_to_main")
    start_time = time.time()

    try:
        # 检查是否已在主界面
        if auto.check_element_exist("public/主界面", roi=roi_config.get_roi("main_menu")):
            logger.debug("已在主界面")
            return True

        # 等待主界面出现，使用新的wait_element API
        if auto.wait_element("public/主界面", timeout=timeout, roi=roi_config.get_roi("main_menu")):
            logger.debug("等待主界面成功")
            return True

        # 备用返回方式，使用带有验证和重试的template_click
        logger.info("尝试使用返回键返回主界面")
        if auto.template_click(
            ["public/返回键1", "public/返回键2"],
            roi=roi_config.get_roi("back_button"),
            verify={"type": "exist", "target": "public/主界面", "roi": roi_config.get_roi("main_menu")},
        ):
            return True

        # 检查结束游戏文本
        end_game_pos = auto.text_click("结束游戏", click=False, roi=roi_config.get_roi("end_game_text"))
        if end_game_pos:
            logger.info("尝试使用ESC+H返回主界面")
            auto.key_press("esc")
            auto.sleep(1)
            auto.key_press("h")
            # 使用wait_element等待主界面出现
            if auto.wait_element("public/主界面", timeout=5, roi=roi_config.get_roi("main_menu")):
                return True

        logger.warning(f"返回主界面失败，已达超时时间 {timeout} 秒")
        return False

    except Exception as e:
        logger.error(f"返回主界面时发生错误: {e}")
        return False


def _handle_return_identifiers(auto: Auto) -> bool:
    """处理返回主界面相关的标识（闪避标识/地图标识）"""
    dodge_pos = auto.check_element_exist("public/闪避标识", roi=roi_config.get_roi("dodge_indicator"))
    map_pos = auto.check_element_exist("public/地图标识", roi=roi_config.get_roi("map_indicator"))

    if dodge_pos or map_pos:
        auto.key_press("h")
        auto.sleep(2)
        return True
    else:
        auto.key_press("esc")
        auto.sleep(1)
        return False


def _handle_confirmation_dialogs(auto: Auto) -> bool:
    """处理确认对话框"""
    confirm_pos = auto.text_click("确认", roi=roi_config.get_roi("confirm_button_pvp"))
    if confirm_pos:
        auto.sleep(2)
        return True
    return False


def back_to_map(auto: Auto, timeout: int = 30) -> bool:
    """
    返回地图

    Args:
        auto: Auto控制实例
        timeout: 剩余超时时间(秒)
    Returns:
        bool: 是否成功返回地图
    """
    logger = auto.logger.create_task_logger("back_to_map")
    start_time = time.time()
    try:
        while True:
            if timeout > 0 and time.time() - start_time >= timeout:
                logger.warning(f"返回地图失败，已达超时时间 {timeout} 秒")
                return False

            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            dodge_pos = auto.check_element_exist("public/闪避标识", roi=roi_config.get_roi("dodge_indicator"))
            map_pos = auto.check_element_exist("public/地图标识", roi=roi_config.get_roi("map_indicator"))

            if dodge_pos or map_pos:
                logger.info("已在地图")
                return True
            auto.key_press("esc")
            auto.sleep(1)

            logger.debug("未检测到地图标识或地图按钮，重试")
    except Exception as e:
        logger.error(f"返回地图时发生错误: {e}")
        return False


def click_back(auto: Auto, timeout: int = 30) -> bool:
    """
    点击返回

    Args:
        auto: Auto控制实例
        timeout: 剩余超时时间(秒)

    Returns:
        bool: 是否成功点击返回
    """
    logger = auto.logger.create_task_logger("click_back")

    try:
        # 检查是否存在返回提示文本，允许重试3次
        if not auto.text_click("点击画面即可返回", click=False, roi=roi_config.get_roi("back_image_text"), retry=3):
            logger.debug("未检测到点击画面返回提示，任务已完成")
            return True

        # 使用带有验证的text_click，验证文本消失
        logger.info("尝试点击返回提示")
        if auto.text_click(
            "点击画面即可返回",
            roi=roi_config.get_roi("back_image_text"),
            verify={
                "type": "disappear",
                "target": "点击画面即可返回",
                "roi": roi_config.get_roi("back_image_text"),
            },
        ):
            logger.debug("点击画面返回成功")
            return True

        logger.warning(f"点击返回超时，已达超时时间 {timeout} 秒")
        return False

    except Exception as e:
        logger.error(f"点击返回时发生错误: {e}")
        return False


def enter_map_select(auto: Auto, timeout: int = 30, swipe_duration: int = 6, is_swipe: bool = True) -> bool:
    """
    进入地图选择

    Args:
        auto: Auto控制实例
        timeout: 剩余超时时间(秒)
        swipe_duration: 滑动持续时间

    Returns:
        bool: 是否成功进入地图选择
    """
    logger = auto.logger.create_task_logger("enter_map_select")

    try:
        # 检查是否已在地图选择界面
        if auto.text_click("游戏卡珍藏集", click=False, roi=roi_config.get_roi("game_collection_text")):
            logger.debug("已在地图选择界面")
            if is_swipe:
                logger.debug("执行滑动操作")
                auto.swipe((1800, 700), (1800, 900), duration=swipe_duration, steps=3, coord_type="BASE")
                auto.sleep(2)
            return True

        # 使用带有验证的click，验证进入地图选择界面
        logger.info("尝试点击地图选择按钮")
        if auto.click(
            (1720, 990),
            click_time=2,
            coord_type="BASE",
            verify={
                "type": "text",
                "target": "游戏卡珍藏集",
                "roi": roi_config.get_roi("game_collection_text"),
            },
        ):
            if is_swipe:
                logger.debug("执行滑动操作")
                auto.swipe((1800, 700), (1800, 900), duration=swipe_duration, steps=3, coord_type="BASE")
                auto.sleep(2)
            logger.debug("成功进入地图选择界面")
            return True

        logger.warning(f"进入地图选择超时，已达超时时间 {timeout} 秒")
        return False

    except Exception as e:
        logger.error(f"进入地图选择时发生错误: {e}")
        return False
