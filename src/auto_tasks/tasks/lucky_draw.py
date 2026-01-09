"""抽抽乐模块

包含抽抽乐活动的抽奖功能
"""

import time

from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks.public import back_to_main, calculate_remaining_timeout


def lucky_draw(auto: Auto, timeout: int = 400, target_count: int = 7) -> bool:
    """抽抽乐

    Args:
        timeout: 任务超时时间(秒)
        target_count: 目标抽奖次数

    Returns:
        bool: 是否成功完成抽抽乐流程
    """
    try:
        logger = auto.get_task_logger("lucky_draw")
        logger.info("开始抽抽乐")
        start_time = time.time()

        # 使用任务链替代状态机
        chain = auto.chain()
        chain.set_total_timeout(timeout)

        # 1. 返回主界面
        remaining_timeout = calculate_remaining_timeout(timeout, start_time)
        chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

        # 2. 进入抽抽乐活动
        chain.then().text_click(
            "抽抽乐", 
            verify={"type": "text", "target": "免费1次"}
        )

        # 3. 循环执行抽奖操作
        def lucky_draw_loop() -> bool:
            """抽抽乐循环抽奖的自定义步骤"""
            completed_count = 0
            last_count = target_count
            
            while completed_count < target_count:
                if auto.check_should_stop():
                    logger.info("检测到停止信号，退出任务")
                    return True
                
                # 尝试点击免费1次
                if auto.text_click("免费1次", verify={"type": "exist", "target": "public/跳过"}):
                    logger.info("检测到免费1次")
                    auto.sleep(2)
                else:
                    # 滑动并点击抽奖
                    if last_count != target_count:
                        last_count = target_count
                        if auto.swipe((410, 410), (410, 203), duration=2, steps=2, coord_type="BASE"):
                            logger.info("滑动抽抽乐")
                            auto.sleep(2)
                    else:
                        if auto.swipe((410, 310), (410, 203), duration=1, steps=2, coord_type="BASE"):
                            logger.info("滑动抽抽乐")
                            auto.sleep(1)

                    # 多次点击抽奖位置
                    auto.click((410, 310), click_time=2, coord_type="BASE")
                    auto.click((410, 310), click_time=2, coord_type="BASE")
                    auto.sleep(1)
                    auto.click((410, 310), click_time=2, coord_type="BASE")
                    auto.sleep(1)
                    logger.info("点击抽抽乐")

                # 处理购买情况
                if auto.text_click(
                    "购买", click_time=2, verify={"type": "exist", "target": "public/跳过"}
                ):
                    logger.info("点击购买")
                    auto.sleep(2)

                # 跳过动画
                if auto.template_click(
                    "public/跳过", verify={"type": "exist", "target": "lucky_draw/抽完标识"}
                ):
                    logger.info("点击跳过")
                    auto.sleep(1)

                # 检查是否抽完一次
                if auto.wait_element("lucky_draw/抽完标识", wait_timeout=0):
                    logger.info("检测到抽完标识")
                    auto.sleep(1)
                    auto.key_press("esc")
                    auto.sleep(1)
                    completed_count += 1
                    logger.info(f"已完成第 {completed_count} 次抽奖")
                
                auto.sleep(0.5)  # 每次循环添加短暂延迟
            
            return True
        
        chain.then().custom_step(lucky_draw_loop, timeout=300)

        # 4. 返回主界面
        remaining_timeout = calculate_remaining_timeout(timeout, start_time)
        chain.then().custom_step(lambda: back_to_main(auto, remaining_timeout), timeout=remaining_timeout)

        # 执行任务链
        result = chain.execute()

        if result.success:
            total_time = round(result.elapsed_time, 2)
            minutes = int(total_time // 60)
            seconds = round(total_time % 60, 2)
            logger.info(f"抽抽乐完成，用时：{minutes}分{seconds}秒")
            return True
        else:
            logger.error(f"抽抽乐失败: {result.error_msg}")
            return False

    except Exception as e:
        logger.error(f"抽抽乐过程中出错: {e}")
        return False
