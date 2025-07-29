import io
import sys
import time

from auto_control.auto import Auto
from auto_control.config.control__config import *
from auto_tasks.pc.get_email import get_email
from auto_tasks.pc.login import login

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def run():
    auto = Auto()
    try:
        auto.add_device()
        auto.start()

        if login(auto):
            auto.add_sleep_task(2)
            if get_email(auto):
                print("领取邮件成功")
            else:
                raise Exception("领取邮件失败")
        else:
            raise Exception("登录失败")

        # 成功执行后正常退出
        sys.exit(0)

    except Exception as e:
        print(f"运行失败: {e}")
        sys.exit(1)
    finally:
        auto.stop()
        generate_report(__file__)


if __name__ == "__main__":
    run()
