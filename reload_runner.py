# BD2-AUTO/reload_runner.py
import os
import subprocess
import sys

from livereload import Server

# 项目根目录（确保和 main.py 中路径一致）
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
# 主程序路径（你的核心启动文件）
MAIN_APP_PATH = os.path.join(PROJECT_ROOT, "main.py")

# 存储当前运行的主程序进程（用于重启时终止旧进程）
current_process = None


def run_main_app():
    """启动/重启主程序（main.py）"""
    global current_process
    # 终止旧进程（避免端口/资源占用）
    if current_process:
        print("🔴 终止旧程序进程...")
        current_process.terminate()
        current_process.wait()  # 确保进程彻底退出
    # 启动新进程（使用当前Python环境运行 main.py）
    print("🟢 启动新程序进程...")
    current_process = subprocess.Popen([
        sys.executable,  # 当前激活的Python解释器（适配虚拟环境）
        MAIN_APP_PATH
    ], cwd=PROJECT_ROOT)  # 工作目录设为项目根目录（保证路径正确）

# 可选：排除无关文件（避免无效重启，比如 venv、__pycache__ 等）


def should_ignore(path):
    """排除无需监听的文件/目录"""
    ignore_patterns = [
        "venv/",
        "logs/",
        "dist/",
        "__pycache__/",
        ".git/",
        ".vscode/",
        ".pyc"  # 排除编译后的字节码文件
    ]
    return any(pattern in path for pattern in ignore_patterns)


def on_file_change(path):
    """文件变化回调（先过滤再重启）"""
    if not should_ignore(path):
        print(f"📄 检测到文件变化：{path}")
        run_main_app()


if __name__ == "__main__":
    # 初始化热重载服务器
    server = Server()
    print(f"📡 热重载服务启动，监听目录：{PROJECT_ROOT}")

    # 核心监听规则：监听 src 下所有层级的 .py 文件 + main.py
    server.watch("src/**/*.py", on_file_change)  # src 下所有层级 .py（递归）
    server.watch("main.py", on_file_change)      # 监听主程序入口
    # server.watch("console_run.py", on_file_change)  # 监听测试脚本本身

    # 可选：如果还有其他根目录下的 .py 文件（如 console_run.py），也可以添加
    # server.watch("*.py", on_file_change)

    # 首次启动主程序
    run_main_app()

    # 启动热重载服务（默认端口35729，不自动打开网页）
    server.serve(open_url=False)
