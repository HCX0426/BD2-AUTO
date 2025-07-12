import io
import sys
import time

from auto_main import Auto
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
# import torch
# print(torch.__version__)          # 应显示类似 2.3.0+cu121
# print(torch.cuda.is_available())  # 应返回 True

# import easyocr
# reader = easyocr.Reader(['en'], gpu=True)
# print(reader.device)  # 应输出 'cuda'
# # 你的代码

sys.stdout.flush()  # 强制刷新输出缓冲区
auto = Auto(ocr_engine='easyocr')

# 添加Windows设备
auto.add_device("Windows:///?title_re=BrownDust II")

a = auto.device_manager.get_active_device().set_foreground()
a =  auto.image_processor.load_template(
    name="lo",
    path=r"C:/Users/hcx/Desktop/BD2-AUTO/Snipaste_2025-07-09_21-33-47.png"
)
print("已加载模板:", auto.image_processor.templates.keys())


time.sleep(5)


auto.add_text_click_task("活动",lang="ch_sim")
auto.start()
sys.stdout.flush()  # 强制刷新输出缓冲区
try:
    while True:
        time.sleep(1)
        sys.stdout.flush()  
except KeyboardInterrupt:
    auto.stop()
