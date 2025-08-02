import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, enter_map_select


def get_pvp(auto: Auto, timeout: int = 600):
    """获取PVP奖励"""
    try:
        logger = Logger("get_pvp")
        logger.info("开始获取PVP奖励")
        start_time = time.time()
        first = True
        second = True

        while time.time() - start_time < timeout:
            # 检测是否在主界面
            if first:
                if back_to_main(auto):
                    result = enter_map_select(auto)
                    if result:
                        pos = auto.check_element_exist("get_pvp/pvp地图")
                        pos1 = auto.check_element_exist("get_pvp/pvp地图2")
                        if pos:
                            logger.info("点击PVP地图")
                            auto.click(pos)
                            auto.sleep(5)
                            first = False
                        elif pos1:
                            logger.info("点击PVP地图2")
                            auto.click(pos1)
                            auto.sleep(5)
                            first = False
                    else:
                        logger.error("进入地图选择失败")
            if not first:
                    if auto.template_click("get_pvp/进入竞技场"):
                        logger.info("点击进入竞技场")
                        auto.sleep(3)
                        if auto.template_click("get_pvp/自动战斗"):
                            logger.info("点击自动战斗")
                            auto.sleep(1)
                            if auto.text_click("MAX"):
                                logger.info("点击MAX")
                                auto.sleep(1)
                                pos = auto.check_element_exist("get_pvp/选项完成")
                                if pos:
                                    logger.info("进入战斗")
                                    auto.click(pos)
                                    auto.sleep(1)
                                    second = False

            
                    if not second:
                        pos = auto.check_element_exist("get_pvp/选项完成")
                        if pos:
                            second = True
                            continue
                    pos = auto.text_click("反复战斗结果",click=False)
                    if pos:
                        pos = auto.check_element_exist("get_pvp/X")
                        if pos:
                            logger.info("点击关闭")
                            auto.sleep(1)
                    pos = auto.check_element_exist("get_pvp/离开")
                    if pos:
                        logger.info("点击离开")
                        auto.click(pos)
                        auto.sleep(1)

                        result = back_to_main(auto)
                        if result:
                            logger.info("返回主界面成功")
                            return True
                        else:
                            logger.error("返回主界面失败")
            auto.sleep(0.5)  # 每次循环添加短暂延迟

        logger.info("领取公会奖励超时")
        return False
    except Exception as e:
        logger.error(f"领取公会奖励过程中出错: {e}")
        return False