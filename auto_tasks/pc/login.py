import time

from auto_control.auto import Auto
from auto_control.logger import Logger


def login(auto: Auto):
    """登录到主界面"""
    try:
        logger = Logger("Login")
        logger.info("开始登录")
        start_time = time.time()
        timeout = 300  # 总超时5分钟

        while True:
            if time.time() - start_time > timeout:
                logger.error("登录超时（300秒），终止流程")
                return False

            pos = auto.add_check_element_exist_task("加载中").wait()
            if pos:
                logger.info("检测到加载中，等待加载完成")
                auto.add_sleep_task(2)
                continue
            pos = auto.add_check_element_exist_task("开始游戏").wait()
            if pos:
                logger.info("检测到开始游戏界面，点击开始游戏")
                auto.add_click_task(pos).wait()

            pos = auto.add_check_element_exist_task("地图标识").wait()
            if pos:
                logger.info("检测到地图标识，按H进入主界面")
                auto.add_key_task("h").wait()

                auto.add_sleep_task(2)

                # 弹窗处理循环
                popup_handled = False
                for _ in range(3):  # 最多处理3次弹窗
                    # 优先处理登录奖励
                    if reward_pos := auto.add_check_element_exist_task("登录奖励X2").wait(3):
                        logger.info("检测到登录奖励X2，点击关闭")
                        auto.add_click_task(reward_pos).wait()
                        popup_handled = True
                        continue

                    # 处理公告弹窗
                    if notice_pos := auto.add_check_element_exist_task("公告X2").wait(3):
                        logger.info("检测到公告X2，点击关闭")
                        auto.add_click_task(notice_pos).wait()
                        popup_handled = True
                        continue

                # 弹窗处理完成后添加短暂等待
                if popup_handled:
                    auto.add_wait_task(1).wait()

            # 主界面检测保持最后
            pos = auto.add_check_element_exist_task("主界面").wait()
            if pos:
                logger.info("检测到主界面，登录成功")
                return True
    except Exception as e:
        logger.error(f"登录过程中出错: {e}")
        return False
