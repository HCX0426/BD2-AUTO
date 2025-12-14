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
:: 支持命令行参数覆盖配置（第1个参数=环境名，第2个参数=spec文件路径）
if not "%1"=="" set CONDA_ENV_NAME=%1
if not "%2"=="" set SPEC_FILE=%2

:: --- 脚本执行区域 ---
:: 初始化日志文件（按时间命名，避免覆盖）
set "LOG_DATE=%date:~0,4%%date:~5,2%%date:~8,2%"
set "LOG_TIME=%time:~0,2%%time:~3,2%%time:~6,2%"
:: 处理时间前缀空格（如 9:05 转为 0905）
set "LOG_TIME=%LOG_TIME: =0%"
set LOG_FILE="%~dp0build_log_%LOG_DATE%_%LOG_TIME%.txt"

:: 1. 清屏 (可选，让输出更清晰)
cls

:: 记录脚本启动时间和基本信息（同时写入日志）
echo **************************************************
echo ************************************************** >> %LOG_FILE%
echo * [BUILD] 批处理打包脚本开始执行              *
echo * [BUILD] 批处理打包脚本开始执行              * >> %LOG_FILE%
echo * 时间: %date% %time%                       *
echo * 时间: %date% %time%                       * >> %LOG_FILE%
echo * 日志文件: %LOG_FILE%                      *
echo * 日志文件: %LOG_FILE%                      * >> %LOG_FILE%
echo **************************************************
echo ************************************************** >> %LOG_FILE%
echo.
echo. >> %LOG_FILE%

:: 2. 激活 Conda 环境 (优化 PATH 顺序，确保环境优先级最高)
echo [INFO] 正在设置 Conda 环境变量以模拟激活...
echo [INFO] 正在设置 Conda 环境变量以模拟激活... >> %LOG_FILE%
:: 核心优化：环境目录优先于根目录，避免使用根目录Python
set "PATH=%CONDA_PREFIX%;%CONDA_PREFIX%\Scripts;%CONDA_BASE_PATH%;%CONDA_BASE_PATH%\Scripts;%PATH%"
:: 设置 CONDA_* 环境变量（规范配置）
set "CONDA_DEFAULT_ENV=%CONDA_ENV_NAME%"
set "CONDA_PREFIX=%CONDA_BASE_PATH%\envs\%CONDA_ENV_NAME%"
:: 防止用户站点包干扰打包环境
set "PYTHONNOUSERSITE=1"

:: 验证 Conda 命令是否可用（修复版本号捕获）
echo [CHECK] 检查 conda 命令是否可用...
echo [CHECK] 检查 conda 命令是否可用... >> %LOG_FILE%
conda --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 无法找到或执行 conda 命令。
    echo [ERROR] 无法找到或执行 conda 命令。 >> %LOG_FILE%
    echo [ERROR] 请检查 CONDA_BASE_PATH 是否正确设置: %CONDA_BASE_PATH%
    echo [ERROR] 请检查 CONDA_BASE_PATH 是否正确设置: %CONDA_BASE_PATH% >> %LOG_FILE%
    echo [ERROR] 当前 PATH 的前缀是: %PATH:~0,100%...
    echo [ERROR] 当前 PATH 的前缀是: %PATH:~0,100%... >> %LOG_FILE%
    pause
    exit /b 1
)
:: 捕获真实 Conda 版本号
for /f "delims=" %%v in ('conda --version 2^>nul') do (
    set "CONDA_VERSION=%%v"
)
echo [OK] Conda 命令可用 ^(版本: %CONDA_VERSION%^).
echo [OK] Conda 命令可用 ^(版本: %CONDA_VERSION%^). >> %LOG_FILE%

