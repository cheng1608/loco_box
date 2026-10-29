# CLAUDE.md — Agent 速记

> 面向**下一次接手扩展的 AI**。深度内容在 `docs/`，这里只放「每次动手前必须知道」的规则。改文档/代码时先读 [docs/README.md](docs/README.md) 选对入口。

## 项目是什么

多功能游戏自动化盒子（洛克王国 S2 幸运惊喜盒工具的多功能扩展）。**本地 Web 前端 + 本地后端 + 系统级悬浮窗**：

```
浏览器式前端(Vue3) → REST/WebSocket → FastAPI 后端(8790)
                    后端 Feature 线程 → ctx.arduino → Arduino(ATmega32U4) → USB HID 按键 → 游戏
                    实时预览/截图 → WebSocket frame/shot → 前端
Tauri 2 壳：主窗口 + 各功能隐藏悬浮窗（无边框/透明/置顶）
```

当前三个功能：`box_monitor` 惊喜盒子（白字识别）、`throw` 丢球（循环键鼠）、`music` 自动演奏（简谱→手碟按键，播放器式歌单）。**完整机制见 `docs/FEATURES.md`。**

## 协作规则

**用户的操作用户最清楚**：用户报告的任何操作/现象都是事实，禁止质疑用户操作是否正确，只排查代码/硬件/日志/进程根因。当用户说某功能不工作，信任判断，直接查代码。

## 硬约束（违反会出事的）

1. **改后端 `.py` 必须重启后端**：后端是长驻进程（127.0.0.1:8790），不重启不生效。桌面启动的后端由 `backend.runner` 管理，关闭主窗口后会正常退出，再运行 `start.bat` 加载改动；独立 uvicorn 用原终端 Ctrl+C 退出后重启。先查健康接口中的 `service/protocol/pid` 确认归属，不按端口盲杀其他进程。完整复盘见 `docs/CHANGELOG.md`。
2. **Arduino 串口只连一次**：ATmega32U4 打开串口会硬件复位 → USB HID 断开重连。启动/首次连接一次 + 等 ~3s → **保持连接**，之后按键瞬间发送。禁止每次按键 connect/disconnect、禁止用 `dsrdtr=False` 之类技巧。所有功能统一走 `ctx.arduino`（`backend/core/arduino.py` 单例），**不要**各自 new `SerialBridge`。
3. **按键必须带 hold**：`Keyboard.write()` 瞬时按下松开太快，游戏检测不到。必须 `press → delay(≥50ms) → release`，即发 `"1:50"` 而非 `"1"`。50ms 是已验证最小有效值。
4. **游戏屏蔽 Python 模拟输入**：pyautogui/keyboard/pynput 一概不能用。Arduino 是唯一输入路径。
5. **字母大小写**：固件把单个大写字母转小写再按（HID 大写=SHIFT 组合）。所以发送大写字母 = 敲小写、不带 Shift。详见 `docs/PROTOCOL.md`。
6. **COM 口会变**：每次插拔 COM 号可能变化。用 `SerialBridge.find_arduino()` 自动检测优先，`settings.json` 的 `com_port` 兜底。
7. **Python 3.9**：类型注解用 `Optional[X]`，**禁止 `X | None`**。List/Dict 用 `typing`。
8. **Windows 父进程退出监听不能阻塞读 stdin**：`backend.runner` 使用 `PeekNamedPipe` 检查管道断开。本机 Conda Python + NumPy/OpenBLAS 下，`stream.read()` 和直接 `ReadFile` 都实测会阻塞首次 DLL 加载及新线程创建；保留非阻塞轮询与对应回归测试。

## 线程与消息

- Feature 各自的后台线程是 daemon。长等待用 `threading.Event.wait()`（可被 stop 打断），**别裸 `time.sleep` 长等**。
- 后台线程**不直接碰前端**：经 `ctx.bus.publish_status(text)` 等 → 事件总线 → WebSocket → 前端 `connectWs`。每个窗口共享一条 WS；`usePolling` 负责 0.8–2s 非重叠轮询、隐藏暂停和卸载清理。实时预览仅 `/ws?preview=1` 订阅。
- `EventBus` 已处理跨线程投递（`loop.call_soon_threadsafe`），后台线程只管 `publish_*`。

