from bd2_auto import BD2Auto

# 初始化自动化系统
auto = BD2Auto(base_resolution=(1920, 1080))

# 添加设备
auto.add_device("Windows:///?title_re=BrownDust II", "windows")  # Windows游戏
auto.add_device("Android://127.0.0.1:5037/emulator-5554", "adb")  # Android模拟器

# 设置活动设备
auto.set_active_device("Windows:///?title_re=BrownDust II")

# 加载模板
auto.image_processor.load_template(
    "login_button", 
    "images/login_button.png",
    roi=(0.4, 0.6, 0.6, 0.7),
    threshold=0.9,
    scale_strategy="fit"
)

# 启动系统
auto.start()

# 添加任务序列（Windows设备）
auto.add_template_click_task("login_button", delay=2)
auto.add_key_task("enter", delay=1)

# 切换到模拟器设备
auto.set_active_device("Android://127.0.0.1:5037/emulator-5554")

# 添加模拟器任务
auto.add_click_task((0.5, 0.5), delay=2)  # 点击中心位置
auto.add_text_input_task("Hello BD2", delay=1)  # 文本输入

# 混合设备任务
auto.add_click_task((0.5, 0.5), device_uri="Windows:///?title_re=BrownDust II")
auto.add_key_task("space", device_uri="Android://127.0.0.1:5037/emulator-5554")

# 停止系统
auto.stop()