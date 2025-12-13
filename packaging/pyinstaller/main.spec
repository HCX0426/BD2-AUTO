import os
import sys
from pathlib import Path

# 修复路径定位（确保从项目根目录打包）
project_root = Path(os.getcwd())
if not (project_root / "src").exists():
    raise FileNotFoundError(f"无法确定项目根目录，请在项目根目录执行打包命令。当前目录: {project_root}")

# 资源文件配置（优化目录整体打包，避免文件遗漏）
datas = [
    # 配置文件（开发/生产环境）
    (str(project_root / "config"), "config"),  # 整体打包config目录，包含dev和prod
    
    # 任务相关资源（核心优化：整体打包任务目录）
    (str(project_root / "src/auto_tasks/pc"), "src/auto_tasks/pc"),  # 包含所有任务.py和templates
    
    # 运行时配置（开发环境的任务配置会覆盖到生产环境路径）
    (str(project_root / "runtime/dev/task_configs.json"), "runtime/prod"),
    (str(project_root / "runtime/dev/app_settings.json"), "runtime/prod"),  # 统一UI配置到prod目录
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
    "numpy.testing",
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