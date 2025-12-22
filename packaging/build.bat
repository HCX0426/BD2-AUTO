@echo off
:: 打包脚本（仅负责环境准备和调用打包，核心逻辑由 spec 文件处理）
setlocal enabledelayedexpansion

:: --- 配置区域 ---
set SPEC_FILE=pyinstaller\main.spec
set CONDA_BASE_PATH=C:\Users\hcx\miniconda3
set CONDA_ENV_NAME=bd2-auto-cpu
:: --- 配置区域结束 ---
if not "%1"=="" set CONDA_ENV_NAME=%1
if not "%2"=="" set SPEC_FILE=%2

:: 日志文件（保留，用于追溯执行记录）
set "LOG_DATE=%date:~0,4%%date:~5,2%%date:~8,2%"
set "LOG_TIME=%time:~0,2%%time:~3,2%%time:~6,2%"
set "LOG_TIME=%LOG_TIME: =0%"
set LOG_FILE="%~dp0build_log_%LOG_DATE%_%LOG_TIME%.txt"

:: 清屏+启动信息
cls
echo **************************************************
echo * [BUILD] 批处理打包脚本开始执行              *
echo * 时间: %date% %time%                       *
echo * 日志文件: %LOG_FILE%                      *
echo * 核心逻辑：请查看 spec 文件输出结果          *
echo **************************************************
echo.

:: 1. 激活Conda环境
set "PATH=%CONDA_BASE_PATH%\envs\%CONDA_ENV_NAME%;%CONDA_BASE_PATH%\envs\%CONDA_ENV_NAME%\Scripts;%PATH%"
set "CONDA_PREFIX=%CONDA_BASE_PATH%\envs\%CONDA_ENV_NAME%"
set "PYTHONNOUSERSITE=1"

:: 2. 验证依赖（Python + PyInstaller）
python --version >nul 2>&1 || (echo [ERROR] 未找到Python！& pause & exit /b 1)
pyinstaller --version >nul 2>&1 || (echo [ERROR] 未安装pyinstaller！& pause & exit /b 1)

:: 3. 切换到项目根目录
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%\.." || (echo [ERROR] 切换根目录失败！& pause & exit /b 1)
set PROJECT_ROOT=%CD%
echo [OK] 项目根目录：%PROJECT_ROOT%
echo.

:: 4. 验证spec文件
set ABS_SPEC_PATH="%PROJECT_ROOT%\packaging\%SPEC_FILE%"
if not exist %ABS_SPEC_PATH% (echo [ERROR] spec文件不存在！& pause & exit /b 1)
echo [OK] spec文件存在：%ABS_SPEC_PATH%
echo.

:: 5. 执行PyInstaller（不重定向日志，直接显示 spec 的完整输出）
echo **************************************************
echo [EXEC] 开始调用打包（核心逻辑由 spec 处理）...
echo 命令：pyinstaller --noconfirm %ABS_SPEC_PATH%
echo **************************************************
echo.
pyinstaller --noconfirm %ABS_SPEC_PATH%

:: 6. 结束（仅保留暂停，让用户查看 spec 的输出结果）
echo.
echo **************************************************
echo * [BUILD] 批处理脚本执行完毕                  *
echo * 打包结果、清理状态请查看上方 spec 输出日志    *
echo * 执行记录已保存到：%LOG_FILE%                *
echo **************************************************