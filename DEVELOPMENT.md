# BD2-AUTO 开发者文档

本文档为BD2-AUTO项目的开发者提供开发环境搭建、代码结构和贡献指南。

## 项目概述

BD2-AUTO是一个基于PyQt6开发的BD2游戏自动化工具，使用OCR进行图像识别，支持多种自动化任务。

## 技术栈

- **Python 3.12**：主要开发语言
- **PyQt6**：GUI框架
- **PyInstaller**：打包工具
- **EasyOCR**：图像识别
- **OpenCV**：图像处理
- **PyTorch**：深度学习框架（EasyOCR依赖）
- **pywin32**：Windows系统API访问

## 开发环境搭建

### 1. 克隆仓库

```bash
git clone https://github.com/yourusername/BD2-AUTO.git
cd BD2-AUTO
```

### 2. 创建虚拟环境

#### 使用Conda（推荐）

```bash
conda create -n bd2-auto python=3.12
conda activate bd2-auto
```

#### 使用venv

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements/dev.txt
```

### 4. 安装开发工具

```bash
pip install pyinstaller black flake8 mypy
```

### 5. 准备OCR模型

首次运行时会自动下载模型，或者手动下载：

```bash
mkdir -p runtime/dev/ocr_models
# 下载模型文件到该目录
# craft_mlt_25k.pth - 检测模型
# zh_sim_g2.pth - 简体中文识别模型
```

## 代码结构

```
BD2-AUTO/
├── src/                  # 源代码目录
│   ├── auto_control/     # 自动控制核心
│   │   ├── config/       # 控制模块配置
│   │   │   ├── auto_config.py     # 自动控制配置
│   │   │   └── ocr_config.py      # OCR识别配置
│   │   ├── core/         # 核心控制逻辑
│   │   │   └── auto.py            # 控制核心类
│   │   ├── devices/      # 设备管理
│   │   │   ├── adb_device.py      # ADB设备控制（预留）
│   │   │   ├── base_device.py     # 设备控制基类
│   │   │   ├── device_manager.py  # 设备管理器
│   │   │   └── windows_device.py  # Windows设备控制实现
│   │   ├── image/        # 图像处理
│   │   │   └── image_processor.py # 图像处理功能
│   │   ├── ocr/          # OCR识别
│   │   │   ├── base_ocr.py        # OCR基类
│   │   │   ├── easyocr_wrapper.py # EasyOCR封装
│   │   │   └── ocr_processor.py   # OCR识别功能
│   │   └── utils/        # 工具函数
│   │       ├── coordinate_transformer.py # 坐标转换工具
│   │       ├── debug_image_saver.py      # 调试图像保存工具
│   │       ├── display_context.py        # 显示上下文工具
│   │       └── logger.py                 # 日志工具
│   ├── auto_tasks/       # 自动化任务模块
│   │   ├── pc/           # PC端任务
│   │   │   ├── templates/# 任务模板图像
│   │   │   │   ├── get_email/           # 获取邮件模板
│   │   │   │   ├── get_guild/           # 公会任务模板
│   │   │   │   ├── get_pvp/             # PVP任务模板
│   │   │   │   ├── get_restaurant/      # 餐厅任务模板
│   │   │   │   ├── intensive_decomposition/ # 强化分解模板
│   │   │   │   ├── login/               # 登录模板
│   │   │   │   ├── lucky_draw/          # 抽奖模板
│   │   │   │   ├── map_collection/      # 地图收集模板
│   │   │   │   ├── pass_activity/       # 通行证活动模板
│   │   │   │   ├── pass_rewards/        # 通行证奖励模板
│   │   │   │   ├── public/              # 公共模板
│   │   │   │   └── sweep_daily/         # 日常扫荡模板
│   │   │   ├── daily_missions.py        # 日常任务实现
│   │   │   ├── get_email.py             # 获取邮件任务实现
│   │   │   ├── get_guild.py             # 公会任务实现
│   │   │   ├── get_pvp.py               # PVP任务实现
│   │   │   ├── get_restaurant.py        # 餐厅任务实现
│   │   │   ├── intensive_decomposition.py # 强化分解任务实现
│   │   │   ├── login.py                 # 登录任务实现
│   │   │   ├── lucky_draw.py            # 抽奖任务实现
│   │   │   ├── map_collection.py        # 地图收集任务实现
│   │   │   ├── pass_activity.py         # 通行证活动任务实现
│   │   │   ├── pass_rewards.py          # 通行证奖励任务实现
│   │   │   ├── public.py                # 公共任务工具
│   │   │   └── sweep_daily.py           # 日常扫荡任务实现
│   │   └── utils/        # 任务工具模块
│   │       └── roi_config.py            # ROI配置管理
│   ├── core/             # 核心功能模块
│   │   ├── path_manager.py  # 路径管理
│   │   └── task_manager.py  # 任务管理
│   └── entrypoints/      # 程序入口点
│       └── main_window.py  # GUI窗口
├── config/               # 配置文件
│   ├── dev/              # 开发环境配置
│   │   ├── app_settings.json  # 应用设置
│   │   ├── rois.json          # ROI配置
│   │   └── settings.json      # 主配置文件
│   └── prod/             # 生产环境配置
│       ├── app_settings.json  # 应用设置
│       └── settings.json      # 主配置文件
├── packaging/            # 打包配置
│   ├── pyinstaller/      # PyInstaller打包配置
│   │   └── main.spec     # PyInstaller打包规范
│   └── build.bat         # 打包脚本
├── requirements/         # 依赖配置
│   └── dev.txt           # 开发环境依赖
├── runtime/              # 运行时文件
│   └── dev/              # 开发环境运行时
│       └── ocr_models/   # OCR模型文件
├── .github/workflows/    # GitHub Actions工作流
│   └── build.yml         # 自动构建和发布工作流
├── .gitignore            # Git忽略文件
├── console_test.py       # 控制台测试文件
├── description_env.txt   # 环境描述文件
├── DEVELOPMENT.md        # 开发者文档
├── main.py               # 项目主入口
└── README.md             # 用户文档
```

## 核心模块说明

### 1. 自动控制核心（auto_control）

自动控制核心是项目的核心执行层，负责处理所有自动化操作。

- **config/**：
  - **auto_config.py**：自动控制的核心配置，定义了执行流程、延迟时间等参数
  - **ocr_config.py**：OCR识别的配置，包括模型路径、识别语言等设置

- **core/**：
  - **auto.py**：控制核心类，负责任务的调度、执行和管理

- **devices/**：
  - **base_device.py**：设备控制的抽象基类，定义了设备操作的标准接口
  - **windows_device.py**：Windows设备的具体实现，使用pywin32访问系统API
  - **device_manager.py**：设备管理器，用于管理和切换不同类型的设备
  - **adb_device.py**：预留的ADB设备控制实现，用于未来扩展到移动平台

- **image/**：
  - **image_processor.py**：图像处理功能，包括截图、图像匹配、模板识别等

- **ocr/**：
  - **base_ocr.py**：OCR识别的抽象基类，定义了OCR操作的标准接口
  - **easyocr_wrapper.py**：EasyOCR的封装实现，提供图像文本识别功能
  - **ocr_processor.py**：OCR识别的高级接口，整合了多种识别策略

- **utils/**：
  - **coordinate_transformer.py**：坐标转换工具，用于处理不同分辨率下的坐标映射
  - **debug_image_saver.py**：调试图像保存工具，用于开发和调试时保存中间图像
  - **display_context.py**：显示上下文工具，用于管理和操作显示设备
  - **logger.py**：日志工具，提供统一的日志记录功能

### 2. 任务管理（core/task_manager）

任务管理模块负责任务的动态加载、配置管理和设置存储。

- **path_manager.py**：路径管理工具，提供统一的路径获取接口，适配开发和打包环境
- **task_manager.py**：
  - **load_task_modules()**：动态加载任务模块，自动发现和注册新任务
  - **TaskConfigManager**：任务配置管理，负责任务配置的加载和保存
  - **AppSettingsManager**：应用设置管理，负责应用级设置的加载和保存

### 3. 自动化任务（auto_tasks）

自动化任务模块包含了所有具体的游戏任务实现。

- **pc/**：PC端游戏任务实现，包括登录、日常任务、竞技场等
- **utils/roi_config.py**：ROI（感兴趣区域）配置管理，用于定义游戏界面上的关键区域

### 4. GUI界面（entrypoints/main_window）

GUI界面模块提供了用户与自动化系统交互的界面。

- **main_window.py**：主窗口类，负责处理用户交互、显示任务状态和控制自动化流程

## 开发流程

### 1. 运行项目

#### GUI模式

```bash
python main.py
```

#### 控制台测试模式

```bash
python console_test.py
```

控制台测试模式用于快速测试和调试单个功能，无需启动GUI。

### 2. 添加新任务

1. 在`src/auto_tasks/pc/`目录下创建新的任务模块（例如：`new_task.py`）
2. 实现任务逻辑，遵循现有任务的结构和命名规范
3. 添加任务模板图像到`templates/new_task/`目录
4. 在任务模块中定义任务步骤和图像识别逻辑
5. 任务会自动被`load_task_modules()`函数加载到GUI中

### 3. 配置管理

项目使用JSON格式的配置文件，位于`config/`目录下：

- `app_settings.json`：应用界面和行为设置
- `rois.json`：感兴趣区域（ROI）配置
- `settings.json`：主配置文件，包含所有核心参数

### 4. 代码规范

- 使用Black进行代码格式化：`black src/`
- 使用Flake8进行代码检查：`flake8 src/`
- 使用mypy进行类型检查：`mypy src/`

### 5. 打包测试

#### 使用打包脚本（Windows）

```bash
cd packaging
build.bat

