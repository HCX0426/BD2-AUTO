@echo off
:: packaging\build.bat - 用于自动化构建项目的批处理脚本
:: 此脚本应位于 packaging 目录下，并从这里执行

:: --- 配置区域 ---
:: 请根据你的实际情况修改以下变量

:: 1. 你的 .spec 文件名 (相对于 packaging 目录)
set SPEC_FILE=pyinstaller\main.spec

:: 2. 项目最终生成的可执行文件名 (通常与 EXE(name=...) 一致)
set PROJECT_NAME=BD2-AUTO

:: 3. Conda 环境配置 (使用环境名称)
::    - CONDA_BASE_PATH: 你的 Miniconda3 或 Anaconda3 的安装根目录
::    - CONDA_ENV_NAME: 你要激活的环境名称
set CONDA_BASE_PATH=C:\Users\hcx\miniconda3
set CONDA_ENV_NAME=bd2-auto-cpu

:: --- 配置区域结束 ---


:: --- 脚本执行区域 ---

:: 1. 清屏 (可选，让输出更清晰)
cls

:: 记录脚本启动时间和基本信息
echo **************************************************
echo * [BUILD] 批处理打包脚本开始执行              *
echo * 时间: %date% %time%                       *
echo **************************************************
echo.

:: 2. 激活 Conda 环境 (使用更稳健的手动 PATH 方法)
echo [INFO] 正在设置 Conda 环境变量以模拟激活...
:: 将 Conda 主目录和 Scripts 目录添加到 PATH 开头，确保能找到 conda 命令
set "PATH=%CONDA_BASE_PATH%;%CONDA_BASE_PATH%\Scripts;%PATH%"
:: 设置 CONDA_* 环境变量 (虽然是模拟，但设置上比较规范)
set "CONDA_DEFAULT_ENV=%CONDA_ENV_NAME%"
set "CONDA_PREFIX=%CONDA_BASE_PATH%\envs\%CONDA_ENV_NAME%"
:: (可选) 设置 PYTHONNOUSERSITE，防止用户站点包干扰打包环境
set "PYTHONNOUSERSITE=1"

:: 验证 Conda 命令是否可用
echo [CHECK] 检查 conda 命令是否可用...
conda --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 无法找到或执行 conda 命令。
    echo [ERROR] 请检查 CONDA_BASE_PATH 是否正确设置: %CONDA_BASE_PATH%
    echo [ERROR] 当前 PATH 的前缀是: %PATH:~0,100%...
    pause
    exit /b 1
)
echo [OK] Conda 命令可用 ^(版本: %ERRORLEVEL%^).

:: 验证 Conda 环境路径是否存在
echo [CHECK] 检查指定的 Conda 环境路径是否存在...
if not exist "%CONDA_PREFIX%" (
    echo [ERROR] 指定的 Conda 环境路径不存在。
    echo [ERROR] CONDA_BASE_PATH: %CONDA_BASE_PATH%
    echo [ERROR] CONDA_ENV_NAME: %CONDA_ENV_NAME%
    echo [ERROR] 推断的环境路径 CONDA_PREFIX: %CONDA_PREFIX%
    pause
    exit /b 1
)
echo [OK] Conda 环境路径存在。

:: 关键步骤：手动将 Conda 环境的根目录和 Scripts 目录添加到 PATH 开头
:: 这是模拟 `conda activate` 最核心的操作，使环境中的工具优先被调用
set "PATH=%CONDA_PREFIX%;%CONDA_PREFIX%\Scripts;%PATH%"
echo [INFO] Conda 环境已通过设置 PATH 模拟激活。

:: 验证：检查当前环境中 Python 的版本和路径
echo [CHECK] 验证当前环境 Python...
python.exe --version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] 无法执行 python.exe --version。可能 PATH 设置有问题。
) else (
    :: 获取 Python 完整路径进行核对
    for /f "delims=" %%p in ('where python.exe 2^>nul') do (
        set "ACTIVE_PYTHON=%%p"
        goto :found_python
    )
    :found_python
    if defined ACTIVE_PYTHON (
        echo [OK] 当前使用的 Python 路径: %ACTIVE_PYTHON%
        echo [OK] 当前使用的 Python 版本:
        python.exe --version
        :: 简单检查路径是否包含环境前缀 (不是100%严谨，但足够指示)
        echo %ACTIVE_PYTHON% | findstr /i /c:"%CONDA_ENV_NAME%" >nul
        if errorlevel 1 (
            echo [WARNING] Python 路径似乎不包含环境名称 '%CONDA_ENV_NAME%'，请检查 PATH 设置。
        ) else (
            echo [OK] Python 路径包含环境名称 '%CONDA_ENV_NAME%'。
        )
    ) else (
        echo [WARNING] 无法确定当前使用的 Python 路径。
    )
)
echo.

