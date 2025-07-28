import io
import sys
import time

from auto_control.auto import Auto
from auto_control.config.control__config import *
from auto_tasks.pc.get_email import get_email

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def run():
    try:
        # 创建Auto实例
        auto = Auto()
        # 添加设备
        auto.add_device()
        # 启动系统
        auto.start()

        # 子任务
        # if login(auto):
        #     print("登录成功")
        # else:
        #     print("登录失败")

        result = get_email(auto)
        if result:
            print("领取邮件成功")
        else:
            print("领取邮件失败")

    except Exception as e:
        print(f"运行过程中出错: {e}")
    finally:
        generate_report(__file__)
        auto.stop()
        sys.exit(1)
        print("程序已退出")

    # 保持主线程运行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        auto.stop()
        print("程序已退出")


run()