# 或指定环境名称和spec文件
cd packaging
build.bat my-conda-env pyinstaller/my.spec
```

#### 手动打包

```bash
pyinstaller --noconfirm packaging/pyinstaller/main.spec
```

### 6. 自动化构建与发布

项目使用GitHub Actions自动构建和发布：

1. 在GitHub上创建新的Release
2. 触发`build.yml`工作流
3. 工作流自动执行以下步骤：
   - 安装依赖
   - 准备OCR模型
   - 使用PyInstaller构建
   - 上传构建结果到Release

详细配置请查看`.github/workflows/build.yml`文件。

## 贡献指南

### 1. 提交代码

1. **Fork项目仓库**：在GitHub上Fork项目到你的个人账号
2. **克隆仓库**：将Fork后的仓库克隆到本地
   ```bash
   git clone https://github.com/yourusername/BD2-AUTO.git
   cd BD2-AUTO
   ```
3. **创建特性分支**：从main分支创建新的特性分支
   ```bash
   git checkout -b feature/your-feature-name
   ```
4. **提交代码**：确保代码符合项目规范，然后提交
   ```bash
   git add .
   git commit -m "清晰描述你的修改内容"
   ```
5. **推送到分支**：将本地分支推送到GitHub
   ```bash
   git push origin feature/your-feature-name
   ```
6. **创建Pull Request**：在GitHub上创建Pull Request，描述你的修改内容和目的

### 2. 代码审查

- 确保代码符合项目的代码规范
- 提供清晰、详细的提交信息
- 包含必要的文档更新
- 确保所有修改都经过测试
- 避免一次性提交过多不相关的修改

### 3. 发布流程

1. **更新版本号**：在相关文件中更新版本号（如果需要）
2. **完善CHANGELOG**：记录所有重要的修改和新功能
3. **创建Release标签**：
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
4. **发布Release**：在GitHub上发布Release，GitHub Actions会自动构建并上传发布包

## 常见问题

### 1. OCR模型下载失败

手动下载模型文件并放置到`runtime/dev/ocr_models/`目录：
- 检测模型：craft_mlt_25k.pth
- 识别模型：zh_sim_g2.pth

模型可以从EasyOCR的官方GitHub仓库或模型托管平台下载。

### 2. 打包失败

- 确保所有依赖已正确安装：`pip install -r requirements/dev.txt`
- 确保OCR模型文件存在
- 检查PyInstaller版本是否兼容
- 查看打包日志以获取详细错误信息

### 3. 任务执行失败

- 确保游戏窗口在前台且未被遮挡
- 检查游戏分辨率是否符合要求（默认1920x1080）
- 检查任务模板图像是否与当前游戏界面匹配
- 查看日志文件（`runtime/dev/logs/`目录）获取详细错误信息

### 4. GUI界面问题

- 如果界面显示异常，尝试删除`config/dev/app_settings.json`重置设置
- 如果侧边栏不可见，使用快捷键或重置设置

## 环境说明

项目环境配置信息可在`description_env.txt`文件中查看，包含了开发环境的详细信息和依赖版本。

## 联系方式

如有问题或建议，欢迎在GitHub上提交Issue或Pull Request。
