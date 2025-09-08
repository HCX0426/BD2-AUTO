import time
from auto_control import Auto
from auto_tasks.pc.public import back_to_main, enter_map_select


def map_collection(auto: Auto, timeout: int = 600) -> bool:
    """地图奖励收集
    
    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)
        
    Returns:
        bool: 是否成功完成地图奖励收集
    """
    logger = auto.get_task_logger("get_map_collection")
    logger.info("开始地图奖励收集流程")
    
    start_time = time.time()
    state = "init"  # 状态机: init -> chapter_selected -> exploring -> collecting -> completing
    
    # 收集状态
    materials_collected = False
    gold_collected = False
    collect_attempts = 0
    max_attempts = 3  # 最大尝试次数

    try:
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            
            # 初始状态：进入地图选择
            if state == "init":
                if back_to_main(auto) and enter_map_select(auto):
                    logger.info("成功进入地图选择界面")
                    state = "chapter_selecting"
                continue
                
            # 选择章节
            if state == "chapter_selecting":
                # 尝试找到第七章地图
                if pos := auto.check_element_exist("map_collection/第七章1"):
                    logger.info("进入第七章1")
                    auto.click(pos)
                elif pos := auto.check_element_exist("map_collection/第七章2"):
                    logger.info("进入第七章2")
                    auto.click(pos)
                else:
                    # 滑动地图寻找第七章
                    logger.info("滑动寻找第七章")
                    auto.swipe((1666, 266), (833, 266), duration=5, steps=4,is_base_coord=True)
                    auto.sleep(2)
                    continue
                
                auto.sleep(5)
                state = "chapter_selected"
                continue
                
            # 章节已选择状态
            if state == "chapter_selected":
                if pos := auto.check_element_exist("map_collection/探寻"):
                    logger.info("开始探寻")
                    auto.click(pos, click_time=2)
                    auto.sleep(5)
                    state = "exploring"
                continue
                
            # 探索中状态
            if state == "exploring":
                # 收集材料
                if not materials_collected:
                    if pos := auto.check_element_exist("map_collection/材料吸收"):
                        logger.info("收集材料")
                        auto.click(pos, click_time=2)
                        collect_attempts += 1
                        
                        if auto.check_element_exist("map_collection/吸收材料完成"):
                            logger.info("材料收集完成")
                            materials_collected = True
                            auto.sleep(2)
                
                # 收集金币
                if not gold_collected:
                    if pos := auto.check_element_exist("map_collection/金币吸收"):
                        logger.info("收集金币")
                        auto.click(pos, click_time=2)
                        collect_attempts += 1
                        
                        if auto.check_element_exist("map_collection/金币吸收完成"):
                            logger.info("金币收集完成")
                            gold_collected = True
                            auto.sleep(2)
                
                # 检查是否完成或达到最大尝试次数
                if (materials_collected and gold_collected) or collect_attempts >= max_attempts * 2:
                    state = "completing"
                continue
                
            # 完成状态
            if state == "completing":
                if back_to_main(auto):
                    logger.info("成功返回主界面")
                    return True
                
                logger.warning("返回主界面失败，重试中...")
                state = "init"  # 返回失败则重新开始流程
                continue
                
            auto.sleep(0.5)

        logger.error("地图奖励收集超时")
        return False
        
    except Exception as e:
        logger.error(f"地图奖励收集过程中出错: {e}")
        return False