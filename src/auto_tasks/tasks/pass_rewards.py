"""通行证奖励领取模块

包含通行证奖励的领取功能
"""
import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import (
                                      back_to_main,
                                      calculate_remaining_timeout, click_back)
from src.auto_tasks.utils.roi_config import roi_config


def pass_rewards(auto: Auto, timeout: int = 600) -> bool:
    """通行证奖励领取

    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)

    Returns:
        bool: 是否成功完成通行证奖励领取
    """
    logger = auto.get_task_logger("pass_rewards")
    logger.info("开始通行证奖励领取流程")

    start_time = time.time()

    # 奖励位置配置
    # 从roi_config获取奖励位置
    reward_positions = [
        roi_config.get_roi("pass_rewards_reward_pos_1", "pass_rewards")[:2],  # 只取(x, y)
        roi_config.get_roi("pass_rewards_reward_pos_2", "pass_rewards")[:2],
        roi_config.get_roi("pass_rewards_reward_pos_3", "pass_rewards")[:2],
        roi_config.get_roi("pass_rewards_reward_pos_4", "pass_rewards")[:2],
        roi_config.get_roi("pass_rewards_reward_pos_5", "pass_rewards")[:2],
        roi_config.get_roi("pass_rewards_reward_pos_6", "pass_rewards")[:2],
    ]

    # 使用任务链替代状态机
    chain = auto.chain()
    chain.set_total_timeout(timeout)

    # 1. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 2. 进入通行证界面
    chain.then().template_click(
        "pass_rewards/通行证标识",
        verify={"type": "text", "target": "基础", "roi": (1235, 300, 69, 37)},
    )

    # 3. 领取所有奖励
    def collect_rewards_step() -> bool:
        """领取所有通行证奖励的自定义步骤"""
        for i, (x, y) in enumerate(reward_positions):
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            
            logger.info(f"点击第{i+1}个奖励")
            
            # 点击奖励位置
            if auto.click(
                (x, y),
                click_time=2,
                coord_type="BASE",
                verify={"type": "exist", "target": "public/返回键1"},
            ):
                auto.sleep(1.5)
                
                # 点击领取按钮位置
                if auto.click(
                    (1590, 680),
                    click_time=2,
                    coord_type="BASE",
                    verify={"type": "text", "target": "全部获得", "roi": (1390, 750, 100, 30)},
                ):
                    if auto.text_click(
                        "全部获得",
                        roi=(1390, 750, 100, 30),
                        verify={"type": "exist", "target": "pass_rewards/通行证标识"},
                    ):
                        logger.info(f"领取第{i+1}个奖励")
                    else:
                        logger.warning(f"领取第{i+1}个奖励失败")
                        click_back(auto, remaining_timeout)
            else:
                logger.warning(f"点击第{i+1}个奖励位置失败")
        return True
    
    chain.then().custom_step(collect_rewards_step)

    # 4. 返回主界面
    remaining_timeout = calculate_remaining_timeout(timeout, start_time)
    chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

    # 执行任务链
    result = chain.execute()

    if result.success:
        total_time = round(result.elapsed_time, 2)
        minutes = int(total_time // 60)
        seconds = round(total_time % 60, 2)
        logger.info(f"通行证奖励领取完成，用时：{minutes}分{seconds}秒")
        return True
    else:
        logger.error(f"通行证奖励领取失败: {result.error_msg}")
        return False