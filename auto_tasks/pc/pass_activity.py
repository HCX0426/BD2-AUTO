import time
from auto_control import Auto
from auto_tasks.pc.public import back_to_main, click_back


def pass_activity(auto: Auto, timeout: int = 600, level_name: str = "第15关") -> bool:
    """活动关卡扫荡
    
    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)
        level_name: 活动关卡名称
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
                if auto.text_click("挑战战斗",time=3):
                    logger.info("进入挑战战斗界面")
                    state = "challenge_selected"
                continue
                
            # 选择困难第15关
            if state == "challenge_selected":
                # 检查是否仍在挑战战斗界面
                if auto.text_click("行程", click=False):
                    logger.info("仍在挑战战斗界面")
                    state == "entered"
                    continue
                
                if pos := auto.check_element_exist(f"pass_activity/{level_name}"):
                    logger.info(f"选择{level_name}")
                    auto.click(pos, time=2)
                    auto.sleep(1)
                    
                    if pos := auto.text_click("快速战斗",click=False):
                        logger.info("进入快速战斗界面")
                        auto.click(pos)
                        auto.sleep(1)
                        state = "quick_battle"
                    else:
                        logger.error("未找到快速战斗按钮,跳过")
                        state = "battle_confirmed"

                continue
                
            # 快速战斗设置
            if state == "quick_battle":
                if pos := auto.text_click("MAX", click=False):
                    logger.info("设置MAX战斗次数")
                    auto.click(pos,time=2)
                    auto.sleep(1)
                    if auto.template_click("pass_activity/战斗",time=2):
                        logger.info("开始战斗")
                        auto.sleep(3)
                        state = "battle_confirmed"
                elif pos := auto.text_click("补充",click=False):
                    logger.info("AP不足")
                    if auto.text_click("取消",time=2):
                        logger.info("取消补充AP")
                        state = "battle_confirmed"
                continue
                
            # 战斗确认后返回
            if state == "battle_confirmed":
                if click_back(auto):
                    logger.info("从战斗界面返回")
                auto.key_press("esc")
                
                # 检查是否在挑战战斗界面
                if auto.text_click("行程", click=False):
                    logger.info("已在挑战战斗界面")
                    state = "boss"
                continue

            if state == "boss":
                if auto.text_click("魔物追踪者",time=2):
                    logger.info("进入魔物追踪者界面")
                    auto.sleep(2)
                if auto.text_click("快速战斗"):
                    logger.info("点击快速战斗")
                    auto.sleep(1)
                    if pos := auto.text_click("确认",click=False):
                        logger.info("确认战斗")
                        auto.click(pos,time=2)
                        auto.sleep(3)
                    else:
                        logger.error("无法点击确认")
                        state = "returning"
                else:
                    logger.info("未找到快速战斗按钮,跳过")
                    state = "returning"

                    # if auto.text_click("去战斗"):
                    #     logger.info("点击去战斗")
                    #     auto.sleep(6)
                    #     if auto.text_click("切换视角",click=False):
                    #         logger.info("切换视角")
                    #         auto.sleep(1)
                    #         if auto.template_click("public/开关"):
                    #             logger.info("自动战斗")
                    #             auto.sleep(10)
                    #             state = "back"

                if click_back(auto):
                    logger.info("领取奖励")
                    state = "returning"
                continue


            if state == "back":
                if auto.text_click("返回",time=2):
                    logger.info("返回魔兽界面")
                    state = "returning"
                
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