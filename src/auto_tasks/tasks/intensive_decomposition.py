"""装备强化分解模块

包含装备的强化和分解功能
"""
import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import (
                                      back_to_main,
                                      calculate_remaining_timeout, click_back)
from src.auto_tasks.utils.roi_config import roi_config


def intensive_decomposition(auto: Auto, timeout: int = 600) -> bool:
    """装备强化分解

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)

    Returns:
        bool: 是否成功完成强化分解流程
    """
    logger = auto.get_task_logger("intensive_decomposition")
    logger.info("开始装备强化分解流程")

    start_time = time.time()
    phase = "decomposition"  # decomposition | enhancement
    state = "init"  # 状态机: init -> bag_opened -> filter_set -> confirm -> execute -> complete

    try:
        while True:
            if timeout > 0 and time.time() - start_time >= timeout:
                logger.error("任务执行超时")
                return False
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            remaining_timeout = calculate_remaining_timeout(timeout, start_time)
            
            # 分解阶段
            if phase == "decomposition":
                if state == "init":
                    if back_to_main(auto, remaining_timeout):
                        if auto.text_click(
                            "背包", 
                            click_time=2, 
                            roi=roi_config.get_roi("backpack_button", "intensive_decomposition"),
                            verify={"type": "exist", "target": "intensive_decomposition/装备标识"},
                        ):
                            logger.info("打开背包")
                            auto.sleep(3)
                            state = "bag_opened"
                    continue

                if state == "bag_opened":
                    if auto.template_click(
                        "intensive_decomposition/装备标识",
                        roi=roi_config.get_roi("equipment_icon", "intensive_decomposition"),
                        click_time=2,
                        verify={"type": "exist", "target": "intensive_decomposition/筛选标识"},
                    ):
                        logger.info("进入装备界面")
                        state = "filter_set"
                    continue

                if state == "filter_set":
                    if auto.template_click(
                        "intensive_decomposition/筛选标识",
                        roi=roi_config.get_roi("filter_icon", "intensive_decomposition"),
                        verify={"type": "exist", "target": "intensive_decomposition/R"},
                    ):
                        logger.info("打开筛选界面")
                        auto.sleep(2)
                        if auto.template_click(
                            "intensive_decomposition/R",
                            verify={"type": "text", "target": "确认"},
                        ):
                            logger.info("选择R装备")
                            auto.sleep(2)
                            if auto.text_click(
                                "确认", 
                                click_time=3,
                                verify={"type": "text", "target": "一键分解"},
                            ):
                                logger.info("确认筛选条件")
                                auto.sleep(3)
                                state = "confirm"
                    else:
                        logger.error("筛选标识不存在")
                        state = "bag_opened"
                    continue

                if state == "confirm":
                    if auto.text_click(
                        "一键分解", 
                        roi=roi_config.get_roi("one_click_decompose", "intensive_decomposition"),
                        verify={"type": "exist", "target": "intensive_decomposition/确认"},
                    ):
                        logger.info("执行一键分解")
                        auto.sleep(2)
                        if auto.click((785, 200), coord_type="BASE"):  # 选择装备位置
                            auto.sleep(1)
                    if auto.template_click(
                        "intensive_decomposition/确认",
                        roi=roi_config.get_roi("confirm_button", "intensive_decomposition"),
                        verify={"type": "exist", "target": "intensive_decomposition/分解按钮"},
                    ):
                        auto.sleep(2)
                        if auto.template_click(
                            "intensive_decomposition/分解按钮",
                            roi=roi_config.get_roi("decompose_button", "intensive_decomposition"),
                            verify={"type": "exist", "target": "intensive_decomposition/装备标识"},
                        ):
                            logger.info("确认分解")
                            auto.sleep(3)
                            phase = "enhancement"
                            state = "init"
                        else:
                            logger.error("分解按钮不存在")
                    continue

            # 强化阶段
            elif phase == "enhancement":
                if state == "init":
                    if back_to_main(auto, remaining_timeout):
                        if auto.text_click(
                            "背包", 
                            click_time=2, 
                            roi=roi_config.get_roi("backpack_button", "intensive_decomposition"),
                            verify={"type": "exist", "target": "intensive_decomposition/装备标识"},
                        ):
                            logger.info("打开背包")
                            auto.sleep(3)
                            state = "bag_opened"
                    continue

                if state == "bag_opened":
                    if auto.template_click(
                        "intensive_decomposition/装备标识",
                        roi=roi_config.get_roi("equipment_icon", "intensive_decomposition"),
                        click_time=2,
                        verify={"type": "exist", "target": "intensive_decomposition/筛选标识"},
                    ):
                        logger.info("进入装备界面")
                        state = "filter_set"
                    else:
                        logger.error("未进入背包界面")
                        state = "init"
                    continue

                if state == "filter_set":
                    if auto.template_click(
                        "intensive_decomposition/筛选标识",
                        roi=roi_config.get_roi("filter_icon", "intensive_decomposition"),
                        verify={"type": "exist", "target": "intensive_decomposition/18加"},
                    ):
                        logger.info("打开筛选界面")
                        auto.sleep(1)
                        if auto.template_click(
                            "intensive_decomposition/18加",
                            verify={"type": "exist", "target": "intensive_decomposition/制作"},
                        ):
                            auto.sleep(1)
                            if auto.template_click(
                                "intensive_decomposition/制作",
                                verify={"type": "text", "target": "确认"},
                            ):
                                auto.sleep(1)
                                if auto.text_click(
                                    "确认", 
                                    click_time=3,
                                    verify={"type": "text", "target": "精炼"},
                                ):
                                    auto.sleep(1)
                                    state = "confirm"
                    continue

                if state == "confirm":
                    if auto.click((785, 200), coord_type="BASE"):  # 选择装备位置
                        logger.info("选择装备")
                        auto.sleep(1)
                        if auto.text_click(
                            "精炼", 
                            click_time=3,
                            verify={"type": "text", "target": "连续精炼"},
                        ):
                            logger.info("进入精炼界面")
                            auto.sleep(2)
                    if auto.text_click(
                        "连续精炼",
                        verify={"type": "exist", "target": "intensive_decomposition/加十"},
                    ):
                        logger.info("进入连续精炼界面")
                        state = "execute"
                    continue

                if state == "execute":
                    if auto.text_click("连续精炼", click=False):
                        logger.info("开始连续精炼")
                        auto.sleep(3)
                        if auto.template_click(
                            "intensive_decomposition/加十",
                            verify={"type": "exist", "target": "intensive_decomposition/精炼"},
                        ):
                            auto.sleep(1)
                            if auto.template_click(
                                "intensive_decomposition/精炼",
                                click_time=2,
                                verify={"type": "exist", "target": "public/跳过"},
                            ):
                                auto.sleep(1)
                        if auto.template_click(
                            "public/跳过",
                            click_time=2,
                            verify={"type": "text", "target": "确认"},
                        ):
                            auto.sleep(5)
                    if auto.text_click("确认", click=False):
                        logger.info("确认精炼完成")
                        auto.click((1100, 500), click_time=2, coord_type="BASE")
                        state = "complete"
                    continue

                if state == "complete":
                    if click_back(auto, remaining_timeout):
                        logger.info("从战斗界面返回")
                    auto.key_press("esc")
                    
                    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
                    if back_to_main(auto, remaining_timeout):
                        total_time = round(time.time() - start_time, 2)
                        minutes = int(total_time // 60)
                        seconds = round(total_time % 60, 2)
                        logger.info(f"强化分解完成，用时：{minutes}分{seconds}秒")
                        return True
                    return False

            auto.sleep(0.5)

    except Exception as e:
        logger.error(f"强化分解过程中出错: {e}")
        return False