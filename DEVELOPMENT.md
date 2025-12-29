# BD2-AUTO 开发者文档

本文档为BD2-AUTO项目的开发者提供开发环境搭建、代码结构和贡献指南。

## 目录

- [BD2-AUTO 开发者文档](#bd2-auto-开发者文档)
  - [目录](#目录)
  - [项目概述](#项目概述)
  - [技术栈](#技术栈)
  - [开发环境搭建](#开发环境搭建)
    - [1. 克隆仓库](#1-克隆仓库)
    - [2. 创建虚拟环境](#2-创建虚拟环境)
      - [使用Conda（推荐）](#使用conda推荐)
      - [使用venv](#使用venv)
    - [3. 安装依赖](#3-安装依赖)
    - [4. 安装开发工具](#4-安装开发工具)
    - [5. 准备OCR模型](#5-准备ocr模型)
  - [代码结构](#代码结构)
  - [核心模块说明](#核心模块说明)
    - [1. 自动控制核心（auto\_control）](#1-自动控制核心auto_control)
    - [2. 任务管理（core/task\_manager）](#2-任务管理coretask_manager)
    - [3. 自动化任务（auto\_tasks）](#3-自动化任务auto_tasks)
    - [4. GUI界面（entrypoints/main\_window）](#4-gui界面entrypointsmain_window)
    - [5. UI模块（ui/）](#5-ui模块ui)
  - [坐标系统](#坐标系统)
    - [坐标类型定义](#坐标类型定义)
      - [1. **BASE（基准坐标）**](#1-base基准坐标)
      - [2. **LOGICAL（逻辑坐标）**](#2-logical逻辑坐标)
      - [3. **PHYSICAL（物理坐标）**](#3-physical物理坐标)
    - [坐标生成与传入路径](#坐标生成与传入路径)
      - [1. **OCR生成坐标**](#1-ocr生成坐标)
      - [2. **图像识别（模板匹配）生成坐标**](#2-图像识别模板匹配生成坐标)
      - [3. **基准坐标传入**](#3-基准坐标传入)
    - [坐标转换流程](#坐标转换流程)
      - [1. **从`auto.click`到设备层的参数传递**](#1-从autoclick到设备层的参数传递)
      - [2. **Windows设备的坐标处理**](#2-windows设备的坐标处理)
      - [3. **核心转换方法**](#3-核心转换方法)
        - [BASE → LOGICAL](#base--logical)
        - [PHYSICAL → LOGICAL](#physical--logical)
        - [LOGICAL → 屏幕物理坐标](#logical--屏幕物理坐标)
        - [PHYSICAL → 屏幕物理坐标](#physical--屏幕物理坐标)
    - [最终点击执行](#最终点击执行)
    - [特殊情况处理](#特殊情况处理)
      - [1. **全屏模式**](#1-全屏模式)
      - [2. **边界检查**](#2-边界检查)
      - [3. **DPI感知**](#3-dpi感知)
    - [坐标系统总结](#坐标系统总结)
  - [开发流程](#开发流程)
    - [1. 运行项目](#1-运行项目)
      - [GUI模式](#gui模式)
      - [控制台测试模式](#控制台测试模式)
    - [2. 添加新任务](#2-添加新任务)
    - [3. 配置管理](#3-配置管理)
    - [4. 代码规范](#4-代码规范)
    - [5. 打包测试](#5-打包测试)
      - [使用打包脚本（Windows）](#使用打包脚本windows)
      - [手动打包](#手动打包)
    - [6. 自动化构建与发布](#6-自动化构建与发布)
  - [贡献指南](#贡献指南)
    - [1. 提交代码](#1-提交代码)
    - [2. 代码审查](#2-代码审查)
    - [3. 发布流程](#3-发布流程)
  - [常见问题](#常见问题)
    - [1. OCR模型下载失败](#1-ocr模型下载失败)
    - [2. 打包失败](#2-打包失败)
    - [3. 任务执行失败](#3-任务执行失败)
    - [4. GUI界面问题](#4-gui界面问题)
  - [环境说明](#环境说明)
  - [联系方式](#联系方式)

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
│   ├── entrypoints/      # 程序入口点
│   │   └── main_window.py  # GUI窗口
│   └── ui/               # UI模块（包含界面组件和布局）
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

### 1. 自动控制核心（auto\_control）

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

### 2. 任务管理（core/task\_manager）

任务管理模块负责任务的动态加载、配置管理和设置存储。

- **path_manager.py**：路径管理工具，提供统一的路径获取接口，适配开发和打包环境
- **task_manager.py**：
  - **load_task_modules()**：动态加载任务模块，自动发现和注册新任务
  - **TaskConfigManager**：任务配置管理，负责任务配置的加载和保存
  - **AppSettingsManager**：应用设置管理，负责应用级设置的加载和保存

### 3. 自动化任务（auto\_tasks）

自动化任务模块包含了所有具体的游戏任务实现。

- **pc/**：PC端游戏任务实现，包括登录、日常任务、竞技场等
- **utils/roi_config.py**：ROI（感兴趣区域）配置管理，用于定义游戏界面上的关键区域

### 4. GUI界面（entrypoints/main\_window）

GUI界面模块提供了用户与自动化系统交互的界面。

- **main_window.py**：主窗口类，负责处理用户交互、显示任务状态和控制自动化流程

### 5. UI模块（ui/）

UI模块包含了应用程序的界面组件和布局定义。

- 提供了各种UI组件的实现，支持应用程序的界面展示和用户交互

## 坐标系统

### 坐标类型定义

#### 1. **BASE（基准坐标）**
- **定义**：基于基准分辨率（通常为1920x1080）的坐标体系，作为模板匹配和OCR的参考标准
- **来源**：用户手动定义的固定坐标，或从模板文件中获取的坐标
- **特点**：与当前窗口分辨率和DPI设置无关，具有最高的通用性

#### 2. **LOGICAL（逻辑坐标）**
- **定义**：客户区逻辑坐标，与DPI缩放无关，反映窗口的实际显示比例
- **来源**：
  - 图像识别（模板匹配）的直接输出结果
  - OCR识别后的坐标转换结果
- **特点**：自动适配窗口大小变化，但不考虑DPI缩放

#### 3. **PHYSICAL（物理坐标）**
- **定义**：客户区物理坐标，考虑DPI缩放后的实际像素坐标
- **来源**：
  - OCR识别的原始输出结果
  - 屏幕截图的直接像素坐标
- **特点**：反映实际屏幕像素位置，但与DPI设置相关

### 坐标生成与传入路径

#### 1. **OCR生成坐标**
- **文件**：`src/auto_control/ocr/ocr_processor.py`
- **方法**：`find_text_position`
- **流程**：
  1. 对输入图像进行OCR识别
  2. 获取文本边界框的物理坐标（子图内）
  3. 将子图坐标转换为原图物理坐标
  4. 通过`get_unified_logical_rect`方法将物理坐标转换为逻辑坐标
  5. 返回逻辑坐标矩形

#### 2. **图像识别（模板匹配）生成坐标**
- **文件**：`src/auto_control/image/image_processor.py`
- **方法**：`match_template`
- **流程**：
  1. 根据当前窗口状态计算模板缩放比例
  2. 对模板进行缩放以适应当前分辨率
  3. 执行模板匹配获取匹配位置
  4. 将匹配位置转换为逻辑坐标
  5. 返回逻辑坐标矩形

#### 3. **基准坐标传入**
- **来源**：用户手动定义或从配置文件中读取
- **特点**：直接使用BASE坐标体系，需要转换为当前窗口的逻辑坐标

### 坐标转换流程

#### 1. **从`auto.click`到设备层的参数传递**
- **文件**：`src/auto_control/core/auto.py`
- **方法**：`click`
- **流程**：
  1. 接收用户传入的坐标和坐标类型（字符串形式："BASE"/"PHYSICAL"/"LOGICAL"）
  2. 将字符串坐标类型映射为`CoordType`枚举
  3. 调用设备层的`click`方法，传入坐标和枚举类型

#### 2. **Windows设备的坐标处理**
- **文件**：`src/auto_control/devices/windows_device.py`
- **方法**：`click`
- **流程**：
  1. 激活目标窗口
  2. 根据坐标类型进行不同的转换：
     - **BASE坐标**：调用`convert_original_to_current_client`转换为逻辑坐标
     - **PHYSICAL坐标**：直接使用，后续转换为屏幕坐标
     - **LOGICAL坐标**：直接使用
  3. 将坐标转换为屏幕物理坐标：
     - **全屏模式**：直接使用逻辑坐标（全屏时逻辑=物理=屏幕坐标）
     - **窗口模式**：
       - 逻辑坐标：调用`convert_client_logical_to_screen_physical`转换
       - 物理坐标：调用`convert_client_physical_to_screen_physical`转换

#### 3. **核心转换方法**
- **文件**：`src/auto_control/utils/coordinate_transformer.py`

##### BASE → LOGICAL
```python
def convert_original_to_current_client(self, x: int, y: int) -> Tuple[int, int]:
    # 全屏模式：直接使用原始坐标
    # 窗口模式：根据当前窗口逻辑分辨率进行缩放
    scale_x = curr_logical_w / orig_w
    scale_y = curr_logical_h / orig_h
    final_x = int(round(x * scale_x))
    final_y = int(round(y * scale_y))
    return final_x, final_y
```

##### PHYSICAL → LOGICAL
```python
def convert_client_physical_to_logical(self, x: int, y: int) -> Tuple[int, int]:
    # 进行逆DPI缩放
    ratio = ctx.logical_to_physical_ratio
    logical_x = int(round(x / ratio))
    logical_y = int(round(y / ratio))
    return logical_x, logical_y
```

##### LOGICAL → 屏幕物理坐标
```python
def convert_client_logical_to_screen_physical(self, x: int, y: int) -> Tuple[int, int]:
    # 先转换为客户区物理坐标
    phys_x, phys_y = self.convert_client_logical_to_physical(x, y)
    # 再映射到屏幕全局坐标
    screen_x, screen_y = win32gui.ClientToScreen(hwnd, (phys_x, phys_y))
    return screen_x, screen_y
```

##### PHYSICAL → 屏幕物理坐标
```python
def convert_client_physical_to_screen_physical(self, x: int, y: int) -> Tuple[int, int]:
    # 直接映射到屏幕全局坐标
    screen_x, screen_y = win32gui.ClientToScreen(hwnd, (x, y))
    return screen_x, screen_y
```

### 最终点击执行

1. **获取屏幕物理坐标**：通过上述转换方法获取最终的屏幕物理坐标
2. **设置鼠标位置**：使用`win32api.SetCursorPos`设置鼠标位置
3. **执行点击操作**：使用`win32api.mouse_event`执行鼠标点击事件
4. **重复点击**：根据`click_time`参数执行多次点击

### 特殊情况处理

#### 1. **全屏模式**
- 跳过DPI缩放和客户区到屏幕的转换
- 直接使用逻辑坐标作为屏幕物理坐标

#### 2. **边界检查**
- 在所有转换步骤中进行边界检查，确保坐标不会超出屏幕或窗口范围
- 使用`_ensure_coords_in_boundary`和`limit_rect_to_boundary`方法进行边界限制

#### 3. **DPI感知**
- 通过`_enable_dpi_awareness`方法启用系统DPI感知
- 确保在不同DPI设置下坐标转换的准确性

### 坐标系统总结

坐标转换系统通过三层坐标体系（BASE/LOGICAL/PHYSICAL）实现了高度的灵活性和适应性：

1. **BASE坐标**：提供了与分辨率和DPI无关的基准，方便用户定义和模板复用
2. **LOGICAL坐标**：实现了窗口大小的自动适配，保证在不同窗口尺寸下的一致性
3. **PHYSICAL坐标**：确保了与实际屏幕像素的准确映射，适应不同DPI设置

整个系统通过`CoordinateTransformer`类实现了坐标的统一管理和转换，通过`WindowsDevice`类实现了设备特定的坐标处理，最终通过`auto.click`方法提供了简洁的用户接口。这种分层设计确保了坐标转换的准确性和灵活性，同时提供了良好的用户体验。

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