
import io
import os
import sys

from src.auto_control.config import *
from src.auto_control.core.auto import Auto
from src.auto_tasks.tasks import *

# 获取当前脚本的绝对路径
current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取项目根目录（即 BD2-AUTO 目录）
project_root = os.path.dirname(os.path.dirname(current_dir))
project_root = current_dir
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    print(f"项目根目录已添加到sys.path: {project_root}")


sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def console_execute():
    auto = Auto()
    try:
        if not auto.add_device():
            auto.logger.error(f"设备添加失败: {auto.last_error}")
            return False
        auto.start()

        cancel_pos = auto.text_click("任务", roi=(616, 951, 130, 86))
        print("取消按钮位置: "+str(cancel_pos))
        # click_success = auto.click((179,158))
        # back_to_main(auto, max_attempts=2)
        # if pos := auto.check_element_exist("get_pvp/image"):
        #     print(pos)
        # return True
    except Exception as e:
        auto.logger.error(f"运行失败: {str(e)}", exc_info=True)
        return False


# -------------------------- 热重载核心代码（新增）--------------------------
if __name__ == "__main__":
    # 判断是否需要启动热重载（通过命令行参数控制，不影响正常运行）
    if len(sys.argv) > 1 and sys.argv[1] == "--reload":
        # 启动热重载模式
        import subprocess

        from livereload import Server
        current_process = None

        def run_script():
            global current_process
            # 终止旧进程
            if current_process:
                current_process.terminate()
                current_process.wait()
            # 启动新进程（运行自身，不带 --reload 参数，避免递归）
            print("🟢 启动 console_run.py（热重载模式）...")
            current_process = subprocess.Popen([
                sys.executable,
                __file__  # 运行当前脚本（console_run.py）
            ], cwd=project_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')

            # 实时打印输出
            def print_output():
                while current_process.poll() is None:
                    if line := current_process.stdout.readline():
                        print(f"[输出] {line.strip()}")
                    if err := current_process.stderr.readline():
                        print(f"[错误] {err.strip()}")
            import threading
            threading.Thread(target=print_output, daemon=True).start()

        # 初始化热重载服务器
        server = Server()
        print("📡 热重载服务启动，监听 console_run.py 和 src 目录...")
        # 监听当前脚本和 src 下所有 .py 文件
        server.watch(__file__, run_script)  # 监听 console_run.py 本身
        server.watch("src/**/*.py", run_script)  # 监听 src 下所有层级 .py
        # 首次启动
        run_script()
        server.serve(open_url=False)
    else:
        # 正常运行模式（不带 --reload 参数时，直接执行核心逻辑）
        console_execute()
