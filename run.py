import io
import sys
import time
from auto import Auto
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
        while True:

            auto.add_key_task('h')
            time.sleep(3)
            if auto.add_check_element_exist_task("21"):
                print("检测到元素存在，21")
                break
        # 添加模板点击任务
        # auto._execute_text_click("活动",lang="ch_sim", roi=None, max_retry=10, retry_interval=1, delay=0, device_uri=None)
        # print(f"任务ID: {task.id}, 状态: {'已完成' if task.future.done() else '未完成'}")

        # # 等待任务
        # auto.wait(timeout=60)

        # # 检查任务状态
        # print(f"任务状态: {'已完成' if task.future.done() else '未完成'}")
        # print(f"任务异常: {task.future.exception()}")
        # print(f"任务结果: {task.future.result()}")
        sys.stdout.flush()
        
        # if login(auto):
        #     print("登录成功")
        # else:
        #     print("登录失败")
        
        sys.stdout.flush()
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