import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.pc.public import back_to_main, click_back


def sweep_daily(auto: Auto, timeout: int = 600, onigiri: str = "第九关", torch: str = "火之洞穴"):
    """每日扫荡
    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)
        onigiri: 饭团使用(仅支持第七关、第九关)
        torch: 火炬使用
    Returns:
        bool: 是否成功扫荡
    """

    logger = auto.get_task_logger("sweep_daily")
    logger.info("开始每日扫荡")

    start_time = time.time()
    state = {
        "main_checked": False,
        "sweep_entered": False,
        "onigiri_selected": False,
        "onigiri_completed": False,
        "torch_selected": False,
    }

    try:
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            # 检查主界面
            if not state["main_checked"]:
                if back_to_main(auto):
                    logger.info("成功返回主界面")
                    state["main_checked"] = True
                continue

            # 进入扫荡界面
            if not state["sweep_entered"]:
                logger.info("开始检测扫荡标识")
                if pos := auto.text_click("快速狩猎", click=False, roi=(1713, 278, 100, 44)):
                    logger.info("检测到快速狩猎标识")
                    auto.click(pos, click_time=3, coord_type="PHYSICAL")
                    auto.sleep(5)
                    if auto.text_click("野猪洞穴", click=False):
                        logger.info("进入到扫荡界面")
                        auto.sleep(1)
                        state["sweep_entered"] = True
                continue

            # 处理饭团扫荡
            if not state["onigiri_completed"]:
                if not state["onigiri_selected"]:
                    if pos := auto.check_element_exist(f"sweep_daily/{onigiri}"):
                        logger.info(f"检测到{onigiri}")
                        auto.click(pos)
                        auto.sleep(1)
                        if auto.check_element_exist(f"sweep_daily/{onigiri}产出"):
                            if auto.template_click("sweep_daily/快速狩猎"):
                                logger.info("点击快速狩猎")
                                auto.sleep(1)
                                state["onigiri_selected"] = True
                    continue

                if pos := auto.text_click("MAX", click_time=3):
                    auto.click(pos)
                    if pos := auto.check_element_exist("sweep_daily/狩猎按钮"):
                        logger.info("点击狩猎按钮")
                        auto.click(pos)
                        auto.sleep(3)
                        if not click_back(auto):
                            auto.text_click("取消")
                            logger.info("米饭已用完")
                        state["onigiri_completed"] = True
                else:
                    state["onigiri_selected"] = False
                continue

            # 处理火把扫荡
            if not state["torch_selected"]:
                if pos := auto.check_element_exist("sweep_daily/天赋本"):
                    logger.info("点击天赋本")
                    auto.click(pos)
                    auto.sleep(1)
                    if auto.text_click(f"{torch}"):
                        if auto.template_click("sweep_daily/快速狩猎"):
                            logger.info(f"点击快速狩猎")
                            auto.sleep(1)
                            state["torch_selected"] = True
                    else:
                        logger.info(f"未检测到{torch}")
                continue

            if pos := auto.text_click("MAX", click_time=3):
                auto.click(pos)
                if pos := auto.check_element_exist("sweep_daily/狩猎按钮"):
                    logger.info("点击狩猎按钮")
                    auto.click(pos)
                    auto.sleep(3)
                    if not click_back(auto):
                        auto.text_click("取消")
                        logger.info("火把已用完")

                    if back_to_main(auto):
                        logger.info("返回主界面")
                        return True
                    logger.info("未返回主界面")
                    return False
            else:
                state["torch_selected"] = False

            auto.sleep(0.5)

        logger.info("扫荡完成")
        return True

    except Exception as e:
        logger.error(f"扫荡过程中出错: {e}")
        return False
