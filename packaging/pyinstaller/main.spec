import os
import sys
import shutil
from pathlib import Path
# 必须导入PyInstaller的核心类（原代码缺失）
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

# 项目打包配置文件（PyInstaller spec）
# 确保从项目根目录执行打包，依赖路径和资源配置已适配项目结构

# 修复路径定位：强制从项目根目录打包（需存在src目录）
project_root = Path(os.getcwd())
if not (project_root / "src").exists():
    raise FileNotFoundError(f"无法确定项目根目录，请在项目根目录执行打包命令。当前目录: {project_root}")

# 定义打包成功校验路径（修复后正确路径）
dist_dir = project_root / "dist" / "BD2-AUTO"  # 最终输出文件夹
exe_path = dist_dir / "BD2-AUTO.exe"  # 正确的exe路径

# -------------------------- OCR模型路径配置 --------------------------
dev_ocr_model_dir = project_root / "runtime" / "dev" / "ocr_models"
dev_ocr_model_dir.mkdir(parents=True, exist_ok=True)
sys_easyocr_model_dir = Path.home() / ".EasyOCR" / "model"

def get_ocr_model_path(model_name: str) -> Path:
    model_name_map = {
        "detect.pth": "craft_mlt_25k.pth",
        "ch_sim_g2.pth": "zh_sim_g2.pth"
    }
    actual_model_name = model_name_map.get(model_name, model_name)

    # 优先查找项目内模型目录
    project_model_path = dev_ocr_model_dir / actual_model_name
    if project_model_path.exists():
        return project_model_path
    
    # 次优先查找系统默认缓存目录
    sys_model_path = sys_easyocr_model_dir / actual_model_name
    if sys_model_path.exists():
        return sys_model_path
    
    raise FileNotFoundError(
        f"OCR模型文件 {actual_model_name} 未找到！\n"
        f"请将以下2个模型文件放置到项目内 {dev_ocr_model_dir} 目录：\n"
        f"1. 检测模型：craft_mlt_25k.pth（对应detect.pth）\n"
        f"2. 简体中文模型：zh_sim_g2.pth（对应ch_sim_g2.pth）\n"
        f"可从EasyOCR官方仓库或模型缓存目录获取。"
    )

# -------------------------- 资源文件打包配置 --------------------------
datas = [
    (str(project_root / "config"), "config"),
    (str(project_root / "src/auto_tasks/tasks"), "src/auto_tasks/tasks"),
    (str(project_root / "src/auto_tasks/templates"), "src/auto_tasks/templates"),
    (str(project_root / "runtime/dev/task_configs.json"), "runtime/prod"),
    (str(project_root / "runtime/dev/app_settings.json"), "runtime/prod"),
    # 模型文件输出路径（保持原始配置）
    (str(get_ocr_model_path("detect.pth")), "runtime/prod/ocr_models"),
    (str(get_ocr_model_path("ch_sim_g2.pth")), "runtime/prod/ocr_models"),
]

