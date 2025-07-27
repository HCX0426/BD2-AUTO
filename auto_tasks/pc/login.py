import time

from auto_control.auto import Auto
from auto_control.logger import Logger


def login(auto: Auto):
    """登录到主界面"""
    logger = Logger("Login")
    logger.info("开始登录")
    while True:
        pos = auto.add_check_element_exist_task("加载中").wait()
        if pos:
            logger.info("检测到加载中，等待加载完成")
            time.sleep(5)
            continue
        pos = auto.add_check_element_exist_task("开始游戏").wait()
        if pos:
            logger.info("检测到开始游戏界面，点击开始游戏")
            auto.add_click_task(pos).wait()
        
        pos = auto.add_check_element_exist_task("地图标识").wait()
        if pos:
            logger.info("检测到地图标识，按H进去主界面")
            auto.add_key_task("h").wait()
        
        pos = auto.add_check_element_exist_task("主界面").wait()
        if pos:
            logger.info("检测到主界面，登录成功")
            return True
