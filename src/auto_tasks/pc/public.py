import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.utils.roi_config import roi_config


def back_to_main(auto: Auto, max_attempts: int = 5) -> bool:
    """
    返回主界面

    Args:
        auto: Auto控制实例
        max_attempts: 最大尝试次数

    Returns:
        bool: 是否成功返回主界面
    """
    logger = auto.get_task_logger("back_to_main")
    attempt = 0

    try:
        while attempt < max_attempts:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            auto.sleep(2)
            # 检查是否已在主界面
            if auto.check_element_exist("public/主界面", roi=roi_config.get_roi("main_menu")):
                logger.debug("已在主界面")
                return True

            if _handle_confirmation_dialogs(auto):
                continue

            if _handle_return_identifiers(auto):
                continue

            # 检查返回是否成功
            if auto.check_element_exist("public/主界面", roi=roi_config.get_roi("main_menu")):
                return True

            # 备用返回方式
            auto.template_click(["public/返回键1", "public/返回键2"], roi=roi_config.get_roi("back_button"))

            if auto.check_element_exist("public/主界面", roi=roi_config.get_roi("main_menu")):
                return True

            end_game_pos = auto.text_click("结束游戏", click=False, roi=roi_config.get_roi("end_game_text"))
            if end_game_pos:
                auto.key_press("esc")
                auto.sleep(1)
                auto.key_press("h")
                auto.sleep(3)
                # 检查返回是否成功
                if auto.check_element_exist("public/主界面", roi=roi_config.get_roi("main_menu")):
                    return True

            attempt += 1
            auto.sleep(1)

        logger.warning(f"返回主界面失败，已达最大尝试次数 {max_attempts}")
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
        timeout: 超时时间(秒)
    Returns:
        bool: 是否成功返回地图
    """
    logger = auto.get_task_logger("back_to_map")
    start_time = time.time()
    try:
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            dodge_pos = auto.check_element_exist("public/闪避标识", roi=roi_config.get_roi("dodge_indicator"))
            map_pos = auto.check_element_exist("public/地图标识", roi=roi_config.get_roi("map_indicator"))

            if dodge_pos or map_pos:
                logger.info("已在地图")
                return True
            else:
                auto.key_press("esc")

            logger.debug("未检测到地图标识或地图按钮")
            return False
    except Exception as e:
        logger.error(f"返回地图时发生错误: {e}")
        return False


def click_back(auto: Auto) -> bool:
    """
    点击返回

    Args:
        auto: Auto控制实例

    Returns:
        bool: 是否成功点击返回
    """
    logger = auto.get_task_logger("click_back")

    try:
        state = None
        if auto.text_click("点击画面即可返回", roi=roi_config.get_roi("back_image_text")):
            logger.debug("点击画面返回成功")
            auto.sleep(1)
            state = "OK"

        if state == "OK":
            if not auto.text_click("点击画面即可返回", click=False, roi=roi_config.get_roi("back_image_text")):
                return True

        logger.debug("未检测到点击画面返回提示")
        return False
    except Exception as e:
        logger.error(f"点击返回时发生错误: {e}")
        return False


def enter_map_select(auto: Auto, swipe_duration: int = 6, is_swipe: bool = True) -> bool:
    """
    进入地图选择

    Args:
        auto: Auto控制实例
        swipe_duration: 滑动持续时间

    Returns:
        bool: 是否成功进入地图选择
    """
    logger = auto.get_task_logger("enter_map_select")

    try:
        if not auto.click((1720, 990), click_time=2, coord_type="BASE"):
            logger.warning("点击地图选择按钮失败")
            return False

        auto.sleep(2)

        if auto.text_click("游戏卡珍藏集", click=False, roi=roi_config.get_roi("game_collection_text")):
            if is_swipe:
                logger.debug("执行滑动操作")
                if auto.swipe((1800, 700), (1800, 900), duration=swipe_duration, steps=3, coord_type="BASE"):
                    auto.sleep(2)
            logger.debug("检测到游戏卡珍藏集")
            return True
        else:
            logger.warning("未检测到游戏卡珍藏集")
            return False

        return True

    except Exception as e:
        logger.error(f"进入地图选择时发生错误: {e}")
        return False
