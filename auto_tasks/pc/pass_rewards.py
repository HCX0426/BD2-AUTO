import time
from auto_control import Auto
from auto_tasks.pc.public import back_to_main, click_back


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
    state = "init"  # 状态机: init -> entered -> collecting -> completing
    
    # 奖励位置配置
    reward_positions = [
        (420, 330),  # 第一个奖励位置
        (420, 430),  # 第二个奖励位置
        (420, 530),  # 第三个奖励位置
        # (420, 630)   # 第四个奖励位置
    ]
    current_reward = 0
    
    try:
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            
            # 初始状态：进入通行证界面
            if state == "init":
                if back_to_main(auto):
                    if pos := auto.check_element_exist("pass_rewards/通行证标识"):
                        if auto.click(pos):
                            logger.info("进入通行证界面")
                            auto.sleep(2)

                            # 检测是否进入成功
                            if auto.text_click("基础",click=False,roi=(1235,300,69,37)):
                                logger.info("已进入通行证界面")
                                state = "entered"
                            else:
                                logger.error("未成功进入通行证界面")
                continue
                
            # 领取奖励状态
            if state == "entered":
                if current_reward < len(reward_positions):
                    x, y = reward_positions[current_reward]
                    
                    # 点击奖励位置
                    if auto.click((x, y), click_time=2):
                        auto.click((x, y))
                        auto.click((x, y))
                        # 点击领取按钮位置
                        if auto.click((1590, 680),click_time=2,is_base_coord=True):
                            if auto.text_click("全部获得",roi=(1390,750,100,30)):
                                logger.info(f"领取第{current_reward+1}个奖励")
                                auto.sleep(3)
                                
                                if click_back(auto):
                                    logger.info("返回通行证界面")
                                    current_reward += 1
                                else:
                                    current_reward += 1
                                    logger.warning("无奖励可领取,下一个奖励")

                else:
                    state = "completing"
                continue
                
            # 完成状态：返回主界面
            if state == "completing":
                if back_to_main(auto):
                    logger.info("成功返回主界面")
                    return True
                
                logger.warning("返回主界面失败，重试中...")
                state = "init"  # 返回失败则重新开始流程
                continue
                
            auto.sleep(0.5)

        logger.error("通行证奖励领取超时")
        return False
        
    except Exception as e:
        logger.error(f"通行证奖励领取过程中出错: {e}")
        return False