:: 验证 Conda 环境路径是否存在
echo [CHECK] 检查指定的 Conda 环境路径是否存在...
echo [CHECK] 检查指定的 Conda 环境路径是否存在... >> %LOG_FILE%
if not exist "%CONDA_PREFIX%" (
    echo [ERROR] 指定的 Conda 环境路径不存在。
    echo [ERROR] 指定的 Conda 环境路径不存在。 >> %LOG_FILE%
    echo [ERROR] CONDA_BASE_PATH: %CONDA_BASE_PATH%
    echo [ERROR] CONDA_BASE_PATH: %CONDA_BASE_PATH% >> %LOG_FILE%
    echo [ERROR] CONDA_ENV_NAME: %CONDA_ENV_NAME%
    echo [ERROR] CONDA_ENV_NAME: %CONDA_ENV_NAME% >> %LOG_FILE%
    echo [ERROR] 推断的环境路径 CONDA_PREFIX: %CONDA_PREFIX%
    echo [ERROR] 推断的环境路径 CONDA_PREFIX: %CONDA_PREFIX% >> %LOG_FILE%
    pause
    exit /b 1
)
echo [OK] Conda 环境路径存在。
echo [OK] Conda 环境路径存在。 >> %LOG_FILE%

:: 验证：检查当前环境中 Python 的版本和路径（优化路径过滤）
echo [CHECK] 验证当前环境 Python...
echo [CHECK] 验证当前环境 Python... >> %LOG_FILE%
python.exe --version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] 无法执行 python.exe --version。可能 PATH 设置有问题。
    echo [WARNING] 无法执行 python.exe --version。可能 PATH 设置有问题。 >> %LOG_FILE%
) else (
    :: 过滤包含环境名称的 Python 路径，确保是目标环境
    set "ACTIVE_PYTHON="
    for /f "delims=" %%p in ('where python.exe 2^>nul ^| findstr /i /c:"%CONDA_ENV_NAME%"') do (
        set "ACTIVE_PYTHON=%%p"
        goto :found_python
    )
    :found_python
    if defined ACTIVE_PYTHON (
        echo [OK] 当前使用的 Python 路径: %ACTIVE_PYTHON%
        echo [OK] 当前使用的 Python 路径: %ACTIVE_PYTHON% >> %LOG_FILE%
        echo [OK] 当前使用的 Python 版本:
        echo [OK] 当前使用的 Python 版本: >> %LOG_FILE%
        python.exe --version
        python.exe --version >> %LOG_FILE%
        :: 验证路径包含环境名称
        echo %ACTIVE_PYTHON% | findstr /i /c:"%CONDA_ENV_NAME%" >nul
        if errorlevel 1 (
            echo [WARNING] Python 路径似乎不包含环境名称 '%CONDA_ENV_NAME%'，请检查 PATH 设置。
            echo [WARNING] Python 路径似乎不包含环境名称 '%CONDA_ENV_NAME%'，请检查 PATH 设置。 >> %LOG_FILE%
        ) else (
            echo [OK] Python 路径包含环境名称 '%CONDA_ENV_NAME%'。
            echo [OK] Python 路径包含环境名称 '%CONDA_ENV_NAME%'。 >> %LOG_FILE%
        )
    ) else (
        echo [WARNING] 未找到包含环境名称 '%CONDA_ENV_NAME%' 的 Python 路径，请检查 PATH 设置！
        echo [WARNING] 未找到包含环境名称 '%CONDA_ENV_NAME%' 的 Python 路径，请检查 PATH 设置！ >> %LOG_FILE%
    )
)
echo.
echo. >> %LOG_FILE%

:: 3. 获取当前脚本所在目录 (即 packaging 目录)，然后切换到项目根目录 (上级目录)
set SCRIPT_DIR=%~dp0
echo [NAV] 正在切换到项目根目录...
echo [NAV] 正在切换到项目根目录... >> %LOG_FILE%
cd /d "%SCRIPT_DIR%\.."
if errorlevel 1 (
    echo [ERROR] 无法切换到项目根目录: %SCRIPT_DIR%\..
    echo [ERROR] 无法切换到项目根目录: %SCRIPT_DIR%\.. >> %LOG_FILE%
    echo [ERROR] 当前目录: %CD%
    echo [ERROR] 当前目录: %CD% >> %LOG_FILE%
    pause
    exit /b 1
)
set PROJECT_ROOT=%CD%
echo [OK] 已切换至项目根目录: %PROJECT_ROOT%
echo [OK] 已切换至项目根目录: %PROJECT_ROOT% >> %LOG_FILE%
echo.
echo. >> %LOG_FILE%

