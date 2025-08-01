import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main


def login(auto: Auto, timeout: int = 300):
    """登录到主界面"""
    try:
        logger = Logger("Login")
        logger.info("开始登录")
        start_time = time.time()
        first = True

        while time.time() - start_time < timeout:
            # 检查开始游戏按钮
            if auto.check_element_exist("login/开始游戏"):
                logger.info("检测到开始游戏界面，点击开始游戏")
                auto.template_click("login/开始游戏")
                auto.sleep(1)
                continue

            if first:
                # 回到主界面
                if back_to_main(auto):
                    logger.info("返回主界面成功")
                    first = False

                    for i in range(3):
                        # 处理弹窗
                        if auto.check_element_exist("login/登录奖励X"):
                            logger.info("检测到登录奖励X2，点击关闭")
                            auto.template_click("login/登录奖励X")
                            auto.sleep(1)
                            continue

                        if auto.check_element_exist("login/公告X"):
                            logger.info("检测到公告X2，点击关闭")
                            auto.template_click("login/公告X")
                            auto.sleep(1)
                            continue

                        # 短暂等待后继续检查
                        auto.sleep(0.5)
                if not first:
                    result = back_to_main(auto)
                    if result:
                        logger.info("返回主界面成功")
                        return True
            
        logger.error("登录超时")
        return False
        
    except Exception as e:
        logger.error(f"登录过程中出错: {e}")
        return False