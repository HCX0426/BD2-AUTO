import os
import sys
from pathlib import Path

# 修复路径定位（确保从项目根目录打包）
project_root = Path(os.getcwd())
if not (project_root / "src").exists():
    raise FileNotFoundError(f"无法确定项目根目录，请在项目根目录执行打包命令。当前目录: {project_root}")

# -------------------------- 获取项目统一的OCR模型路径 --------------------------
# 开发环境：runtime/dev/ocr_models（本地开发时模型存放目录，与PathManager定义一致）
dev_ocr_model_dir = project_root / "runtime" / "dev" / "ocr_models"
# 确保开发环境模型目录存在（避免打包时路径不存在报错，无需手动创建）
dev_ocr_model_dir.mkdir(parents=True, exist_ok=True)

# 系统默认EasyOCR模型目录（用户本地缓存）
sys_easyocr_model_dir = Path.home() / ".EasyOCR" / "model"

# -------------------------- 适配模型命名（craft_mlt_25k.pth = detect.pth） --------------------------
def get_ocr_model_path(model_name: str) -> Path:
    """
    获取OCR模型文件路径（适配不同版本的模型命名）
    - 检测模型：detect.pth → craft_mlt_25k.pth（你的环境中实际名称）
    - 简体中文模型：ch_sim_g2.pth → zh_sim_g2.pth（你的环境中实际名称）
    """
    # 模型名称映射（适配你的环境）
    model_name_map = {
        "detect.pth": "craft_mlt_25k.pth",
        "ch_sim_g2.pth": "zh_sim_g2.pth"
    }
    actual_model_name = model_name_map.get(model_name, model_name)

    # 优先检查项目内模型目录
    project_model_path = dev_ocr_model_dir / actual_model_name
    if project_model_path.exists():
        return project_model_path
    
    # 其次检查系统默认目录
    sys_model_path = sys_easyocr_model_dir / actual_model_name
    if sys_model_path.exists():
        return sys_model_path
    
    # 若都不存在，抛出明确错误
    raise FileNotFoundError(
        f"OCR模型文件 {actual_model_name} 未找到！\n"
        f"请将以下2个模型文件放置到项目内 {dev_ocr_model_dir} 目录：\n"
        f"1. 检测模型：craft_mlt_25k.pth（对应detect.pth）\n"
        f"2. 简体中文模型：zh_sim_g2.pth（对应ch_sim_g2.pth）\n"
        f"当前你的模型目录里已有这两个文件，直接复制到 {dev_ocr_model_dir} 即可。"
    )

# 资源文件配置
datas = [
    # 配置文件（开发/生产环境）
    (str(project_root / "config"), "config"),  # 整体打包config目录，包含dev和prod
    
    # 任务相关资源（核心优化：整体打包任务目录）
    (str(project_root / "src/auto_tasks/pc"), "src/auto_tasks/pc"),  # 包含所有任务.py和templates
    
    # 运行时配置（开发环境的任务配置会覆盖到生产环境路径）
    (str(project_root / "runtime/dev/task_configs.json"), "runtime/prod"),
    (str(project_root / "runtime/dev/app_settings.json"), "runtime/prod"),  # 统一UI配置到prod目录
    
    # -------------------------- 使用实际模型名称打包 --------------------------
    (str(get_ocr_model_path("detect.pth")), "runtime/prod/ocr_models"),  # 实际打包craft_mlt_25k.pth
    (str(get_ocr_model_path("ch_sim_g2.pth")), "runtime/prod/ocr_models"),  # 实际打包zh_sim_g2.pth
]

# 隐藏导入（保持必要模块，移除重复项）
hiddenimports = [
    # 任务模块（与__init__.py中的导出列表保持一致）
    "src.auto_tasks.pc.daily_missions",
    "src.auto_tasks.pc.get_email",
    "src.auto_tasks.pc.get_guild",
    "src.auto_tasks.pc.get_pvp",
    "src.auto_tasks.pc.get_restaurant",
    "src.auto_tasks.pc.intensive_decomposition",
    "src.auto_tasks.pc.login",
    "src.auto_tasks.pc.lucky_draw",
    "src.auto_tasks.pc.map_collection",
    "src.auto_tasks.pc.pass_activity",
    "src.auto_tasks.pc.pass_rewards",
    "src.auto_tasks.pc.sweep_daily",
    "src.auto_tasks.pc.public",  # 公共函数模块
    
    # 核心组件
    "src.core.path_manager",
    "src.core.task_manager",
    "src.auto_control.core.auto",
    "src.auto_control.devices.windows_device",
    
    # GUI相关
    "src.entrypoints.main_window",
    
    # 第三方依赖
    "easyocr",
    "win32api",
    "win32con",
    "win32gui",
    "win32process",
    "PyQt6.sip",
    "PyQt6.QtWidgets",
    "PyQt6.QtGui",
    "PyQt6.QtCore",
    "scipy.special._ufuncs_cxx",
]

# 排除不必要的模块（进一步精简体积）
excludes = [
    "matplotlib",
    "pandas",
    "tensorboard",
    "tkinter",  # 排除未使用的GUI库
    "setuptools",  # 运行时不需要的打包工具
]

# 手动指定动态库（确保依赖正常加载）
binaries = []
# Torch DLL
torch_lib_path = Path(sys.executable).parent / "Lib" / "site-packages" / "torch" / "lib"
if torch_lib_path.exists():
    binaries.append((str(torch_lib_path / "*.dll"), "torch/lib"))
# OpenCV DLL
cv2_lib_path = Path(sys.executable).parent / "Lib" / "site-packages" / "cv2"
if cv2_lib_path.exists():
    binaries.append((str(cv2_lib_path / "*.dll"), "cv2"))
# PyQt6 DLL
pyqt6_lib_path = Path(sys.executable).parent / "Lib" / "site-packages" / "PyQt6" / "Qt6" / "bin"
if pyqt6_lib_path.exists():
    binaries.append((str(pyqt6_lib_path / "*.dll"), "PyQt6/Qt6/bin"))

# 分析阶段配置
a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],  # 项目根目录加入搜索路径
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# 优化：移除重复的二进制文件（避免打包多个副本）
a.binaries = list(dict.fromkeys(a.binaries))
# 优化：移除冗余的zipped_data（减少体积）
a.zipped_data = [(k, v) for k, v in a.zipped_data if not k.startswith(('numpy/testing', 'scipy/test'))]

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# 生成可执行文件配置
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="BD2-AUTO",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # 生产环境保持压缩
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 建议先保持控制台可见，方便调试打包问题
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 生成单文件夹输出
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BD2-AUTO",
)

# ------------------- 自动清理 build 文件夹 -------------------
print("打包流程完成，开始清理 build 文件夹...") 
try:
    import shutil
    build_dir = project_root / "build" # 构建 build 目录路径
    if build_dir.exists() and build_dir.is_dir():
        shutil.rmtree(build_dir) # 删除整个 build 目录及其内容
        print(f"已成功删除 build 文件夹: {build_dir}")
    else:
        print(f"警告：未找到 build 文件夹或路径非目录: {build_dir}")
except Exception as e:
    # 捕获可能的异常（如权限不足等），避免中断打包结果
    print(f"清理 build 文件夹时出错: {e}")
    print("请注意手动清理 build 文件夹。")

print("清理流程结束")