:: 4. 检查关键文件/目录是否存在，确保是正确的项目根目录
echo [CHECK] 校验项目根目录关键文件/目录...
echo [CHECK] 校验项目根目录关键文件/目录... >> %LOG_FILE%
if not exist "src" (
    echo [ERROR] 项目根目录下未找到 'src' 目录。
    echo [ERROR] 项目根目录下未找到 'src' 目录。 >> %LOG_FILE%
    echo [ERROR] 请确认脚本是否在正确的项目结构中运行。
    echo [ERROR] 请确认脚本是否在正确的项目结构中运行。 >> %LOG_FILE%
    cd /d "%SCRIPT_DIR%"  :: 尝试切回去再退出
    pause
    exit /b 1
)
if not exist "main.py" (
    echo [ERROR] 项目根目录下未找到 'main.py' 入口文件。
    echo [ERROR] 项目根目录下未找到 'main.py' 入口文件。 >> %LOG_FILE%
    echo [ERROR] 请确认脚本是否在正确的项目根目录运行。
    echo [ERROR] 请确认脚本是否在正确的项目根目录运行。 >> %LOG_FILE%
    cd /d "%SCRIPT_DIR%"  :: 尝试切回去再退出
    pause
    exit /b 1
)
echo [OK] 项目根目录校验通过。
echo [OK] 项目根目录校验通过。 >> %LOG_FILE%
echo.
echo. >> %LOG_FILE%

:: 5. 检查 pyinstaller 是否安装（新增优化）
echo [CHECK] 检查 pyinstaller 是否安装...
echo [CHECK] 检查 pyinstaller 是否安装... >> %LOG_FILE%
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 环境中未安装 pyinstaller！请先执行: pip install pyinstaller
    echo [ERROR] 环境中未安装 pyinstaller！请先执行: pip install pyinstaller >> %LOG_FILE%
    cd /d "%SCRIPT_DIR%"
    pause
    exit /b 1
) else (
    for /f "delims=" %%v in ('pyinstaller --version 2^>nul') do (
        set "PYINSTALLER_VERSION=%%v"
    )
    echo [OK] pyinstaller 已安装 ^(版本: %PYINSTALLER_VERSION%^).
    echo [OK] pyinstaller 已安装 ^(版本: %PYINSTALLER_VERSION%^). >> %LOG_FILE%
)
echo.
echo. >> %LOG_FILE%

:: 6. 准备执行 PyInstaller 打包命令
echo **************************************************
echo ************************************************** >> %LOG_FILE%
echo * [LOG] 即将开始 PyInstaller 打包过程...       *
echo * [LOG] 即将开始 PyInstaller 打包过程...       * >> %LOG_FILE%
echo **************************************************
echo ************************************************** >> %LOG_FILE%
echo [CONFIG] 项目名称: %PROJECT_NAME%
echo [CONFIG] 项目名称: %PROJECT_NAME% >> %LOG_FILE%
echo [CONFIG] Spec 文件 (相对路径): packaging\%SPEC_FILE%
echo [CONFIG] Spec 文件 (相对路径): packaging\%SPEC_FILE% >> %LOG_FILE%
:: 构造 .spec 文件的绝对路径用于验证和调用
set ABS_SPEC_PATH="%CD%\packaging\%SPEC_FILE%"
echo [CONFIG] Spec 文件 (绝对路径): %ABS_SPEC_PATH%
echo [CONFIG] Spec 文件 (绝对路径): %ABS_SPEC_PATH% >> %LOG_FILE%
if not exist %ABS_SPEC_PATH% (
    echo [ERROR] Spec 文件不存在于指定路径。
    echo [ERROR] Spec 文件不存在于指定路径。 >> %LOG_FILE%
    cd /d "%SCRIPT_DIR%"  :: 切回去再退出
    pause
    exit /b 1
)
echo [OK] Spec 文件存在。
echo [OK] Spec 文件存在。 >> %LOG_FILE%
echo.
echo. >> %LOG_FILE%

