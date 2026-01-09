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

    # 使用任务链替代状态机
    chain = auto.chain()
    chain.set_total_timeout(timeout)

    # 1. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 2. 进入扫荡界面
    chain.then().text_click(
        "快速狩猎",
        roi=(1713, 278, 100, 44),
        click_time=3,
        coord_type="PHYSICAL",
        verify={"type": "text", "target": "野猪洞穴"},
    )

    # 3. 饭团扫荡 - 选择关卡
    chain.then().template_click(
        f"sweep_daily/{onigiri}",
        verify={"type": "exist", "target": f"sweep_daily/{onigiri}产出"},
    )

    # 4. 饭团扫荡 - 点击快速狩猎
    chain.then().template_click(
        "sweep_daily/快速狩猎",
        verify={"type": "text", "target": "MAX"},
    )

    # 5. 饭团扫荡 - 设置MAX次数并开始狩猎
    def onigiri_hunt_step() -> bool:
        """饭团扫荡的自定义步骤"""
        if pos := auto.text_click("MAX", click=False):
            logger.info("点击MAX")
            auto.click(pos, click_time=3)
            auto.sleep(1)
            if auto.template_click(
                "sweep_daily/狩猎按钮",
                verify={"type": "exist", "target": "public/返回键1"},
            ):
                logger.info("点击狩猎按钮")
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if not click_back(auto, remaining_timeout):
                    auto.text_click("取消")
                    logger.info("米饭已用完")
                return True
        return False
    chain.then().custom_step(onigiri_hunt_step)

    # 6. 火把扫荡 - 点击天赋本
    chain.then().template_click(
        "sweep_daily/天赋本",
        verify={"type": "text", "target": torch},
    )

    # 7. 火把扫荡 - 选择火把关卡
    chain.then().text_click(
        f"{torch}",
        verify={"type": "text", "target": "快速狩猎"},
    )

    # 8. 火把扫荡 - 点击快速狩猎
    chain.then().template_click(
        "sweep_daily/快速狩猎",
        verify={"type": "text", "target": "MAX"},
    )

    # 9. 火把扫荡 - 设置MAX次数并开始狩猎
    def torch_hunt_step() -> bool:
        """火把扫荡的自定义步骤"""
        if pos := auto.text_click("MAX", click=False):
            logger.info("点击MAX")
            auto.click(pos, click_time=3)
            if auto.template_click(
                "sweep_daily/狩猎按钮",
                verify={"type": "exist", "target": "public/返回键1"},
            ):
                logger.info("点击狩猎按钮")
                auto.sleep(3)
                remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                if not click_back(auto, remaining_timeout):
                    auto.text_click("取消")
                    logger.info("火把已用完")
                return True
        return False
    chain.then().custom_step(torch_hunt_step)

    # 10. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 执行任务链
    result = chain.execute()

    if result.success:
        total_time = round(result.elapsed_time, 2)
        minutes = int(total_time // 60)
        seconds = round(total_time % 60, 2)
        logger.info(f"每日扫荡完成，用时：{minutes}分{seconds}秒")
        return True
    else:
        logger.error(f"每日扫荡失败: {result.error_msg}")
        return False