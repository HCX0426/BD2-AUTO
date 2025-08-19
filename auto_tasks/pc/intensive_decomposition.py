import time
from auto_control import Auto
from auto_tasks.pc.public import back_to_main, click_back


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
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            
            # 分解阶段
            if phase == "decomposition":
                if state == "init":
                    if back_to_main(auto):
                        if auto.text_click("背包"):
                            logger.info("成功打开背包")
                            auto.sleep(3)
                            state = "bag_opened"
                    continue
                
                if state == "bag_opened":
                    if pos := auto.check_element_exist("intensive_decomposition/装备标识"):
                        logger.info("进入装备界面")
                        auto.click(pos, time=2)
                        auto.sleep(3)
                        state = "filter_set"
                    else:
                        logger.error("装备标识不存在")
                        if auto.text_click("背包",click=False):
                            logger.error("未进入背包界面")
                            state = "init"
                    continue
                
                if state == "filter_set":
                    if pos := auto.check_element_exist("intensive_decomposition/筛选标识"):
                        logger.info("打开筛选界面")
                        auto.click(pos)
                        auto.sleep(2)
                        if pos := auto.check_element_exist("intensive_decomposition/R"):
                            auto.click(pos)
                            logger.info("选择R装备")
                            auto.sleep(2)
                            if auto.text_click("确认",time=3):
                                logger.info("确认筛选条件")
                                auto.sleep(3)
                                state = "confirm"
                    continue
                
                if state == "confirm":
                    if auto.text_click("一键分解"):
                        logger.info("执行一键分解")
                        auto.sleep(2)
                        if auto.click((785, 200)):  # 选择装备位置
                            auto.sleep(1)
                    if pos := auto.check_element_exist("intensive_decomposition/确认"):
                        auto.click(pos)
                        auto.sleep(2)
                        if pos := auto.check_element_exist("intensive_decomposition/分解按钮"):
                            auto.click(pos)
                            logger.info("确认分解")
                            auto.sleep(3)
                            state = "complete"
                        else:
                            logger.error("分解按钮不存在")
                    continue
                
                if state == "complete":
                    if click_back(auto):
                        logger.info("返回装备界面")
                        auto.sleep(2)
                        if back_to_main(auto):
                            logger.info("成功返回主界面，进入强化阶段")
                            phase = "enhancement"
                            state = "init"
                    continue
            
            # 强化阶段
            elif phase == "enhancement":
                if state == "init":
                    if back_to_main(auto):
                        if auto.text_click("背包"):
                            logger.info("成功打开背包")
                            auto.sleep(3)
                            state = "bag_opened"
                    continue
                
                if state == "bag_opened":
                    if pos := auto.check_element_exist("intensive_decomposition/装备标识"):
                        logger.info("进入装备界面")
                        auto.click(pos, time=2)
                        auto.sleep(3)
                        state = "filter_set"
                    continue
                
                if state == "filter_set":
                    if pos := auto.check_element_exist("intensive_decomposition/筛选标识"):
                        logger.info("打开筛选界面")
                        auto.click(pos)
                        auto.sleep(1)
                        if pos := auto.check_element_exist("intensive_decomposition/UR"):
                            auto.click(pos)
                            auto.sleep(1)
                            if pos := auto.check_element_exist("intensive_decomposition/满等级"):
                                auto.click(pos)
                                auto.sleep(1)
                                if pos := auto.check_element_exist("intensive_decomposition/制作"):
                                    auto.click(pos)
                                    auto.sleep(1)
                                    if auto.text_click("确认",time=3):
                                        auto.sleep(1)
                                        state = "confirm"
                    continue
                
                if state == "confirm":
                    if auto.click((785, 200)):  # 选择装备位置
                        logger.info("选择装备")
                        auto.sleep(1)
                        if auto.text_click("精炼",time=3):
                            logger.info("进入精炼界面")
                            auto.sleep(2)
                    if auto.text_click("连续精炼"):
                        logger.info("进入连续精炼界面")
                        state = "execute"
                    continue
                
                if state == "execute":
                    if auto.text_click("连续精炼"):
                        logger.info("开始连续精炼")
                        auto.sleep(1)
                        if pos := auto.check_element_exist("intensive_decomposition/加十"):
                            auto.click(pos)
                            auto.sleep(1)
                            if pos := auto.check_element_exist("intensive_decomposition/精炼"):
                                auto.click(pos)
                                auto.sleep(1)
                        if pos := auto.check_element_exist("public/跳过"):
                            auto.click(pos)
                            auto.sleep(5)
                        if auto.text_click("确认"):
                            auto.sleep(2)
                            state = "complete"
                    continue
                
                if state == "complete":
                    if back_to_main(auto):
                        logger.info("强化完成，返回主界面")
                        return True
                    continue
            
            auto.sleep(0.5)

        logger.error("强化分解流程超时")
        return False
        
    except Exception as e:
        logger.error(f"强化分解过程中出错: {e}")
        return False