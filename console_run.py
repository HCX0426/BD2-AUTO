import sys
import io  # 添加缺失的io导入

from auto_control import Auto
from auto_control.config import *
from auto_control.image_processor import ImageProcessor
from auto_tasks.pc import *
from auto_tasks.pc.public import back_to_main

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def console_execute():
    auto = Auto()
    try:
        if not auto.add_device():
            auto.logger.error(f"设备添加失败: {auto.last_error}")
            return False
        auto.start()
        # 修改template_click的使用方式，它返回的是布尔值而不是坐标
        # click_success = auto.click((179,158))
        click_success = auto.template_click("get_guild/公会标识")
        if click_success:
            auto.logger.info(f"公会标识点击成功:{click_success}")
        else:
            auto.logger.warning("公会标识点击失败或未找到")

        # a  = back_to_main(auto)
        # print("11"+str(a))
        
        # 如果需要获取坐标位置，应该使用check_element_exist结合其他方法
        # 例如：
        # if auto.check_element_exist("get_guild/公会标识"):
        #     # 这里可以获取坐标或执行其他操作
        
        return True
    except Exception as e:
        auto.logger.error(f"运行失败: {str(e)}", exc_info=True)
        return False

console_execute()