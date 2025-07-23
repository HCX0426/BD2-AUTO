import sys
from auto import Auto


def login(auto: Auto):
    return (
        auto.add_template_click_task("touch_to_start")
        .wait(timeout=60)
        .result()
    )



