import os
import easyocr
import io
import sys
import time

import cv2

from auto_tasks.pc.login import Login
from bd2_auto import BD2Auto

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    reader = easyocr.Reader(['ch_sim', 'en'])  # 测试简体中文+英文
    print("✅ 中文支持已安装！")
except Exception as e:
    print("❌ 中文未正确安装，错误信息:", e)


# 初始化自动化系统
auto = BD2Auto(ocr_engine='easyocr')

# 添加Windows设备
auto.add_device("Windows:///?title_re=BrownDust II")

a = auto.device_manager.get_active_device().set_foreground()
if a:
    print("窗口已置前")
else:
    print("窗口未置前")

# 调试截

device = auto.device_manager.get_active_device()
print("=== 设备调试信息 ===")
print(f"设备URI: {device.device_uri}")
print(f"连接状态: {device.connected}")
# print(f"窗口句柄: {device.window_handle}")
print(f"分辨率: {device.resolution}")
if device.is_minimized():
    print("⚠️ 窗口已最小化，无法截图")
    device.set_foreground()  # 尝试恢复窗口
    time.sleep(1)  # 等待窗口恢复

screen = auto.capture_screen()
if screen is not None:
    print(f"截图尺寸: {screen.shape if hasattr(screen, 'shape') else '未知'}")
    cv2.imwrite('debug_screen.png', screen)
    result = auto.ocr_processor.recognize_text(screen, lang='ch_sim')
    print(f"直接识别结果: {result}")
else:
    print("⚠️ 截图失败")

# auto.add_key_task("h")
time.sleep(5)
auto.add_text_click_task("餐馆营业额", lang='ch_sim')

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
