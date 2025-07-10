import io
import sys
import time

from bd2_auto import BD2Auto

# 你的代码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stdout.flush()  # 强制刷新输出缓冲区
# 修改这里：初始化自动化系统时指定支持的语言
auto = BD2Auto(ocr_engine='easyocr')

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
except KeyboardInterrupt:
    auto.stop()

# 使用示例
# if __name__ == "__main__":
#     def sync_task(name: str) -> str:
#         print(f"执行同步任务: {name}")
#         time.sleep(1)
#         return f"同步任务 {name} 完成"

#     async def async_task(name: str) -> str:
#         print(f"执行异步任务: {name}")
#         await asyncio.sleep(1)
#         return f"异步任务 {name} 完成"

#     def callback(result: Optional[str], error: Optional[Exception]) -> None:
#         if error:
#             print(f"任务失败: {str(error)}")
#         else:
#             print(f"任务结果: {result}")

#     executor = TaskExecutor(max_workers=2)
#     executor.start()

#     # 添加不同优先级的任务
#     executor.add_task(sync_task, "任务1", priority=3, callback=callback)
#     executor.add_task(async_task, "任务2", priority=1, callback=callback)
#     executor.add_task(sync_task, "任务3", priority=5, callback=callback)

#     # 动态调整优先级示例
#     def condition(task: Task) -> bool:
#         return task.func.__name__ == "sync_task" and "任务3" in task.args

#     executor.adjust_task_priority(condition, 2)  # 将任务3的优先级提高到2

#     time.sleep(2)  # 等待部分任务完成

#     executor.pause()
#     print("执行器暂停中...")
#     time.sleep(2)
#     executor.resume()

#     executor.wait_all_tasks()
#     executor.stop()