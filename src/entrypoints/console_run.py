import sys
import io

from src.auto_control.core.auto import Auto
from src.auto_control.config import *
from src.auto_tasks.pc import *

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def console_execute():
    auto = Auto()
    try:
        if not auto.add_device():
            auto.logger.error(f"设备添加失败: {auto.last_error}")
            return False
        auto.start()
        # click_success = auto.click((179,158))
        if pos := auto.check_element_exist("get_pvp/image"):

            print(pos)


        return True
    except Exception as e:
        auto.logger.error(f"运行失败: {str(e)}", exc_info=True)
        return False

console_execute()