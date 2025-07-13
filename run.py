import io
import sys
import time
from auto import Auto
from auto_tasks.pc import *
from auto_tasks.pc.login import login

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def run():
    sys.stdout.flush()
    # 创建Auto实例
    auto = Auto()

    # 添加设备
    auto.add_device("Windows:///?title_re=BrownDust II")

    # 启动系统
    auto.start()

    # 添加任务并获取ID
    click_task = auto.add_click_task((0.5, 0.5), is_relative=True)  # 点击屏幕中心
    task_id = auto.get_task_id(click_task)
    print(f"点击任务ID: {task_id}")

    # 链式调用
    (auto.add_key_task('a', duration=0.2)
    .then(lambda _: print("按下了A键"))
    .add_wait_task(1.0)
    .add_click_task((100, 200), is_relative=False)  # 绝对坐标
    .catch(lambda e: print(f"发生错误: {e}"))
    .wait()
    )

    # 创建并执行任务链
    task1 = auto.create_click_task((0.1, 0.1), is_relative=True)
    task2 = auto.create_wait_task(0.5)
    task3 = auto.create_key_task('enter')

    if auto.strict_sequence(task1, task2, task3):
        print("任务链执行成功")
    else:
        print(f"任务失败: {auto.last_error}")

    # 取消任务示例
    long_task = auto.add_wait_task(10.0)
    if auto.cancel_task(auto.get_task_id(long_task)):
        print("成功取消了长时间等待任务")
    sys.stdout.flush()
    # 停止系统
    auto.stop()
    
    # 保持主线程运行
    try:
        while True:
            time.sleep(1)
            sys.stdout.flush()
    except KeyboardInterrupt:
        auto.stop()
        print("程序已退出")

run()