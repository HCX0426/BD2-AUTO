from auto_main import Auto


def login(auto: Auto):
    """登录到主界面"""

    # pos = auto.add_check_element_exist_task("确认")
    # if pos:
    #     auto.add_click_task(pos)

    print("tes1")
    auto.add_template_click_task("touch_to_start")