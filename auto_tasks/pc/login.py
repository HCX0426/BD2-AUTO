import sys
import time
from auto_control.auto import Auto
from auto_control.logger import Logger


def login(auto: Auto):
    logger = Logger("Login")
    logger.info("开始登录")
    while True:
        # 检查是否加载中
        pos = auto.add_check_element_exist_task("加载中").wait()
        if pos:
            print("检测到加载中，等待加载完成")
            time.sleep(5)
            continue

        pos = auto.add_check_element_exist_task("开始游戏").wait()
        if pos:
            print("检测到开始游戏界面，点击开始游戏")
            auto.add_template_click_task("开始游戏").wait()
        else:
            # 检查是否在主界面
            pos = auto.add_check_element_exist_task("主界面").wait()
            if pos:
                print("检测到主界面，登录成功")
            else:
                # 检查图钉
                print("未检测到开始游戏或主界面，按H键尝试进入主界面")
                auto.add_key_task('h').wait()
        
        pos = auto.add_template_click_task("活动").wait()
        if pos:
            print(f"点击位置: {pos}")
            return True


