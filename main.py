import io
import os
import sys
import threading
import time

import airtest
import cv2
import easyocr
import numpy as np
import win32gui
from airtest.core.api import Template, connect_device, paste, swipe, touch

from auto_control.image_processor import ImageProcessor
from bd2_auto import BD2Auto

processor = ImageProcessor()
# 你的代码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 修改这里：初始化自动化系统时指定支持的语言
auto = BD2Auto(ocr_engine='easyocr')

# 添加Windows设备
auto.add_device("Windows:///?title_re=BrownDust II")

a = auto.device_manager.get_active_device().set_foreground()
if a:
    print("窗口已置前")
else:
    print("窗口未置前")
a =  auto.image_processor.load_template(
    name="lo",
    path=r"C:/Users/hcx/Desktop/BD2-AUTO/Snipaste_2025-07-09_21-33-47.png"
)
# 加载模板后添加检查
print("已加载模板:", auto.image_processor.templates.keys())

# device = auto.device_manager.get_active_device()
# screen = device.capture_screen()
# if screen is not None:
#     cv2.imwrite('current_screen.png', screen)
#     print("当前屏幕已保存为 current_screen.png")

#     # 检查模板图像是否加载成功
#     template_path = r"C:/Users/hcx/Desktop/BD2-AUTO/Snipaste_2025-07-09_21-33-47.png"
#     if not os.path.exists(template_path):
#         print(f"⚠️ 模板文件不存在: {template_path}")
#     else:
#         template_img = cv2.imread(template_path)
#         print(
#             f"模板图像尺寸: {template_img.shape if template_img is not None else '加载失败'}")

#     resolution = device.get_resolution()
#     print(f"设备分辨率: {resolution}")

#     pos = auto.image_processor.match_template(screen, "lo", resolution)
#     if pos:
#         print(f"匹配位置: {pos}")
#         # 在图像上标记匹配位置
#         marked = screen.copy()
#         cv2.circle(marked, pos, 10, (0, 0, 255), 2)
#         cv2.imwrite('matched_position.png', marked)
#         print("匹配位置已标记并保存为 matched_position.png")

#         if device.click(*pos):
#             print("点击执行成功")
#         else:
#             print("点击执行失败")
#     else:
#         print("⚠️ 模板匹配失败")

auto.add_template_click_task("lo")

# 添加模板点击任务
# auto.add_template_click_task("lo")

# 启动系统
auto.start()