# -------------------------- 隐藏导入配置 --------------------------
# 保留你原始的依赖配置，未添加任何补充依赖
hiddenimports = [
    # PC端自动任务模块（与任务导出列表一致）
    "src.auto_tasks.tasks.daily_missions",
    "src.auto_tasks.tasks.get_email",
    "src.auto_tasks.tasks.get_guild",
    "src.auto_tasks.tasks.get_pvp",
    "src.auto_tasks.tasks.get_restaurant",
    "src.auto_tasks.tasks.intensive_decomposition",
    "src.auto_tasks.tasks.login",
    "src.auto_tasks.tasks.lucky_draw",
    "src.auto_tasks.tasks.map_collection",
    "src.auto_tasks.tasks.pass_activity",
    "src.auto_tasks.tasks.pass_rewards",
    "src.auto_tasks.tasks.sweep_daily",
    "src.auto_tasks.tasks.public",
    # 项目核心组件
    "src.core.path_manager",
    "src.core.task_manager",
    "src.auto_control.core.auto",
    "src.auto_control.devices.windows_device",
    # GUI相关组件
    "src.entrypoints.main_window",
    # 第三方依赖模块（保持原始配置）
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

# -------------------------- 排除模块配置 --------------------------
# 保留原始排除配置
excludes = [
    "matplotlib",
    "pandas",
    "tensorboard",
    "tkinter",
    "setuptools",
]

# -------------------------- 动态库依赖配置 --------------------------
binaries = []
# Torch相关DLL（保持原始配置）
torch_lib_path = Path(sys.executable).parent / "Lib" / "site-packages" / "torch" / "lib"
if torch_lib_path.exists():
    binaries.append((str(torch_lib_path / "*.dll"), "torch/lib"))
# OpenCV相关DLL（保持原始配置）
cv2_lib_path = Path(sys.executable).parent / "Lib" / "site-packages" / "cv2"
if cv2_lib_path.exists():
    binaries.append((str(cv2_lib_path / "*.dll"), "cv2"))
# PyQt6相关DLL（保持原始配置）
pyqt6_lib_path = Path(sys.executable).parent / "Lib" / "site-packages" / "PyQt6" / "Qt6" / "bin"
if pyqt6_lib_path.exists():
    binaries.append((str(pyqt6_lib_path / "*.dll"), "PyQt6/Qt6/bin"))

# -------------------------- 打包核心流程 --------------------------
try:
    print("开始执行打包流程...")

    # 1. 依赖分析阶段
    a = Analysis(
        [str(project_root / "main.py")],  # 项目入口文件
        pathex=[str(project_root)],       # 项目根目录加入搜索路径
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

    # 移除重复二进制文件（保持原始优化）
    a.binaries = list(dict.fromkeys(a.binaries))
    # 移除冗余压缩数据（保持原始优化）
    a.zipped_data = [(k, v) for k, v in a.zipped_data if not k.startswith(('numpy/testing', 'scipy/test'))]

    # 2. 生成PYZ文件
    pyz = PYZ(a.pure, a.zipped_data, cipher=None)

    # 3. 生成可执行文件（修复路径配置，关键修复保留）
    exe = EXE(
        pyz,
        a.scripts,  # 补充缺失的scripts参数（必要修复）
        [],
        exclude_binaries=True,  # 关键：排除二进制文件，由COLLECT统一处理
        name="BD2-AUTO",  # 只指定文件名，不嵌套路径（修复路径冲突）
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,  # 隐藏控制台窗口（保持原始配置）
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        # 可选：添加图标（替换为你的图标路径，如需启用请取消注释）
        # icon=str(project_root / "assets" / "icon.ico")
    )

    # 4. 生成单文件夹输出（整合所有依赖）
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="BD2-AUTO",  # 输出文件夹名称（dist/BD2-AUTO）
    )

    # -------------------------- 打包成功后处理 --------------------------
    if exe_path.exists():
        print(f"\n✅ 打包成功！可执行文件已生成：{exe_path}")
        # 清理build目录（保持原始逻辑）
        build_dir = project_root / "build"
        try:
            if build_dir.exists() and build_dir.is_dir():
                shutil.rmtree(build_dir)
                print(f"✅ 已成功删除 build 文件夹：{build_dir}")
            else:
                print(f"⚠️  未找到 build 文件夹，无需清理")
        except Exception as e:
            print(f"❌ 清理 build 文件夹失败：{e}")
            print("⚠️  请手动清理 build 文件夹")
    else:
        raise RuntimeError(f"打包流程执行完成，但未找到可执行文件：{exe_path}\n实际dist目录结构：{list(project_root / 'dist').__str__()}")

except Exception as e:
    # -------------------------- 打包失败后处理 --------------------------
    print(f"\n❌ 打包失败！错误信息：{str(e)}")
    # 清理临时文件（保持原始逻辑）
    build_dir = project_root / "build"
    dist_root = project_root / "dist"

    # 清理build目录
    try:
        if build_dir.exists() and build_dir.is_dir():
            shutil.rmtree(build_dir)
            print(f"✅ 已删除 build 文件夹：{build_dir}")
        else:
            print(f"⚠️  未找到 build 文件夹，无需清理")
    except Exception as e1:
        print(f"❌ 清理 build 文件夹失败：{e1}")

    # 清理dist目录
    try:
        if dist_root.exists() and dist_root.is_dir():
            shutil.rmtree(dist_root)
            print(f"✅ 已删除 dist 文件夹：{dist_root}")
        else:
            print(f"⚠️  未找到 dist 文件夹，无需清理")
    except Exception as e2:
        print(f"❌ 清理 dist 文件夹失败：{e2}")

    print("\n❌ 打包失败，已清理残留文件，请排查错误后重试！")
    raise

print("\n📌 打包+清理流程全部结束！")