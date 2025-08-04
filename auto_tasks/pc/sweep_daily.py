import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, click_back


def sweep_daily(auto: Auto, timeout: int = 600, onigiri: str = '第九关', torch: str = '火之洞穴'):
    """每日扫荡"""
    try:
        logger = Logger("sweep_daily")
        logger.info("开始每日扫荡")
        start_time = time.time()
        first = True
        second = True
        third = True
        fourth = True
        fifth = True
        sixth = True

        while time.time() - start_time < timeout:
            # 检测是否在主界面
            if first:
                if back_to_main(auto):
                    auto.key_press('esc')
                    auto.sleep(1)
                    pos = auto.check_element_exist("public/地图标识")
                    if pos:
                        logger.info("检测到地图标识")
                        first = False

            if not first and second:
                pos = auto.check_element_exist("sweep_daily/扫荡标识")
                if pos:
                    logger.info("检测到扫荡标识")
                    auto.click(pos)
                    auto.sleep(5)
                    pos = auto.check_element_exist("sweep_daily/快速狩猎")
                    if pos:
                        logger.info("进入到扫荡界面")
                        auto.sleep(1)
                        second = False
            
            if not second and third:
                # 饭团使用
                pos = auto.check_element_exist(f"sweep_daily/{onigiri}")
                if pos:
                    logger.info(f"检测到{onigiri}")
                    auto.click(pos)
                    auto.sleep(1)
                    pos = auto.check_element_exist(f"sweep_daily/{onigiri}产出")
                    if pos:
                        if auto.template_click("sweep_daily/快速狩猎"):
                            logger.info("点击快速狩猎")
                            auto.sleep(1)
                            third = False
            
            if not third and fourth:
                if auto.text_click("MAX"):
                    pos = auto.check_element_exist("sweep_daily/狩猎按钮")
                    if pos:
                        logger.info("点击狩猎按钮")
                        auto.click(pos)
                        auto.sleep(3)
                        if click_back(auto):
                            logger.info("点击返回")
                        else:
                            auto.text_click("取消")
                            logger.info("米饭已用完")

                        fourth = False
            
            if not fourth and fifth:
                # 使用火把
                pos = auto.check_element_exist("sweep_daily/天赋本")
                if pos:
                    logger.info("点击天赋本")
                    auto.click(pos)
                    auto.sleep(1)
                    pos = auto.text_click(f"{torch}")
                    if pos:
                        logger.info(f"点击{torch}")
                        if auto.template_click("sweep_daily/快速狩猎"):
                            logger.info("点击快速狩猎")
                            auto.sleep(1)
                            fifth = False
                    else:
                        logger.info(f"未检测到{torch}")
            if not fifth and sixth:
                if auto.text_click("MAX"):
                    pos = auto.check_element_exist("sweep_daily/狩猎按钮")
                    if pos:
                        logger.info("点击狩猎按钮")
                        auto.click(pos)
                        auto.sleep(3)

                        if click_back(auto):
                            logger.info("点击返回")
                        else:
                            auto.text_click("取消")
                            logger.info("火把已用完")
                        
                        if back_to_main(auto):
                            logger.info("返回主界面")
                            return True
                        else:
                            logger.info("未返回主界面")
                            return False
            auto.sleep(0.5)  # 每次循环添加短暂延迟

        logger.info("扫荡完成")
        return True
    except Exception as e:
        logger.error(f"扫荡过程中出错: {e}")
        return False
