import time
from auto_control.auto import Auto
from auto_control.logger import Logger
# 公共方法

# 回到主界面
def back_to_main(auto: Auto):
    """
    回到主界面
    :param auto: Auto实例
    :param timeout: 超时时间
    :return:
    """
    try:
        logger = Logger("back_to_main")
        # 检测是否在主界面
        pos = auto.add_check_element_exist_task("public/主界面")
        if pos:
            logger.info("检测到主界面，无需返回")
            auto.add_sleep_task(1)
            return True
        else:
            # 检测地图标识
            pos = auto.add_check_element_exist_task("public/地图标识")
            if pos:
                auto.add_key_task("h")
                auto.add_sleep_task(1)
            else:
                logger.info("未检测到已知界面")
                auto.add_key_task("esc")
                auto.add_sleep_task(1)

                # 检查是否出现结束游戏弹窗
                pos = auto.add_text_click_task("结束游戏",click=False)
                if pos:
                    logger.info("检测到结束游戏弹窗")
                    auto.add_key_task("esc")
                    auto.add_sleep_task(1)
                    if auto.add_check_element_exist_task("public/地图标识"):
                        logger.info("检测到地图标识，返回主界面")
                        auto.add_key_task("h")
                        auto.add_sleep_task(1)
    except Exception as e:
        logger.error(f"返回主界面失败: {e}")
        return False


# 等待加载
def wait_load(auto: Auto):
    """
    等待加载
    :param auto: Auto实例
    :param timeout: 超时时间
    :return:
    """
    logger = Logger("wait_load")
    try:
        pos = auto.add_check_element_exist_task("public/加载中")
        if pos:
            logger.info("检测到加载中，等待加载完成")
            auto.add_sleep_task(6)
        else:
            logger.info("未检测到加载中")
            return True
    except Exception as e:
        logger.error(f"等待加载失败: {e}")
        return False

# 点击画面即可返回
def click_back(auto: Auto):
    """
    点击画面即可返回
    :param auto: Auto实例
    :return:
    """
    logger = Logger("click_back")
    try:
        pos = auto.add_text_click_task("点击画面即可返回")
        if pos:
            logger.info("点击画面即可返回")
            auto.add_sleep_task(2)
            return True
        else:
            logger.info("未检测到点击画面即可返回")
            return False
    except Exception as e:
        logger.error(f"点击画面即可返回失败: {e}")
        return False