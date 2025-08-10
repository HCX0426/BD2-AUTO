import time
from auto_control.auto import Auto
from auto_tasks.pc.public import back_to_main, click_back


def pass_activity(auto: Auto, timeout: int = 600) -> bool:
    """活动关卡扫荡
    
    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)
        
    Returns:
        bool: 是否成功完成活动关卡扫荡
    """
    logger = auto.get_task_logger("pass_activity")
    logger.info("开始活动关卡扫荡流程")
    
    start_time = time.time()
    state = "init"  # 状态机: init -> entered -> challenge_selected -> quick_battle -> battle_confirmed -> returning
    
    try:
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            
            # 初始状态：进入活动界面
            if state == "init":
                if back_to_main(auto):
                    if pos := auto.check_element_exist("pass_activity/活动关入口"):
                        logger.info("进入活动关卡")
                        auto.click(pos)
                        auto.sleep(2)
                        state = "entered"
                    else:
                        logger.error("未找到活动关入口")
                        return False
                continue
                
            # 进入挑战战斗
            if state == "entered":
                if auto.text_click("挑战战斗"):
                    logger.info("进入挑战战斗界面")
                    state = "challenge_selected"
                continue
                
            # 选择困难第15关
            if state == "challenge_selected":
                # 检查是否仍在挑战战斗界面
                if auto.text_click("挑战战斗", click=False):
                    logger.info("仍在挑战战斗界面")
                    continue
                
                if pos := auto.check_element_exist("pass_activity/困难第15关"):
                    logger.info("选择困难第15关")
                    auto.click(pos, time=2)
                    auto.sleep(1)
                    
                    if auto.text_click("快速战斗"):
                        logger.info("进入快速战斗界面")
                        state = "quick_battle"
                continue
                
            # 快速战斗设置
            if state == "quick_battle":
                if pos := auto.text_click("MAX", click=False):
                    logger.info("设置MAX战斗次数")
                    auto.click(pos)
                    auto.sleep(1)
                    if pos := auto.check_element_exist("pass_activity/战斗"):
                        logger.info("开始战斗")
                        auto.click(pos)
                        auto.sleep(3)
                        state = "battle_confirmed"
                continue
                
            # 战斗确认后返回
            if state == "battle_confirmed":
                if click_back(auto):
                    logger.info("从战斗界面返回")
                    state = "returning"
                continue
                
            # 返回主界面
            if state == "returning":
                if back_to_main(auto):
                    logger.info("成功返回主界面")
                    return True
                
                logger.warning("返回主界面失败，重试中...")
                state = "init"  # 返回失败则重新开始流程
                continue
                
            auto.sleep(0.5)

        logger.error("活动关卡扫荡超时")
        return False
        
    except Exception as e:
        logger.error(f"活动关卡扫荡过程中出错: {e}")
        return False