:: 3. 获取当前脚本所在目录 (即 packaging 目录)，然后切换到项目根目录 (上级目录)
set SCRIPT_DIR=%~dp0
echo [NAV] 正在切换到项目根目录...
cd /d "%SCRIPT_DIR%\.."
if errorlevel 1 (
    echo [ERROR] 无法切换到项目根目录: %SCRIPT_DIR%\..
    echo [ERROR] 当前目录: %CD%
    pause
    exit /b 1
)
set PROJECT_ROOT=%CD%
echo [OK] 已切换至项目根目录: %PROJECT_ROOT%
echo.

:: 4. 检查关键文件/目录是否存在，确保是正确的项目根目录
echo [CHECK] 校验项目根目录关键文件/目录...
if not exist "src" (
    echo [ERROR] 项目根目录下未找到 'src' 目录。
    echo [ERROR] 请确认脚本是否在正确的项目结构中运行。
    cd /d "%SCRIPT_DIR%"  :: 尝试切回去再退出
    pause
    exit /b 1
)
if not exist "main.py" (
    echo [ERROR] 项目根目录下未找到 'main.py' 入口文件。
    echo [ERROR] 请确认脚本是否在正确的项目根目录运行。
    cd /d "%SCRIPT_DIR%"  :: 尝试切回去再退出
    pause
    exit /b 1
)
echo [OK] 项目根目录校验通过。
echo.

:: 5. 准备执行 PyInstaller 打包命令
echo **************************************************
echo * [LOG] 即将开始 PyInstaller 打包过程...       *
echo **************************************************
echo [CONFIG] 项目名称: %PROJECT_NAME%
echo [CONFIG] Spec 文件 (相对路径): packaging\%SPEC_FILE%
:: 构造 .spec 文件的绝对路径用于验证和调用
set ABS_SPEC_PATH="%CD%\packaging\%SPEC_FILE%"
echo [CONFIG] Spec 文件 (绝对路径): %ABS_SPEC_PATH%
if not exist %ABS_SPEC_PATH% (
    echo [ERROR] Spec 文件不存在于指定路径。
    cd /d "%SCRIPT_DIR%"  :: 切回去再退出
    pause
    exit /b 1
)
echo [OK] Spec 文件存在。
echo.

:: 6. 执行 PyInstaller 打包命令
echo [EXEC] 正在调用 PyInstaller...
echo [EXEC] 命令: pyinstaller --noconfirm %ABS_SPEC_PATH%
echo **************************************************
pyinstaller --noconfirm %ABS_SPEC_PATH%

:: 7. 检查打包是否成功
set BUILD_SUCCESS=0
if %errorlevel% == 0 (
    set BUILD_SUCCESS=1
    echo.
    echo **************************************************
    echo *                                                *
    echo *  [SUCCESS] *** 打包成功完成! ***               *
    echo *                                                *
    echo *  可执行文件位于:                               *
    echo *    dist\%PROJECT_NAME%                         *
    echo *                                                *
    echo **************************************************
    echo [END] 成功时间: %date% %time%
    echo.
) else (
    set BUILD_SUCCESS=0
    echo.
    echo **************************************************
    echo *                                                *
    echo *  [FAILURE] *** 打包过程失败! ***               *
    echo *                                                *
    echo *  错误码: %errorlevel%                          *
    echo *  请仔细检查上方 PyInstaller 输出以定位问题。     *
    echo *                                                *
    echo **************************************************
    echo [END] 失败时间: %date% %time%
    echo.
    :: ========== 失败时清理 ==========
    echo [CLEANUP] 打包失败，正在尝试清理 dist 和 build 文件夹...
    if exist "dist" (
        echo [CLEANUP] 删除 dist 文件夹...
        rd /s /q "dist" >nul 2>&1
        if errorlevel 1 (
            echo [WARNING] 清理 dist 文件夹失败 (可能被占用)。
        ) else (
            echo [CLEANUP] dist 文件夹已成功删除。
        )
    ) else (
        echo [CLEANUP] dist 文件夹不存在，无需清理。
    )
    if exist "build" (
        echo [CLEANUP] 删除 build 文件夹...
        rd /s /q "build" >nul 2>&1
        if errorlevel 1 (
           echo [WARNING] 清理 build 文件夹失败 (可能被占用)。
        ) else (
            echo [CLEANUP] build 文件夹已成功删除。
        )
    ) else (
        echo [CLEANUP] build 文件夹不存在，无需清理。
    )
    echo [CLEANUP] 失败清理操作已完成。
    echo.
    :: ========== 清理结束 ==========
)

:: 8. 恢复到脚本所在的 packaging 目录 (可选，但推荐，保持环境整洁)
cd /d "%SCRIPT_DIR%"
if errorlevel 1 (
    echo [WARNING] 无法恢复到脚本原始目录: %SCRIPT_DIR%
) else (
    echo [NAV] 已恢复到脚本原始目录: %CD%
)

:: 9. 结束
echo **************************************************
echo * [BUILD] 批处理打包脚本执行结束                *
echo * 状态: %BUILD_SUCCESS% (0=失败, 1=成功)          *
echo **************************************************
pause