## 模块地图（当前架构）

| 层 | 位置 | 说明 |
|----|------|------|
| 启动器 | `start.bat` + `scripts/launch.ps1` | 日常复用 release；源码变化才构建；dev/build/doctor 模式 |
| Tauri 壳/窗口 | `frontend/src-tauri/src/{lib,backend,overlays}.rs` | 应用装配、后端就绪/日志/进程管理、悬浮窗按需创建和释放 |
| 后端入口 | `backend/main.py` + `runner.py` | FastAPI lifespan 管理预览与清理；桌面父进程退出管道触发正常关闭 |
| 运行时单例 | `backend/state.py` | `arduino/bus/config/features` 全局单例装配 |
| 配置 | `backend/core/config.py` | `data/settings.json`，功能命名空间 + 旧字段自动迁移 |
| 事件总线 | `backend/core/events.py` | `publish_status/shot/frame/count/event` |
| 截图/预览 | `backend/core/screen.py` `preview.py` | mss 截图、JPEG base64、周期推帧 |
| 功能框架 | `backend/features/__init__.py` | `Feature` ABC + `@register` + `FeatureContext` |
| 三个功能 | `backend/features/{box_monitor,throw,music}.py` | 见 `docs/FEATURES.md` |
| 路由/WS | `backend/api/routes.py` `ws.py` | REST 端点、`/ws` 事件转发 |
| 复用图像库 | `loco_box/`（matcher/monitor/image_ops/serial_bridge/region_selector/types） | 惊喜盒子识别与串口桥（后端经 `ctx.arduino` 用） |
| 前端入口/主视图 | `frontend/src/main.ts` `App.vue` `MainView.vue` | 窗口分发 + 侧栏面板 + 可折叠实时预览 |
| 面板 | `frontend/src/views/*.vue` | 各功能配置面板 |
| 悬浮窗 | `frontend/src/{Overlay,BoxOverlay,MusicOverlay}View.vue` | 各功能悬浮控件 |
| API 封装 | `frontend/src/api/client.ts` | REST 封装 + WS 自动重连 |

## 数据库/数据位置

- 运行数据目录 `data/`（已 gitignore）：`settings.json`（配置）、`scores/*.txt`（简谱）、`template.png`（白字模板）。
- `data/` 用 `backend/core/config.py` 里的 `_app_root()` 定位。

## 启动命令

```bash
start.bat                                     # 日常：直接运行已构建程序；首次/源码变更才构建
start.bat dev                                 # 开发：Vite + Tauri 热更新
start.bat build                               # 仅构建桌面，不启动
start.bat doctor                              # 诊断环境和后端
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8790   # 仅后端
cd frontend && npm run build                  # vue-tsc 类型检查 + 前端生产构建
cd frontend && npm run tauri dev              # 整机调试
```

回归：仓库根 `.venv/Scripts/python.exe -m unittest discover -s tests -v`；前端构建后 `npm test`（首次需 `npx playwright install chromium`）；Rust `cargo test --lib`。当前桌面产物依赖本仓库 `.venv` 和 Python 源码，尚未打包 sidecar；不要宣称为独立安装包。

## 文档入口

- 索引：`docs/README.md`（Overview/How-to/Reference/Changelog 分层）
- 技术栈：`docs/TECH-STACK.md`；架构：`docs/ARCHITECTURE.md`
- 功能 + 加功能指南：`docs/FEATURES.md`；后端 API：`docs/API.md`
- 音乐域设计（音阶/键位/乐谱格式/时序/模式）：`docs/MUSIC.md`
- 串口协议：`docs/PROTOCOL.md`；更新记录：`docs/CHANGELOG.md`
