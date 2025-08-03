import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, enter_map_select


def get_map_collection(auto: Auto, timeout: int = 600):
    """获取地图奖励"""
    try:
        logger = Logger("get_map_collection")
        logger.info("开始获取地图奖励")
        start_time = time.time()
        first = True
        second = False

        flag1 = False
        flag2 = False

        count1 = 0
        count2 = 0
        
        while time.time() - start_time < timeout:
            # 检测是否在主界面
            if first:
                if back_to_main(auto):
                    result = enter_map_select(auto)
                    if result:
                        pos = auto.check_element_exist("map_collection/第七章1")
                        pos1 = auto.check_element_exist("map_collection/第七章2")
                        if pos:
                            logger.info("点击第七章1")
                            auto.click(pos)
                            auto.sleep(5)
                            first = False
                        elif pos1:
                            logger.info("点击第七章2")
                            auto.click(pos1)
                            auto.sleep(5)
                            first = False
                    else:
                        if auto.swipe((1666, 266), (833, 266), duration=8, steps=6):
                            logger.info("向右滑动")
                            auto.sleep(2)

                        pos = auto.check_element_exist("map_collection/第七章1")
                        pos1 = auto.check_element_exist("map_collection/第七章2")
                        if pos:
                            logger.info("点击第七章1")
                            auto.click(pos)
                            auto.sleep(5)
                            first = False
                        elif pos1:
                            logger.info("点击第七章2")
                            auto.click(pos1)
                            auto.sleep(5)
                            first = False

            if not first:
                pos = auto.check_element_exist("map_collection/探寻")
                if pos:
                    logger.info("点击探寻")
                    auto.click(pos,time=2)
                    auto.sleep(5)
                    second = True
                
                if second:
                    if not flag1:
                        pos = auto.check_element_exist("map_collection/材料吸收")
                        if pos:
                            logger.info("点击材料吸收")
                            auto.click(pos,time=2)
                            count1 += 1

                            pos = auto.check_element_exist("map_collection/吸收材料完成")
                            if pos:
                                logger.info("检测到吸收材料完成")
                                auto.sleep(2)
                                flag1 = True
                    
                    if not flag2:
                        pos = auto.check_element_exist("map_collection/金币吸收")
                        if pos:
                            logger.info("点击金币吸收")
                            auto.click(pos,time=2)
                            count2 += 1

                        pos = auto.check_element_exist("map_collection/金币吸收完成")
                        if pos:
                            logger.info("检测到金币吸收完成")
                            auto.sleep(2)
                            flag2 = True

                    if (flag1 and flag2) or (count1 >= 3 and count2 >= 3):
                        logger.info("地图收集完成")
                        
                        result = back_to_main(auto)
                        if result:
                            logger.info("返回主界面成功")
                            return True
                        else:
                            logger.error("返回主界面失败")
                            return False
            auto.sleep(0.5)  # 每次循环添加短暂延迟

        logger.info("地图收集超时")
        return False
    except Exception as e:
        logger.error(f"地图收集过程中出错: {e}")
        return False