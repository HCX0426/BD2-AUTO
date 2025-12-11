import os
import sys

def get_current_env() -> str:
    """获取当前环境：dev 或 prod"""
    # 1. 加载环境变量文件（开发环境读 .env，生产环境读打包的 .env.prod）
    if getattr(sys, 'frozen', False):
        # 打包环境：从 _MEIPASS 读取嵌入的 .env.prod
        env_path = os.path.join(sys._MEIPASS, ".env.prod")
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
    else:
        # 开发环境：读取本地 .env 文件（若存在）
        if os.path.exists(".env"):
            with open(".env", 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
    
    # 2. 从环境变量获取 ENV，默认 dev
    return os.getenv("ENV", "dev")

# 初始化环境（项目启动时自动执行）
current_env = get_current_env()