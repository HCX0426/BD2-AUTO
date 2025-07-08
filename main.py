from bd2_auto import BD2Auto
import time
import sys
import io

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

# 监控状态
try:
    while True:
        status = auto.get_status()
        print(f"运行状态: {status}")
        time.sleep(5)
except KeyboardInterrupt:
    auto.stop()