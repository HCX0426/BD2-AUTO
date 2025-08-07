import time

from auto_control.auto import Auto
from auto_control.logger import Logger
from auto_tasks.pc.public import back_to_main, click_back


def intensive_decomposition(auto: Auto, timeout: int = 600):
    """强化分解"""
    try:
        logger = auto.get_task_logger("intensive_decomposition")
        logger.info("开始强化分解")
        start_time = time.time()

        one = True  # 分解流程
        two = True  # 强化流程

        first = True
        second = True
        third = True
        fourth = True
        fifth = True
        sixth = True
        seventh = True
        eighth = True

        while time.time() - start_time < timeout:
            if auto.check_should_stop():
                logger.info("检测到停止信号，退出任务")
                return True
            if one:
                # 分解流程
                # 检测是否在主界面
                if first:
                    if back_to_main(auto):
                        auto.text_click("背包")
                        auto.sleep(3)
                        first = False

                if not first and second:
                    pos = auto.check_element_exist(
                        "intensive_decomposition/装备标识")
                    if pos:
                        auto.click(pos, time=2)
                        auto.sleep(3)
                        second = False

                if not second and third:
                    pos = auto.check_element_exist(
                        "intensive_decomposition/筛选标识")
                    if pos:
                        auto.click(pos)
                        auto.sleep(2)
                        third = False

                if not third and fourth:
                    pos = auto.check_element_exist(
                        "intensive_decomposition/SR")
                    if pos:
                        auto.click(pos)
                        auto.sleep(2)
                        auto.text_click("确认")
                        auto.sleep(3)
                        fourth = False

                if not fourth and fifth:
                    if auto.text_click("确认",click=False):
                        fourth = True
                        continue

                    if auto.text_click("一键分解"):
                        auto.sleep(2)
                        if auto.click((785, 200)):
                            auto.sleep(1)
                            pos = auto.check_element_exist(
                                "intensive_decomposition/确认")
                            if pos:
                                auto.click(pos)
                                auto.sleep(2)
                                pos = auto.check_element_exist("intensive_decomposition/分解按钮")
                                if pos:
                                    logger.info("点击分解")
                                    auto.click(pos)
                                    auto.sleep(3)
                                    fifth = False

                if not fifth and sixth:
                    if click_back(auto):
                        logger.info("点击画面即可返回")
                        auto.sleep(2)

                        if back_to_main(auto):
                            logger.info("返回主界面")
                            auto.sleep(3)
                            one = False

                            # 重置步骤变量
                            first = True
                            second = True
                            third = True
                            fourth = True
                            fifth = True
                            sixth = True
                        else:
                            logger.info("返回主界面失败")
                            return False
                    else:
                        logger.info("点击返回失败")
                        fifth = True


            if two and not one:
                # 强化流程
                # 检测是否在主界面
                if first:
                    if back_to_main(auto):
                        auto.text_click("背包")
                        auto.sleep(3)
                        first = False

                if not first and second:
                    pos = auto.check_element_exist(
                        "intensive_decomposition/装备标识")
                    if pos:
                        auto.click(pos, time=2)
                        auto.sleep(3)
                        second = False

                if not second and third:
                    pos = auto.check_element_exist(
                        "intensive_decomposition/筛选标识")
                    if pos:
                        auto.click(pos)
                        auto.sleep(2)
                        third = False

                if not third and fourth:
                    pos = auto.check_element_exist(
                        "intensive_decomposition/UR")
                    if pos:
                        auto.click(pos)
                        auto.sleep(2)

                        pos = auto.check_element_exist(
                            "intensive_decomposition/满等级")
                        if pos:
                            auto.click(pos)
                            auto.sleep(2)
                            auto.text_click("确认")
                            auto.sleep(3)
                            fourth = False

                if not fourth and fifth:
                    # 防止确认失效
                    if auto.text_click("确认"):
                        logger.info("确认")
                        auto.sleep(3)

                    if auto.click((785, 200)):
                        logger.info("选择装备")
                        auto.sleep(1)
                        if auto.text_click("精炼"):
                            logger.info("精炼")
                            auto.sleep(2)
                            fifth = False

                if not fifth and sixth:
                    if auto.text_click("连续精炼"):
                        logger.info("连续精炼")
                        auto.sleep(1)
                        sixth = False

                if not sixth and seventh:
                    pos = auto.check_element_exist(
                        "intensive_decomposition/加十")
                    if pos:
                        logger.info("加十")
                        auto.click(pos)
                        auto.sleep(1)
                        pos = auto.check_element_exist(
                            "intensive_decomposition/精炼")
                        if pos:
                            logger.info("精炼")
                            auto.click(pos)
                            auto.sleep(1)
                    pos = auto.check_element_exist("public/跳过")
                    if pos:
                        logger.info("跳过")
                        auto.click(pos)
                        auto.sleep(5)
                    if auto.text_click("确认"):
                        logger.info("确认")
                        auto.sleep(3)
                        seventh = False

                if not seventh and eighth:
                    if back_to_main(auto):
                        logger.info("返回主界面")
                        auto.sleep(3)
                        two = False
                        return True

            auto.sleep(0.5)  # 每次循环添加短暂延迟

        logger.info("领取公会奖励超时")
        return False
    except Exception as e:
        logger.error(f"领取公会奖励过程中出错: {e}")
        return False
