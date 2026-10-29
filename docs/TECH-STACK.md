# 技术栈与顶层结构

## 一句话

本地 **FastAPI 后端**（自动化逻辑 + 串口） + **Vue3 前端**（配置界面与悬浮窗，跑在 Tauri WebView 里） + **Arduino**（唯一能往游戏发按键的硬件）。整机只有一个进程树，全跑在本机 `127.0.0.1`，无任何外部服务。

## 技术栈清单

| 层 | 技术 | 版本（依据 manifest） | 说明 |
|----|------|----------------------|------|
| 桌面壳 | Tauri 2 (Rust) | `tauri 2.11.3`, `tauri-build 2.6.3`（Cargo.toml） | 主窗 + 按需悬浮窗、后端就绪检查、管道退出与进程管理 |
| 前端框架 | Vue 3 | `^3.4.31`（package.json） | `<script setup lang="ts">` 组合式 API |
| UI 库 | Element Plus | `^2.7.8` | 具体组件及样式按需导入，暗色主题；悬浮窗不引入主面板组件库 |
| 构建/语言 | Vite 5 + TypeScript + vue-tsc | 以 package-lock.json 为准 | `npm run build` 先做 Vue/TS 类型检查，再构建 |
| 前端回归 | Playwright | 以 package-lock.json 为准 | 用真实 Chromium 验证延迟启动、恢复、共享连接和窗口分发 |
| Tauri 前端 API | `@tauri-apps/api` | `^2.11.1` | 动态 `import()` 引入（core/event/window），非 Tauri 环境（浏览器预览）自动降级 |
| 后端框架 | FastAPI + uvicorn | `fastapi>=0.110`, `uvicorn[standard]>=0.29`（requirements.txt） | 端口 8790，CORS 全开（仅本机） |
| 事件推送 | WebSocket | 同上 | `/ws`，事件总线广播 |
| 截图 | mss + numpy + Pillow | `mss>=9.0.1` 等 | 主屏预览、区域截图、JPEG base64 |
| 串口 | pyserial | `>=3.5` | 9600 baud → Arduino（经 `loco_box/serial_bridge.py`） |
| 图像识别 | numpy + Pillow（无 OpenCV） | — | `loco_box/matcher.py` 白字笔画指纹，纯 numpy 实现 |
| 硬件 | Arduino ATmega32U4 | — | USB HID 键盘/鼠标（Leonardo/Micro 兼容板），固件 `scripts/arduino_bridge/arduino_bridge.ino` |
| Python | CPython | 3.9（约束见下） | 运行 `.venv`；系统也装有 anaconda python 可跑同一套 |

## 目录结构（当前架构）

```
loco_box/
├── backend/                  # FastAPI 后端（本轮重构核心）
│   ├── main.py               # app + 路由 + lifespan 管理后台资源
│   ├── runner.py             # 桌面父进程管道关闭后正常退出
│   ├── state.py              # 单例装配：arduino / bus / config / features
│   ├── api/
│   │   ├── routes.py         # 全部 REST 端点
│   │   └── ws.py             # /ws WebSocket 转发
│   ├── core/
│   │   ├── arduino.py        # ArduinoController（共享持久连接单例）
│   │   ├── config.py         # ConfigStore（settings.json）+ 常量 DATA_DIR/SCORES_DIR/TEMPLATE_FILE
│   │   ├── events.py         # EventBus（跨线程事件 → WS 广播）
│   │   ├── preview.py        # 全局实时预览循环（有订阅者才截主屏）
│   │   └── screen.py         # 截图 + JPEG base64 编码
│   └── features/             # Feature 插件（box_monitor / throw / music）
├── frontend/                 # Vue3 + Tauri
│   ├── src/
│   │   ├── main.ts           # Vue 挂载 + 暗色主题
│   │   ├── App.vue           # 按窗口 label 分发视图
│   │   ├── MainView.vue      # 主界面（侧栏 + 面板 + 可折叠实时预览）
│   │   ├── views/            # 各功能配置面板
│   │   ├── OverlayView.vue           # 丢球悬浮窗（throw）
│   │   ├── BoxOverlayView.vue        # 惊喜盒子悬浮窗
│   │   ├── MusicOverlayView.vue      # 自动演奏悬浮窗（播放器控件）
│   │   ├── components/MusicIcons.ts  # 内联 SVG 图标（无额外依赖）
│   │   └── api/client.ts     # REST 封装 + WS 自动重连
│   └── src-tauri/
│       ├── src/lib.rs        # 应用装配与 invoke 注册
│       ├── src/backend.rs    # 后端就绪、日志、进程与优雅退出
│       ├── src/overlays.rs   # 悬浮窗按需创建和释放
│       ├── tauri.conf.json   # 主窗口 1120×760、frontendDist、bundle
│       └── capabilities/default.json  # 4 个窗口 + 窗口操作权限
├── loco_box/                 # 可复用 Python 库（识别/串口/框选/类型）
├── data/                     # 运行数据（gitignore）：settings.json / scores/*.txt / template.png
├── scripts/
│   ├── arduino_bridge/arduino_bridge.ino  # Arduino 固件
│   └── test_*.py             # 串口/按键链路诊断脚本
├── docs/                     # 本文档目录
└── CLAUDE.md / README.md
```

## 端口与地址约定

| 服务 | 地址 |
|------|------|
| FastAPI 后端 | `http://127.0.0.1:8790` |
| WS 事件 | `ws://127.0.0.1:8790/ws` |
| Vite dev server（仅开发） | `http://127.0.0.1:5173`，端口被占用时直接报错 |

## Python 版本与代码约束

- 目标 Python **3.9**：类型注解用 `typing.Optional[X]`，**禁止 `X | None`**；容器用 `List`/`Dict`/`Tuple`（来自 `typing`）。
- 不引入 OpenCV；图像一律 numpy/Pillow，颜色约定 **BGR**（兼容性需要，灰度权重 `[0.114, 0.587, 0.299]`）。
- 串口读写都在后台线程，主逻辑线程与 asyncio 事件循环经 `EventBus` 隔离（见 `docs/ARCHITECTURE.md`）。

## 环境备注（可能踩坑）

- `requirements.txt` 仅包含应用运行依赖，旧 customtkinter 已移除。MIDI 转换与手碟模拟器使用 `requirements-tools.txt` 中的可选依赖；Tkinter 仅用于系统区域框选和独立工具 GUI。
- 系统装有 anaconda python 与项目 `.venv` 两套解释器，都装了依赖；启动/重启后端统一用 `backend/main.py` 头注释里的 `.venv` 命令，避免版本漂移。
- `data/` 已被 gitignore；`settings.json`（含 COM 口、各功能参数）不进版本库。
