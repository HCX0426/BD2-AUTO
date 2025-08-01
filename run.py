import io
import sys
import time

from auto_control.auto import Auto
from auto_control.config.control__config import *
from auto_tasks.pc.get_email import get_email
from auto_tasks.pc.login import login
from auto_tasks.pc.get_guild import get_guild
from auto_tasks.pc.get_restaurant import get_restaurant  # 添加餐馆领取导入

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
            
            # 领取邮件
            if get_email(auto):
                print("领取邮件成功")
            else:
                print("领取邮件失败")
                
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
        else:
            print("登录失败")
            raise Exception("登录失败")

        # 成功执行后正常退出
        sys.exit(0)

    except Exception as e:
        print(f"运行失败: {e}")
        sys.exit(1)
    finally:
        auto.stop()
        generate_report(__file__)  # 如果不需要生成报告，可以注释或删除


if __name__ == "__main__":
    run()