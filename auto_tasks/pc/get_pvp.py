import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, click_back, enter_map_select


def get_pvp(auto: Auto, timeout: int = 600):
    """获取PVP奖励"""
    try:
        logger = auto.get_task_logger("get_pvp")
        logger.info("开始获取PVP奖励")
        start_time = time.time()
        first = True
        second = True
        third = True
        fourth = True

        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
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
            if not first and second:
                pos = auto.check_element_exist("get_pvp/进入竞技场")
                if pos:
                    logger.info("点击进入竞技场")
                    auto.click(pos)
                    auto.sleep(5)
                pos = auto.text_click("确定", click=False)
                if pos:
                    logger.info("点击确定")
                    auto.click(pos)
                    auto.sleep(1)

                if pos := auto.check_element_exist("get_pvp/自动战斗"):
                    logger.info("点击自动战斗")
                    auto.click(pos)
                    auto.sleep(1)
                if pos := auto.text_click("MAX",click=False):
                    logger.info("点击MAX")
                    auto.click(pos)
                    auto.sleep(1)
                    pos = auto.check_element_exist("get_pvp/选项完成")
                    if pos:
                        logger.info("进入战斗")
                        auto.click(pos)
                        auto.sleep(10)
                        second = False

            if not second and third:
                pos = auto.check_element_exist("get_pvp/选项完成")
                if pos:
                    second = True
                    continue
                pos = auto.text_click("反复战斗结果", click=False)
                if pos:
                    pos = auto.check_element_exist("get_pvp/X")
                    if pos:
                        logger.info("点击关闭")
                        auto.sleep(1)
                if pos := auto.text_click("离开", click=False):
                    logger.info("点击离开")
                    auto.click(pos, time=3)
                    auto.sleep(3)
                    third = False
                

            if not third and fourth:
                pos = auto.text_click("离开", click=False)
                if pos:
                    third = True
                    logger.info("点击离开未成功")
                    continue
                if click_back(auto):
                    logger.info("点击画面即可返回")
                pos = auto.text_click("确认", click=False)
                if pos:
                    logger.info("点击确认")
                    auto.click(pos)
                    auto.sleep(2)

                result = back_to_main(auto)
                if result:
                    logger.info("返回主界面成功")
                    return True
                else:
                    logger.error("返回主界面失败")

            auto.sleep(0.5)  # 每次循环添加短暂延迟

        logger.info("领取PVP奖励超时")
        return False
    except Exception as e:
        logger.error(f"领取PVP奖励过程中出错: {e}")
        return False
