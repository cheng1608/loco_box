# Loco Box · 本地游戏自动化工具箱

Windows 桌面应用，包含惊喜盒子监控、循环丢球、自动演奏三个功能。Vue 负责配置界面，Tauri 负责桌面和悬浮窗，Python 负责截图识别与自动化，所有游戏输入统一通过 Arduino USB HID 发送。

## 硬件要求

- **Arduino ATmega32U4**（Pro Micro / BadUSB / Leonardo 兼容板），USB-C 或 Micro-USB
- 固件：`scripts/arduino_bridge/arduino_bridge.ino`（Arduino IDE 上传，选 Arduino Leonardo）

## 快速启动

环境已配置好后，双击仓库根目录的 **`start.bat`**。

- 首次启动会构建桌面程序，Rust 首次编译可能需要数分钟，并显示构建进度。
- 后续启动直接运行已有程序，不启动 Vite、Node 或 Cargo。前端或桌面源码变化时才重新构建；后端改动随下次启动加载。
- 后端启动期间会显示连接状态，就绪后自动出现功能面板；连接中断也会自动恢复。
- 重复双击会激活已打开的窗口。关闭主窗口会退出悬浮窗并释放应用自己启动的后端。

当前构建是**在本仓库内运行的桌面版本**，需要保留 `.venv`、`backend/` 和 `loco_box/`。历史 Releases 的单文件程序属于旧 Tkinter 版本，不能代表当前 Vue/Tauri 功能；当前尚未提供内置 Python 的独立安装包。

## 首次启动

1. Arduino 插上 USB
2. 双击运行 `start.bat`

   ![当前桌面界面示例](docs/images/main-window.png)

3. 点击**监控区域**，框选包含「幸运惊喜盒」五个白字的区域

   ![监控区域](docs/images/监控区域.png)

4. 点击**截图区域**，框选盒子打完以后要截图的区域

   ![截图区域](docs/images/截图区域.png)

5. 调整参数：
   - **延迟**：文字消失后等待多久再截图（默认 1 秒）
   - **阈值**：匹配灵敏度（默认 0.45）
   - **亮度**：白色笔画提取阈值（默认 200）
   - **按键**：检测到盒子后多久发送按键 1（默认 5 秒）
   - **COM**：Arduino 端口（默认 AUTO 自动检测）

6. 点击**开始**启动监控

7. 检测到盒子后按设定延时发送按键 1；文字消失后截图并显示在预览区

## 当前版本说明

当前代码为 **Vue3 + FastAPI + Tauri 2** 多窗口架构（本地 Web 前端 + 本地后端 + 系统级悬浮窗），含三个功能：惊喜盒子、丢球、自动演奏。开发者文档见 [docs/](docs/README.md)。

## 从源码运行

首次准备需要 Windows、Python 3.9、Node.js LTS、Rust 和 Visual Studio C++ 构建工具。已完成构建且源码未变时，日常运行不需要启动 Node/Rust 工具链。

```powershell
py -3.9 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
# 前端依赖不存在时，启动器会执行 npm ci
start.bat

# 显式开发模式，带热更新与可见日志
start.bat dev
# 只构建，不打开窗口
start.bat build
# 检查解释器、依赖、构建产物与服务状态
start.bat doctor

# 或分开跑（开发调试用，两个终端）：
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8790
cd frontend
npm run dev
```

MIDI 转谱和本地手碟模拟器是可选工具，需要额外安装 `.venv\Scripts\python.exe -m pip install -r requirements-tools.txt`。日常应用不再依赖旧界面库 customtkinter。

运行数据在 `data/`：配置 `settings.json`、模板 `template.png`、歌单 `scores/`。启动日志在 `data/logs/backend.log`，构建日志在 `data/logs/build.log`。排查启动问题先运行 `start.bat doctor`，再查看界面连接详情及日志。

## 验证改动

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
cd frontend
npm run build
npx playwright install chromium
npm test
cd src-tauri
cargo test --lib
```

前端测试覆盖后端晚启动、服务中断恢复、配置失败重试、共享 WebSocket 和悬浮窗初始化；后端测试不依赖 Arduino，也不会向游戏发送按键。

## 文档

| 文档 | 内容 |
|------|------|
| [CLAUDE.md](CLAUDE.md) | AI Agent 协作规则与硬约束 |
| [docs/README.md](docs/README.md) | 开发者文档索引 |
| [docs/TECH-STACK.md](docs/TECH-STACK.md) | 技术栈与版本 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构（进程/窗口/数据流/线程） |
| [docs/FEATURES.md](docs/FEATURES.md) | 功能详解 + 扩展指南 |
| [docs/API.md](docs/API.md) | 后端 API 参考 |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | Arduino 串口协议 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 更新记录 |
