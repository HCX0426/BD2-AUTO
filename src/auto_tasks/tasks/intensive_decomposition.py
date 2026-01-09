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

    # 使用任务链替代状态机
    chain = auto.chain()
    chain.set_total_timeout(timeout)

    remaining_timeout = calculate_remaining_timeout(timeout, start_time)

    # ===========================================
    # 分解阶段 (decomposition phase)
    # ===========================================
    
    # 1. 返回主界面
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 2. 打开背包
    chain.then().text_click(
        "背包", 
        click_time=2, 
        roi=roi_config.get_roi("backpack_button", "intensive_decomposition"),
        verify={"type": "exist", "target": "intensive_decomposition/装备标识"},
    )

    # 3. 进入装备界面
    chain.then().template_click(
        "intensive_decomposition/装备标识",
        roi=roi_config.get_roi("equipment_icon", "intensive_decomposition"),
        click_time=2,
        verify={"type": "exist", "target": "intensive_decomposition/筛选标识"},
    )

    # 4. 打开筛选界面并选择R装备
    chain.then().template_click(
        "intensive_decomposition/筛选标识",
        roi=roi_config.get_roi("filter_icon", "intensive_decomposition"),
        verify={"type": "exist", "target": "intensive_decomposition/R"},
    )

    # 5. 选择R装备
    chain.then().template_click(
        "intensive_decomposition/R",
        verify={"type": "text", "target": "确认"},
    )

    # 6. 确认筛选条件
    chain.then().text_click(
        "确认", 
        click_time=3,
        verify={"type": "text", "target": "一键分解"},
    )

    # 7. 执行一键分解
    chain.then().text_click(
        "一键分解", 
        roi=roi_config.get_roi("one_click_decompose", "intensive_decomposition"),
        verify={"type": "exist", "target": "intensive_decomposition/确认"},
    )

    # 8. 选择装备位置
    chain.then().click((785, 200), coord_type="BASE")

    # 9. 确认分解
    chain.then().template_click(
        "intensive_decomposition/确认",
        roi=roi_config.get_roi("confirm_button", "intensive_decomposition"),
        verify={"type": "exist", "target": "intensive_decomposition/分解按钮"},
    )

    # 10. 执行分解
    chain.then().template_click(
        "intensive_decomposition/分解按钮",
        roi=roi_config.get_roi("decompose_button", "intensive_decomposition"),
        verify={"type": "exist", "target": "intensive_decomposition/装备标识"},
    )

    # ===========================================
    # 强化阶段 (enhancement phase)
    # ===========================================
    
    # 11. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 12. 打开背包
    chain.then().text_click(
        "背包", 
        click_time=2, 
        roi=roi_config.get_roi("backpack_button", "intensive_decomposition"),
        verify={"type": "exist", "target": "intensive_decomposition/装备标识"},
    )

    # 13. 进入装备界面
    chain.then().template_click(
        "intensive_decomposition/装备标识",
        roi=roi_config.get_roi("equipment_icon", "intensive_decomposition"),
        click_time=2,
        verify={"type": "exist", "target": "intensive_decomposition/筛选标识"},
    )

    # 14. 打开筛选界面
    chain.then().template_click(
        "intensive_decomposition/筛选标识",
        roi=roi_config.get_roi("filter_icon", "intensive_decomposition"),
        verify={"type": "exist", "target": "intensive_decomposition/18加"},
    )

    # 15. 选择18加装备
    chain.then().template_click(
        "intensive_decomposition/18加",
        verify={"type": "exist", "target": "intensive_decomposition/制作"},
    )

    # 16. 点击制作
    chain.then().template_click(
        "intensive_decomposition/制作",
        verify={"type": "text", "target": "确认"},
    )

    # 17. 确认筛选条件
    chain.then().text_click(
        "确认", 
        click_time=3,
        verify={"type": "text", "target": "精炼"},
    )

    # 18. 选择装备并进入精炼界面
    def select_equipment_step() -> bool:
        """选择装备并进入精炼界面的自定义步骤"""
        if auto.click((785, 200), coord_type="BASE"):  # 选择装备位置
            logger.info("选择装备")
            auto.sleep(1)
            return auto.text_click(
                "精炼", 
                click_time=3,
                verify={"type": "text", "target": "连续精炼"},
            )
        return False
    chain.then().custom_step(select_equipment_step)

    # 19. 进入连续精炼界面
    chain.then().text_click(
        "连续精炼",
        verify={"type": "exist", "target": "intensive_decomposition/加十"},
    )

    # 20. 执行连续精炼
    def execute_enhancement_step() -> bool:
        """执行连续精炼的自定义步骤"""
        if auto.text_click("连续精炼", click=False):
            logger.info("开始连续精炼")
            auto.sleep(3)
            # 点击加十
            auto.template_click(
                "intensive_decomposition/加十",
                verify={"type": "exist", "target": "intensive_decomposition/精炼"},
            )
            auto.sleep(1)
            # 点击精炼
            auto.template_click(
                "intensive_decomposition/精炼",
                click_time=2,
                verify={"type": "exist", "target": "public/跳过"},
            )
            auto.sleep(1)
            # 点击跳过
            auto.template_click(
                "public/跳过",
                click_time=2,
                verify={"type": "text", "target": "确认"},
            )
            auto.sleep(5)
        # 确认精炼完成
        if auto.text_click("确认", click=False):
            logger.info("确认精炼完成")
            auto.click((1100, 500), click_time=2, coord_type="BASE")
        return True
    chain.then().custom_step(execute_enhancement_step)

    # 21. 返回并退出
    def return_and_exit_step() -> bool:
        """返回并退出的自定义步骤"""
        click_back(auto, remaining_timeout)
        logger.info("从战斗界面返回")
        auto.key_press("esc")
        return back_to_main(auto, remaining_timeout)
    chain.then().custom_step(return_and_exit_step, timeout=remaining_timeout)

    # 执行任务链
    result = chain.execute()

    if result.success:
        total_time = round(result.elapsed_time, 2)
        minutes = int(total_time // 60)
        seconds = round(total_time % 60, 2)
        logger.info(f"强化分解完成，用时：{minutes}分{seconds}秒")
        return True
    else:
        logger.error(f"强化分解失败: {result.error_msg}")
        return False