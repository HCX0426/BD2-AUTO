import sys
from auto import Auto


def login(auto: Auto):
    """登录到主界面"""

    # pos = auto.add_check_element_exist_task("确认")
    # if pos:
    #     auto.add_click_task(pos)

    print("tes1")
    auto.add_key_task("h").add_key_task("esc").wait()
    sys.stdout.flush()
