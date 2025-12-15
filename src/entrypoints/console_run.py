import sys
import io
import os

# 获取当前脚本的绝对路径
current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取项目根目录（即 BD2-AUTO 目录）
project_root = os.path.dirname(os.path.dirname(current_dir))
# 将项目根目录添加到 sys.path 中
sys.path.insert(0, project_root)

from src.auto_control.core.auto import Auto
from src.auto_control.config import *
from src.auto_tasks.pc import *
from src.auto_tasks.pc.public import back_to_main

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def console_execute():
    auto = Auto()
    try:
        if not auto.add_device():
            auto.logger.error(f"设备添加失败: {auto.last_error}")
            return False
        auto.start()

        cancel_pos = auto.text_click("取消", click=True,roi=(850,600,60,40))
        print("取消按钮位置: "+str(cancel_pos))
        # click_success = auto.click((179,158))
        # back_to_main(auto, max_attempts=2)
        # if pos := auto.check_element_exist("get_pvp/image"):

        #     print(pos)


        return True
    except Exception as e:
        auto.logger.error(f"运行失败: {str(e)}", exc_info=True)
        return False

console_execute()