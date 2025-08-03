import time
from auto_control.auto import Auto
from auto_control.logger import Logger
# 公共方法

# 回到主界面
def back_to_main(auto: Auto):
    """
    回到主界面
    :param auto: Auto实例
    :return: 是否成功
    """
    try:
        while True:
            logger = Logger("back_to_main")
            # 检测是否在主界面
            if auto.check_element_exist("public/主界面"):
                logger.info("检测到主界面，无需返回")
                auto.sleep(1)
                return True
            else:
                # 检测地图标识
                if auto.check_element_exist("public/地图标识"):
                    auto.key_press("h")
                    auto.sleep(1)
                else:
                    logger.info("未检测到地图标识")
                    auto.key_press("esc")

                    # 防止esc失效
                    if not auto.check_element_exist("public/主界面"):
                        pos = auto.check_element_exist("public/返回键1")
                        if pos:
                            auto.click(pos)
                            auto.sleep(2)
                        pos = auto.check_element_exist("public/返回键2")
                        if pos:
                            auto.click(pos)
                            auto.sleep(2)
                        auto.text_click("取消")
                    auto.sleep(1)

    except Exception as e:
        logger.error(f"返回主界面失败: {e}")
        return False


# 等待加载
def wait_load(auto: Auto):
    """
    等待加载
    :param auto: Auto实例
    :return: 是否成功
    """
    logger = Logger("wait_load")
    try:
        if auto.check_element_exist("public/加载中"):
            logger.info("检测到加载中，等待加载完成")
            auto.sleep(6)
            return True
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
    :return: 是否成功
    """
    logger = Logger("click_back")
    try:
        if auto.text_click("点击画面即可返回"):
            logger.info("点击画面即可返回")
            auto.sleep(2)
            return True
        else:
            logger.info("未检测到点击画面即可返回")
            return False
    except Exception as e:
        logger.error(f"点击画面即可返回失败: {e}")
        return False
    


# 进入地图选择
def enter_map_select(auto: Auto):
    """
    进入地图选择
    :param auto: Auto实例
    :return: 是否成功
    """
    logger = Logger("enter_map_select")
    try:
        if auto.click((1720,990)):
            logger.info("点击地图选择")
            auto.sleep(3)
            if auto.text_click("游戏卡珍藏集",click=False):
                logger.info("检测到游戏卡珍藏集")
                if auto.swipe((1800, 700), (1800, 900), duration=6, steps=4):
                    logger.info("滑动回原位")
                    auto.sleep(2)
                return True
            else:
                logger.info("未检测到游戏卡珍藏集")
                return False
    except Exception as e:
        logger.error(f"进入地图选择失败: {e}")
        return False