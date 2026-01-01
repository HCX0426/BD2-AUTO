"""每日扫荡模块

包含每日快速狩猎的扫荡功能，包括饭团和火炬的使用
"""
import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import (
                                      back_to_main,
                                      calculate_remaining_timeout, click_back)


def sweep_daily(auto: Auto, timeout: int = 600, onigiri: str = "第九关", torch: str = "火之洞穴") -> bool:
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
        while True:
            if timeout > 0 and time.time() - start_time >= timeout:
                logger.error("任务执行超时")
                return False
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            remaining_timeout = calculate_remaining_timeout(timeout, start_time)
            
            # 检查主界面
            if not state["main_checked"]:
                if back_to_main(auto, remaining_timeout):
                    logger.info("成功返回主界面")
                    state["main_checked"] = True
                continue

            # 进入扫荡界面
            if not state["sweep_entered"]:
                logger.info("开始检测扫荡标识")
                if auto.text_click(
                    "快速狩猎",
                    roi=(1713, 278, 100, 44),
                    click_time=3,
                    coord_type="PHYSICAL",
                    verify={"type": "text", "target": "野猪洞穴", "timeout": 5},
                    retry=2,
                    delay=1
                ):
                    logger.info("检测到快速狩猎标识")
                    state["sweep_entered"] = True
                continue

            # 处理饭团扫荡
            if not state["onigiri_completed"]:
                if not state["onigiri_selected"]:
                    if auto.template_click(
                        f"sweep_daily/{onigiri}",
                        verify={"type": "exist", "target": f"sweep_daily/{onigiri}产出", "timeout": 5},
                        retry=1
                    ):
                        logger.info("检测到%s", onigiri)
                        if auto.template_click(
                            "sweep_daily/快速狩猎",
                            verify={"type": "text", "target": "MAX", "timeout": 5},
                            retry=1
                        ):
                            logger.info("点击快速狩猎")
                            state["onigiri_selected"] = True
                else:
                    if pos := auto.text_click("MAX", click=False):
                        logger.info("点击MAX")
                        auto.click(pos, click_time=3)
                        auto.sleep(1)
                        if auto.template_click(
                            "sweep_daily/狩猎按钮",
                            verify={"type": "exist", "target": "public/返回键1", "timeout": 10},
                            retry=1
                        ):
                            logger.info("点击狩猎按钮")
                            remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                            if not click_back(auto, remaining_timeout):
                                auto.text_click("取消")
                                logger.info("米饭已用完")
                            state["onigiri_completed"] = True
                    else:
                        state["onigiri_selected"] = False
                continue

            # 处理火把扫荡
            if not state["torch_selected"]:
                if auto.template_click(
                    "sweep_daily/天赋本",
                    verify={"type": "text", "target": torch, "timeout": 5},
                    retry=1
                ):
                    logger.info("点击天赋本")
                    if auto.text_click(
                        f"{torch}",
                        verify={"type": "text", "target": "快速狩猎", "timeout": 5},
                        retry=1
                    ):
                        if auto.template_click(
                            "sweep_daily/快速狩猎",
                            verify={"type": "text", "target": "MAX", "timeout": 5},
                            retry=1
                        ):
                            logger.info(f"点击快速狩猎")
                            state["torch_selected"] = True
                continue

            if pos := auto.text_click("MAX", click=False):
                logger.info("点击MAX")
                auto.click(pos, click_time=3)
                if auto.template_click(
                    "sweep_daily/狩猎按钮",
                    verify={"type": "exist", "target": "public/返回键1", "timeout": 10},
                    retry=1
                ):
                    logger.info("点击狩猎按钮")
                    auto.sleep(3)
                    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                    if not click_back(auto, remaining_timeout):
                        auto.text_click("取消")
                        logger.info("火把已用完")

                    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                    if back_to_main(auto, remaining_timeout):
                        total_time = round(time.time() - start_time, 2)
                        minutes = int(total_time // 60)
                        seconds = round(total_time % 60, 2)
                        logger.info(f"每日扫荡完成，用时：{minutes}分{seconds}秒")
                        return True
                    logger.info("未返回主界面")
                    return False
            else:
                state["torch_selected"] = False

            auto.sleep(0.5)

    except Exception as e:
        logger.error(f"扫荡过程中出错: {e}")
        return False