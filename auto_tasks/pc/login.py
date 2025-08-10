import time
from auto_control import Auto
from auto_tasks.pc.public import back_to_main


def login(auto: Auto, timeout: int = 300) -> bool:
    """登录
    
    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)
        
    Returns:
        bool: 是否成功登录并返回主界面
    """
    logger = auto.get_task_logger("Login")
    logger.info("开始登录流程")
    
    start_time = time.time()
    state = "start_screen"  # 状态机: start_screen -> main_check -> popup_handling -> completed
    
    try:
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            
            # 处理开始游戏界面
            if state == "start_screen":
                if auto.check_element_exist("login/开始游戏"):
                    logger.info("检测到开始游戏按钮，点击进入")
                    auto.template_click("login/开始游戏")
                    auto.sleep(7)
                state = "main_check"
                continue
                
            # 检查主界面状态
            if state == "main_check":
                if back_to_main(auto):
                    logger.info("成功进入主界面")
                    state = "popup_handling"
                continue
                
            # 处理各种弹窗
            if state == "popup_handling":
                popup_handled = False
                
                # 检查并关闭各种弹窗
                if auto.check_element_exist("login/登录奖励X"):
                    logger.info("关闭登录奖励弹窗")
                    auto.template_click("login/登录奖励X")
                    popup_handled = True
                    
                if auto.check_element_exist("login/公告X"):
                    logger.info("关闭公告弹窗")
                    auto.template_click("login/公告X")
                    popup_handled = True
                    
                # 每日收集处理
                if auto.check_element_exist("public/每日收集"):
                    logger.info("处理每日收集")
                    auto.template_click("public/每日收集")
                    popup_handled = True
                
                if popup_handled:
                    auto.sleep(1)
                    continue
                
                # 没有弹窗需要处理，确认主界面状态
                if back_to_main(auto):
                    logger.info("所有弹窗处理完成，返回主界面成功")
                    return True
                
                logger.warning("弹窗处理后未能确认主界面状态")
                state = "main_check"
                continue
                
            auto.sleep(0.5)

        logger.error("登录流程超时")
        return False
        
    except Exception as e:
        logger.error(f"登录过程中发生错误: {e}")
        return False