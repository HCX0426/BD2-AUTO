import io
import sys
import time

from auto_tasks.pc.login import Login
from bd2_auto import BD2Auto

# 控制台中文调试
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 初始化自动化系统
auto = BD2Auto(ocr_engine='tesseract')

# 添加Windows设备
auto.add_device("Windows:///?title_re=BrownDust II")

a = auto.device_manager.get_active_device().set_foreground()
if a:
    print("窗口已置前")
else:
    print("窗口未置前")

auto.add_key_task("h")
# 启动系统
auto.start()

# 初始化并添加任务
# sample_task = Login(auto.task_executor)
# task_id = sample_task.run(message="主线程启动的示例任务")
# print(f"已添加示例任务，任务ID: {task_id}")

# 监控状态
try:
    while True:
        status = auto.get_status()
        print(f"运行状态: {status}")
        time.sleep(5)
except KeyboardInterrupt:
    auto.stop()