:: 7. 执行 PyInstaller 打包命令（输出写入日志）
echo [EXEC] 正在调用 PyInstaller...
echo [EXEC] 正在调用 PyInstaller... >> %LOG_FILE%
echo [EXEC] 命令: pyinstaller --noconfirm %ABS_SPEC_PATH%
echo [EXEC] 命令: pyinstaller --noconfirm %ABS_SPEC_PATH% >> %LOG_FILE%
echo **************************************************
echo ************************************************** >> %LOG_FILE%
pyinstaller --noconfirm %ABS_SPEC_PATH% >> %LOG_FILE% 2>&1

:: 8. 检查打包是否成功
set BUILD_SUCCESS=0
if %errorlevel% == 0 (
    set BUILD_SUCCESS=1
    echo.
    echo. >> %LOG_FILE%
    echo **************************************************
    echo ************************************************** >> %LOG_FILE%
    echo *                                                *
    echo *                                                * >> %LOG_FILE%
    echo *  [SUCCESS] *** 打包成功完成! ***               *
    echo *  [SUCCESS] *** 打包成功完成! ***               * >> %LOG_FILE%
    echo *                                                *
    echo *                                                * >> %LOG_FILE%
    echo *  可执行文件位于:                               *
    echo *  可执行文件位于:                               * >> %LOG_FILE%
    echo *    %PROJECT_ROOT%\dist\%PROJECT_NAME%          *
    echo *    %PROJECT_ROOT%\dist\%PROJECT_NAME%          * >> %LOG_FILE%
    echo *                                                *
    echo *                                                * >> %LOG_FILE%
    echo **************************************************
    echo ************************************************** >> %LOG_FILE%
    echo [END] 成功时间: %date% %time%
    echo [END] 成功时间: %date% %time% >> %LOG_FILE%
    echo.
    echo. >> %LOG_FILE%
) else (
    set BUILD_SUCCESS=0
    echo.
    echo. >> %LOG_FILE%
    echo **************************************************
    echo ************************************************** >> %LOG_FILE%
    echo *                                                *
    echo *                                                * >> %LOG_FILE%
    echo *  [FAILURE] *** 打包过程失败! ***               *
    echo *  [FAILURE] *** 打包过程失败! ***               * >> %LOG_FILE%
    echo *                                                *
    echo *                                                * >> %LOG_FILE%
    echo *  错误码: %errorlevel%                          *
    echo *  错误码: %errorlevel%                          * >> %LOG_FILE%
    echo *  请查看日志文件排查问题: %LOG_FILE%            *
    echo *  请查看日志文件排查问题: %LOG_FILE%            * >> %LOG_FILE%
    echo *                                                *
    echo *                                                * >> %LOG_FILE%
    echo **************************************************
    echo ************************************************** >> %LOG_FILE%
    echo [END] 失败时间: %date% %time%
    echo [END] 失败时间: %date% %time% >> %LOG_FILE%
    echo.
    echo. >> %LOG_FILE%
    :: ========== 失败时清理（优化清理逻辑，补充缓存和临时文件） ==========
    echo [CLEANUP] 打包失败，正在尝试清理生成文件...
    echo [CLEANUP] 打包失败，正在尝试清理生成文件... >> %LOG_FILE%
    :: 清理 dist 文件夹
    if exist "dist" (
        echo [CLEANUP] 删除 dist 文件夹...
        echo [CLEANUP] 删除 dist 文件夹... >> %LOG_FILE%
        rd /s /q "dist" >nul 2>&1
        if errorlevel 1 (
            echo [WARNING] 清理 dist 文件夹失败 (可能被其他程序占用，请手动删除)。
            echo [WARNING] 清理 dist 文件夹失败 (可能被其他程序占用，请手动删除)。 >> %LOG_FILE%
        ) else (
            echo [CLEANUP] dist 文件夹已成功删除。
            echo [CLEANUP] dist 文件夹已成功删除。 >> %LOG_FILE%
        )
    ) else (
        echo [CLEANUP] dist 文件夹不存在，无需清理。
        echo [CLEANUP] dist 文件夹不存在，无需清理。 >> %LOG_FILE%
    )
    :: 清理 build 文件夹
    if exist "build" (
        echo [CLEANUP] 删除 build 文件夹...
        echo [CLEANUP] 删除 build 文件夹... >> %LOG_FILE%
        rd /s /q "build" >nul 2>&1
        if errorlevel 1 (
           echo [WARNING] 清理 build 文件夹失败 (可能被其他程序占用，请手动删除)。
           echo [WARNING] 清理 build 文件夹失败 (可能被其他程序占用，请手动删除)。 >> %LOG_FILE%
        ) else (
            echo [CLEANUP] build 文件夹已成功删除。
            echo [CLEANUP] build 文件夹已成功删除。 >> %LOG_FILE%
        )
    ) else (
        echo [CLEANUP] build 文件夹不存在，无需清理。
        echo [CLEANUP] build 文件夹不存在，无需清理。 >> %LOG_FILE%
    )
    :: 清理 __pycache__ 缓存目录
    echo [CLEANUP] 清理 __pycache__ 缓存目录...
    echo [CLEANUP] 清理 __pycache__ 缓存目录... >> %LOG_FILE%
    for /d /r "." %%d in (__pycache__) do (
        if exist "%%d" (
            rd /s /q "%%d" >nul 2>&1
            echo [CLEANUP] 删除缓存目录: %%d
            echo [CLEANUP] 删除缓存目录: %%d >> %LOG_FILE%
        )
    )
    :: 清理 PyInstaller 临时文件
    if exist "%PROJECT_NAME%.exe.manifest" (
        del /f /q "%PROJECT_NAME%.exe.manifest" >nul 2>&1
        echo [CLEANUP] 删除临时文件: %PROJECT_NAME%.exe.manifest
        echo [CLEANUP] 删除临时文件: %PROJECT_NAME%.exe.manifest >> %LOG_FILE%
    )
    if exist "%PROJECT_NAME%.spec" (
        del /f /q "%PROJECT_NAME%.spec" >nul 2>&1
        echo [CLEANUP] 删除临时文件: %PROJECT_NAME%.spec
        echo [CLEANUP] 删除临时文件: %PROJECT_NAME%.spec >> %LOG_FILE%
    )
    echo [CLEANUP] 失败清理操作已完成。
    echo [CLEANUP] 失败清理操作已完成。 >> %LOG_FILE%
    echo.
    echo. >> %LOG_FILE%
    :: ========== 清理结束 ==========
)

:: 9. 恢复到脚本所在的 packaging 目录
cd /d "%SCRIPT_DIR%"
if errorlevel 1 (
    echo [WARNING] 无法恢复到脚本原始目录: %SCRIPT_DIR%
    echo [WARNING] 无法恢复到脚本原始目录: %SCRIPT_DIR% >> %LOG_FILE%
) else (
    echo [NAV] 已恢复到脚本原始目录: %CD%
    echo [NAV] 已恢复到脚本原始目录: %CD% >> %LOG_FILE%
)

:: 10. 结束
echo **************************************************
echo ************************************************** >> %LOG_FILE%
echo * [BUILD] 批处理打包脚本执行结束                *
echo * [BUILD] 批处理打包脚本执行结束                * >> %LOG_FILE%
echo * 状态: %BUILD_SUCCESS% (0=失败, 1=成功)          *
echo * 状态: %BUILD_SUCCESS% (0=失败, 1=成功)          * >> %LOG_FILE%
echo * 日志文件: %LOG_FILE%                          *
echo * 日志文件: %LOG_FILE%                          * >> %LOG_FILE%
echo **************************************************
echo ************************************************** >> %LOG_FILE%
pause