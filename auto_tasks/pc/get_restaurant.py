import time
from auto_control import Auto
from auto_tasks.pc.public import back_to_main, click_back


def get_restaurant(auto: Auto, timeout: int = 600) -> bool:
    """餐厅领取奖励
    Args:
        auto: Auto控制对象
        timeout: 超时时间(秒)
    Returns:
        bool: 是否成功领取奖励
    """

    logger = auto.get_task_logger("get_restaurant")
    logger.info("开始领取餐厅奖励")
    start_time = time.time()
    
    # 状态定义
    state = "first"  # first -> second -> third -> fourth
    
    try:
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            
            if state == "first":
                if back_to_main(auto):
                    if auto.template_click("get_restaurant/餐馆标识"):
                        logger.info("点击餐馆标识")
                        auto.sleep(1)
                        state = "second"
                        continue
            
            elif state == "second":
                if auto.text_click("结算"):
                    logger.info("点击结算")
                    auto.sleep(3)
                    if click_back(auto):
                        logger.info("领取成功")
                    else:
                        logger.info("无需结算")
                    state = "third"
                    continue
                else:
                    logger.info("未检测到结算按钮")
                    state = "first"  # 回到初始状态
                    continue
            
            elif state == "third":
                if pos := auto.check_element_exist("get_restaurant/进入餐厅"):
                    logger.info("点击进入餐厅")
                    auto.click(pos, click_time=2)
                    auto.sleep(3)
                    state = "fourth"
                    continue
                if pos := auto.check_element_exist("get_restaurant/餐馆标识"):
                    logger.info("点击餐馆标识")
                    auto.click(pos)
                    auto.sleep(1)

            elif state == "fourth":
                if pos := auto.text_click("点击画面关闭",click=False):
                    logger.info("点击画面关闭")
                    auto.click(pos,click_time=2)
                    continue
                
                if click_back(auto):
                    logger.info("点击返回")
                    auto.sleep(1)
                    continue
                
                if pos_1 := auto.text_click("常客",click=False):
                    if pos := auto.check_element_exist("get_restaurant/下一阶段"):
                        logger.info("点击下一阶段")
                        auto.click(pos, click_time=2)
                        auto.sleep(1)
                        continue
                    
                    if pos := auto.check_element_exist("get_restaurant/升级"):
                        logger.info("点击升级")
                        auto.click(pos, click_time=2)
                        auto.sleep(1)
                        continue

                    logger.info("点击常客")
                    auto.click(pos_1,click_time=2)
                    return back_to_main(auto)
            
            auto.sleep(0.5)

        logger.info("餐厅奖励领取超时")
        return False
        
    except Exception as e:
        logger.error(f"餐厅奖励领取出错: {e}")
        return False