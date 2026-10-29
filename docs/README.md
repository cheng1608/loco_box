# 开发者文档索引

> 本目录是面向**开发者与后续接手扩展的 AI** 的技术文档，按 Google 文档规范组织（Overview / How-to / Reference / Changelog 分层）。终端用户指南见仓库根 `README.md`。

## 读哪一篇

| 你的目标 | 文档 |
|----------|------|
| 一句话了解这是什么 + 各技术栈版本 | [TECH-STACK.md](TECH-STACK.md) |
| 系统怎么拼起来的：进程 / 窗口 / 数据流 / 线程 / 串口策略 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 三个功能怎么用、怎么给按键、**如何加新功能** | [FEATURES.md](FEATURES.md) |
| 自动演奏的域设计：手碟音阶 / 键位映射 / 乐谱格式 / 时序 / 模式 | [MUSIC.md](MUSIC.md) |
| 后端 REST / WebSocket / Feature 基类 / 配置格式 | [API.md](API.md) |
| Arduino 串口文本协议与固件（含字母大小写语义） | [PROTOCOL.md](PROTOCOL.md) |
| 最近几轮改了哪些东西（含踩坑经验） | [CHANGELOG.md](CHANGELOG.md) |

给 AI Agent 的速记（协作规则、硬约束、代码书写规范）仍在仓库根 [`CLAUDE.md`](../CLAUDE.md)。

## 文档结构说明（Google 风格映射）

- **Overview** — `TECH-STACK.md`（是什么 / 用什么 / 顶层结构）。
- **How-to / 概念解释** — `FEATURES.md`（功能怎么运作、怎么扩展）；`ARCHITECTURE.md` 内含关键概念的图示与说明。
- **Reference** — `API.md`、`PROTOCOL.md`、`MUSIC.md`（端点表、消息格式、常量、音乐域设计表），以表格为骨架，不重复 How-to。
- **Changelog** — `CHANGELOG.md`（每轮开发追加一条）。

## 常用命令（开发期）

```bash
# 后端单独跑（默认 127.0.0.1:8790）
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8790

# 前端 dev（vite，HMR）—— 需要后端已起
cd frontend && npm run dev

# 日常启动：复用本地编译的桌面程序；首次或桌面源码变化才构建
start.bat
start.bat dev      # Vite + Tauri 开发模式
start.bat build    # 仅构建
start.bat doctor   # 启动诊断

# 前端生产构建（包括 vue-tsc 类型检查）
cd frontend && npm run build

# 回归：浏览器测试前先构建并安装 Playwright Chromium
npm test
# 仓库根目录执行后端测试
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

> 改了 `backend/**` 的 `.py` 后**必须重启 uvicorn** 生效；前端改动在 `vite build` / `tauri dev` 下自动或重新编译生效。详见 `docs/CHANGELOG.md` 排查经验。
