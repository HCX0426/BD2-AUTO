import io
import sys
import time
from auto_main import Auto
from auto_tasks.pc import *
from auto_tasks.pc.login import login

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def run():
    sys.stdout.flush()
    auto = Auto()
    # 添加Windows设备
    auto.add_device("Windows:///?title_re=BrownDust II")
    auto.add_text_click_task("活动")
    # login(auto)
    
    # 启动自动任务
    auto.start()
    sys.stdout.flush()
    
    # 保持主线程运行
    try:
        while True:
            time.sleep(1)
            sys.stdout.flush()
    except KeyboardInterrupt:
        auto.stop()
        print("程序已退出")

run()