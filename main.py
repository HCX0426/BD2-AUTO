from bd2_auto import BD2Auto
import time

# 初始化自动化系统
auto = BD2Auto(ocr_engine='tesseract')

# 添加Windows设备
auto.add_device("Windows:///?title_re=BrownDust II")

# 添加OCR任务 - 识别登录界面文本
def ocr_callback(result):
    print("OCR识别结果:")
    print(result)
    if "登录" in result:
        print("检测到登录界面")
        
auto.add_ocr_task(ocr_callback, lang='chi_sim', roi=(0.4, 0.6, 0.6, 0.7))

# 添加文本点击任务 - 点击"开始游戏"按钮
auto.add_text_click_task("开始游戏", lang='chi_sim', delay=3)

# 添加模板点击任务 - 点击技能图标
auto.image_processor.load_template(
    "skill_icon", 
    "images/skill.png",
    roi=(0.7, 0.1, 0.9, 0.3)
)
auto.add_template_click_task("skill_icon", delay=2)

# 添加组合键任务 - 释放大招
auto.add_task(
    lambda: auto.input_controller.combo_action(['ctrl', 'alt', 'q'], delay=0.5),
    priority=1  # 高优先级
)

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