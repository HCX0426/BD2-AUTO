import time
from auto_control import Auto

def back_to_main(auto: Auto, max_attempts: int = 5) -> bool:
    """
    返回主界面
    
    Args:
        auto: Auto控制实例
        max_attempts: 最大尝试次数
        
    Returns:
        bool: 是否成功返回主界面
    """
    logger = auto.get_task_logger("back_to_main")
    attempt = 0
    
    try:
        while attempt < max_attempts:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True

            auto.sleep(2)    
            # 检查是否已在主界面
            if auto.check_element_exist("public/主界面"):
                logger.debug("已在主界面")
                return True
                
            # 尝试通过多种方式返回
            if _handle_return_identifiers(auto):
                continue
                
            if _handle_confirmation_dialogs(auto):
                continue
            
            # 检查返回是否成功
            if auto.check_element_exist("public/主界面"):
                return True
                
            # 备用返回方式
            _try_alternative_back_methods(auto)

            end_game_pos = auto.text_click("结束游戏", click=False)
            if end_game_pos:
                cancel_pos = auto.text_click("取消", click=False)
                if cancel_pos:
                    auto.click(cancel_pos)
                    auto.sleep(1)
                    auto.key_press("h")
                    auto.sleep(2)
                    # 检查返回是否成功
                    if auto.check_element_exist("public/主界面"):
                        return True
            
            attempt += 1
            auto.sleep(1)
            
        logger.warning(f"返回主界面失败，已达最大尝试次数 {max_attempts}")
        return False
        
    except Exception as e:
        logger.error(f"返回主界面时发生错误: {e}")
        return False

def _handle_return_identifiers(auto: Auto) -> bool:
    """处理返回主界面相关的标识（闪避标识/地图标识）"""
    dodge_pos = auto.check_element_exist("public/闪避标识")
    map_pos = auto.check_element_exist("public/地图标识")
    
    if dodge_pos or map_pos:
        if daily_pos := auto.check_element_exist("public/每日收集"):
            auto.key_press("a",1)
            auto.click(daily_pos)
            auto.sleep(1)
        auto.key_press("h")
        auto.sleep(1)
        return True
    else:
        auto.key_press("esc")
        auto.sleep(1)
        return False

def _handle_confirmation_dialogs(auto: Auto) -> bool:
    """处理确认对话框"""
    confirm_pos = auto.text_click("确认", click=False)
    end_game_pos = auto.text_click("结束游戏", click=False)
    if confirm_pos and not end_game_pos:
        auto.click(confirm_pos)
        auto.sleep(1)
        return True
    return False

def _try_alternative_back_methods(auto: Auto):
    """尝试备用返回方式"""
    back_btn1 = auto.check_element_exist("public/返回键1")
    back_btn2 = auto.check_element_exist("public/返回键2")
    
    if back_btn1:
        auto.click(back_btn1)
    elif back_btn2:
        auto.click(back_btn2)
        

def back_to_map(auto: Auto, timeout: int = 30) -> bool:
    """
    返回地图
    
    Args:
        auto: Auto控制实例
        timeout: 超时时间(秒)
    Returns:
        bool: 是否成功返回地图
    """
    logger = auto.get_task_logger("back_to_map")
    start_time = time.time()
    try:
        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            
            dodge_pos = auto.check_element_exist("public/闪避标识")
            map_pos = auto.check_element_exist("public/地图标识")

            if dodge_pos or map_pos:
                logger.info("已在地图")
                return True
            else:
                auto.key_press("esc")
                
            logger.debug("未检测到地图标识或地图按钮")
            return False
    except Exception as e:
        logger.error(f"返回地图时发生错误: {e}")
        return False


def wait_load(auto: Auto, timeout: int = 10) -> bool:
    """
    等待加载
    
    Args:
        auto: Auto控制实例
        timeout: 超时时间(秒)
        
    Returns:
        bool: 是否加载完成
    """
    logger = auto.get_task_logger("wait_load")
    start_time = time.time()
    
    try:
        while time.time() - start_time < timeout:
            if not auto.check_element_exist("public/加载中"):
                logger.debug("加载完成")
                return True
            auto.sleep(1)
            
        logger.warning(f"等待加载超时 ({timeout}秒)")
        return False
    except Exception as e:
        logger.error(f"等待加载时发生错误: {e}")
        return False

def click_back(auto: Auto) -> bool:
    """
    点击返回
    
    Args:
        auto: Auto控制实例
        
    Returns:
        bool: 是否成功点击返回
    """
    logger = auto.get_task_logger("click_back")
    
    try:
        state = None
        if auto.text_click("点击画面即可返回"):
            logger.debug("点击画面返回成功")
            auto.sleep(1)
            state = "OK"

        if state == "OK":
           if not auto.text_click("点击画面即可返回",click=False):
               return True
            
        logger.debug("未检测到点击画面返回提示")
        return False
    except Exception as e:
        logger.error(f"点击返回时发生错误: {e}")
        return False

def enter_map_select(auto: Auto, swipe_duration: int = 6) -> bool:
    """
    进入地图选择
    
    Args:
        auto: Auto控制实例
        swipe_duration: 滑动持续时间
        
    Returns:
        bool: 是否成功进入地图选择
    """
    logger = auto.get_task_logger("enter_map_select")
    
    try:
        if not auto.click((1720, 990), click_time=2, is_base_coord=True):
            logger.warning("点击地图选择按钮失败")
            return False
            
        auto.sleep(3)
        
        if auto.text_click("游戏卡珍藏集", click=False):
            logger.debug("检测到游戏卡珍藏集，执行滑动操作")
            if auto.swipe((1800, 700), (1800, 900), duration=swipe_duration, steps=4, is_base_coord=True):
                auto.sleep(2)
                return True
        else:
            logger.warning("未检测到游戏卡珍藏集")
            return False
            
    except Exception as e:
        logger.error(f"进入地图选择时发生错误: {e}")
        return False