import io
import sys

from auto_control.auto import Auto
from auto_control.config.control__config import *
from auto_tasks.pc.daily_missions import daily_missions
from auto_tasks.pc.get_email import get_email
from auto_tasks.pc.get_guild import get_guild
from auto_tasks.pc.get_pvp import get_pvp
from auto_tasks.pc.get_restaurant import get_restaurant
from auto_tasks.pc.intensive_decomposition import intensive_decomposition
from auto_tasks.pc.login import login
from auto_tasks.pc.lucky_draw import lucky_draw
from auto_tasks.pc.map_collection import map_collection
from auto_tasks.pc.pass_activity import pass_activity
from auto_tasks.pc.pass_rewards import pass_rewards
from auto_tasks.pc.sweep_daily import sweep_daily

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def run():
    auto = Auto()
    try:
        # 添加设备并启动
        auto.add_device()
        auto.start()

        # 登录游戏
        if login(auto):
            print("登录成功")
            auto.sleep(2)

            if map_collection(auto):
                print("地图采集成功")
            else:
                print("地图采集失败")

            if sweep_daily(auto):
                print("扫荡成功")
            else:
                print("扫荡失败")

            if pass_activity(auto):
                print("通过活动成功")
            else:
                print("通过活动失败")

            if intensive_decomposition(auto):
                print(" 强化分解成功")
            else:
                print(" 强化分解失败")

            # 领取公会奖励
            if get_guild(auto):
                print("领取公会奖励成功")
            else:
                print("领取公会奖励失败")

            # 领取餐馆奖励
            if get_restaurant(auto):
                print("领取餐馆奖励成功")
            else:
                print("领取餐馆奖励失败")

            if lucky_draw(auto):
                print("抽抽乐成功")
            else:
                print("抽抽乐失败")

            # 领取PVP奖励
            if get_pvp(auto):
                print("领取PVP奖励成功")
            else:
                print("领取PVP奖励失败")

            if pass_rewards(auto):
                print("通行证成功")
            else:
                print("通行证失败")

            # 领取邮件
            if get_email(auto):
                print("领取邮件成功")
            else:
                print("领取邮件失败")

            if daily_missions(auto):
                print("领取每日任务成功")
            else:
                print("领取每日任务失败")

        else:
            print("登录失败")
            raise Exception("登录失败")

    except Exception as e:
        print(f"运行失败: {e}")
        sys.exit(1)
    finally:
        auto.stop()
        generate_report(__file__)
        sys.exit(0)


if __name__ == "__main__":
    run()
