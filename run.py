import io
import sys
import time
from auto_control.auto import Auto
from auto_tasks.pc import *
from auto_tasks.pc.login import login

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def run():
    try:
        sys.stdout.flush()
        # 创建Auto实例
        auto = Auto()

        # 添加设备
        auto.add_device("Windows:///?title_re=BrownDust II")

        # 启动系统
        auto.start()
        # while True:
        
        pos = auto.add_template_click_task("活动").wait()
        if pos:
            print(f"点击位置: {pos}")

        time.sleep(3)

    except Exception as e:
        print(f"运行过程中出错: {e}")
        sys.stdout.flush()
    finally:
        auto.stop()
        sys.exit(1)
        print("程序已退出")

    # 保持主线程运行
    try:
        while True:
            time.sleep(1)
            sys.stdout.flush()
    except KeyboardInterrupt:
        auto.stop()
        print("程序已退出")

run()