# 架构

## 进程模型

日常启动是**一个 Tauri 进程树**：`start.bat` 调用 `scripts/launch.ps1`，比较桌面源文件内容指纹，首次或源码变化才执行生产构建，后续直接运行 `frontend/src-tauri/target/release/app.exe`。只有 `start.bat dev` 才启动 Vite 与编译 watcher。重复启动按桌面进程的实际路径识别并激活主窗口，不以“后端健康”代替“桌面已打开”。

Rust 后台线程检查后端身份与协议，未运行时用 `.venv` 的 Python 启动 `backend.runner`，状态由 `backend_status` 暴露，日志存于 `data/logs/backend.log`。界面同时加载，等待服务的过程中显示连接状态并自动重试。主窗口关闭后 Rust 关闭后端 stdin 管道，runner 请求 Uvicorn 正常退出并运行 lifespan 清理，等待最多 4 秒，超时才强制终止。外部独立启动的兼容后端可以复用，桌面不终止它。

Windows 管道监听使用 `PeekNamedPipe` 每 100ms 检查断开，不发起阻塞读取。本机 Conda Python 3.9 + NumPy/OpenBLAS 组合下，阻塞 stdin 读取会卡住之后的 DLL 加载与线程创建，已通过独立子进程回归验证。不能将其改回 `stream.read()` 或阻塞 `ReadFile`。

```
[ 主进程 loco_box (Tauri / Rust) ]
├─ 后端子进程 backend.runner → uvicorn backend.main:app  127.0.0.1:8790
│    ├─ Feature 后台线程（监控 / 演奏 / 丢球，各自 daemon）
│    ├─ 预览线程（仅有 preview=1 订阅者时每 300ms 截主屏）
│    └─ /ws 广播（EventBus → 所有 WebSocket）
└─ 1 个主 WebView + 按需创建的悬浮 WebView（各视图独立加载）
```

## 窗口清单（`frontend/src-tauri/src/lib.rs` + `App.vue`）

前端在 `App.vue` 首次渲染前通过 Tauri 的 `isTauri()/getCurrentWindow().label` 识别窗口并动态加载对应视图；浏览器环境回退主界面。悬浮窗首次使用才创建，关闭时销毁 WebView 并保存位置，再次打开恢复位置。悬浮窗不会先挂载一次主界面。

| label | 视图组件 | 尺寸 | 特性 | 何时显示 |
|-------|----------|------|------|----------|
| `main` | `MainView.vue`（侧栏切换 3 面板 + 右可折叠实时预览） | 1120×760，最小 900×600 | 常规窗口 | 启动即显示 |
| `overlay` | `OverlayView.vue`（丢球：开关按钮 + 5s 冷却） | 220×110 | 无边框/透明/置顶/`skip_taskbar` | 丢球面板「启动」经 `toggle_overlay` 显隐 |
| `box_overlay` | `BoxOverlayView.vue`（计数 + 最近截图） | 320×320 | 同上 | 惊喜盒子面板点「开始监控」后 `show_box_overlay` |
| `music_overlay` | `MusicOverlayView.vue`（播放器四按钮） | 320×150 | 同上 + **`.focusable(false)`**（不抢游戏键盘焦点） | 自动演奏面板点「启动」后 `show_music_overlay` |

> **为什么丢球/惊喜盒子悬浮窗没加 `focusable(false)`**：丢球和惊喜盒子的按键目标是「当时获得焦点的窗口」（鼠标点在游戏上即可），悬浮窗只是按钮面板；而自动演奏的 HID 键必须落到游戏/记事本，悬浮窗若可聚焦会抢走键盘焦点导致按键敲进 App。若后续某功能出现「按键打在悬浮窗上」，先给该窗口补 `.focusable(false)`。
>
> 悬浮窗可拖动：顶栏 `grip` 上 `@mousedown` → `getCurrentWindow().startDragging()`。悬浮窗「×」关闭与主面板状态双向同步：面板 `listen('box-monitor-stopped'|'overlay-hidden'|...)`，悬浮窗关时 `emit` 同名事件 + `hide_xxx`。

## 前后端通信

### REST（指令 + 拉取）
前端 `api/client.ts` 的 `http<T>()`：JSON、失败抛 `Error(detail)`，普通请求 8 秒超时，Arduino 连接 30 秒，人工框选不设固定超时。主视图将功能列表与设备状态作为初始化条件，失败持续重试；断开后保留已填写内容并禁止操作，恢复后重新启用。所有功能启停、配置读写、音乐播放控制都走 REST。完整端点表见 `docs/API.md`。

### WebSocket（推送）
`/ws`：后端 EventBus → 各连接；仅 `/ws?preview=1` 接收预览帧。前端每个窗口共享一条连接，`connectWs` 负责引用计数与 0.5–5 秒退避重连。消息按 `type` 分发：`frame`（实时预览）/ `shot`（区域截图）/ `count`（盒子计数）/ `status`（状态文本）/ `event`（通用）。`usePolling` 以 0.8–2 秒间隔补充状态，在请求结束后调度下一次，隐藏/卸载时停止。

### 跨线程数据流（后端内部）

```
Feature 后台线程（任何线程）
   │  ctx.bus.publish_status("演奏中 · …")        ← 可放心在任意线程调用
   ▼
EventBus.publish → loop.call_soon_threadsafe(_broadcast)
   ▼  asyncio 事件循环线程
EventBus._broadcast → 每个订阅队列 put_nowait（队满丢弃，64 上限；预览最多排一帧）
   ▼
ws.py 从队列取 → send_json 到浏览器
```

要点：后台线程**绝不直接**碰 `asyncio.Queue` / 前端；全部经 `EventBus`。FastAPI lifespan 注入事件循环，退出时停止预览、各功能并断开 Arduino。模块导入不会启动线程；图像库和 Tkinter 到实际使用时才导入。WebSocket 同时监听客户端断开，空闲连接也能及时清理。

## 串口策略（ArduinoController）

见 `docs/PROTOCOL.md` 物理层细节。架构层要点：

- ATmega32U4 打开串口 = 硬件复位 → USB HID 断开重连需 ~3s。
- 因此 `ArduinoController`（`backend/core/arduino.py`）做成**全局单例持久连接**：谁缺连接谁去 `connect()`（内部加锁、已连接直接返回），成功后 `settings.json` 记住本次 COM 口兜底。之后 `send()` 只 `write()`，无 sleep。
- COM 解析 `AUTO`：`SerialBridge.find_arduino()`（扫描述含 arduino/micro）→ 失败用配置 `com_port` → 再失败报错。
- 三个功能拿到同一 `ctx.arduino`。串口只被它独占；**新功能不要自建 `SerialBridge` 连接**。

## Feature 生命周期

1. `backend/state.py` 启动时建 `FeatureContext(arduino, bus, config)` → `create_features(ctx)` import 各模块（触发 `@register`）→ 实例化注册表里所有 Feature。
2. 每个 Feature：`default_config()`（由 `config_schema` 生成）merge `settings.json` 已存值 → `start(config)` 起后台线程。
3. 停止：REST `stop` → 翻 `_active` / set `Event`，线程在下一个可打断点退出。
4. 运行态经 `GET /api/features` 暴露 `running`，前端轮询。

新增功能的四步模板（后端注册 → 路由 → 面板 → 悬浮窗）与自检清单见 `docs/FEATURES.md`。

## 功能运行时速览

### 惊喜盒子 `box_monitor`
面板框选两个区域 → 「开始监控」：先落盘配置、起 `MonitorThread`（0.3s 轮询白字指纹，`loco_box/matcher.py` + `monitor.py`），后台线程连 Arduino，同时 `show_box_overlay`。盒子出现 → 预约 `trigger_delay` 后按 `1:50`；消失 → 截 `region_b` 图推 `shot` + `count`。关闭悬浮窗即停并同步面板。

白字识别核心（无 OpenCV）：白场判断 → top-hat（`gray - gaussian`）→ 阈值二值化 → 垂直投影切字符 → 多因子加权评分 + 硬拒条件，返回 `MatchAnalysis{absent/strong_present/weak_present/score}`。模板持久化 `data/template.png`。

### 丢球 `throw`
面板设 4 段时间 → 「启动」仅 `toggle_overlay` 显隐悬浮窗；真正开关在悬浮窗里（`startFeature/stopFeature('throw')`）。后端 `_loop` 循环 `MOUSE_LEFT:mouse_hold` → sleep → `LSHIFT:shift_hold` → sleep。无识别。

### 自动演奏 `music`
面板展示歌单并选曲（`select_song`），「启动」只 `show_music_overlay`；播放/暂停/切歌/模式全在悬浮窗。播放线程：每首歌前 3s 倒计时（首曲与 Arduino 连接并行）→ 逐音符 `send(key, HOLD_MS=50)`，按谱面停顿 `sleep`。支持五播放模式、音符边界暂停续播、手动切歌打断。实现细节见 `docs/FEATURES.md`「自动演奏」；域设计（音阶/键位/乐谱格式/时序）见 `docs/MUSIC.md`。

## 实时预览（主界面右侧）

`backend/core/preview.py`：daemon 线程每 300ms 检查 `bus.has_preview_subscribers()`，有明确订阅才截主屏，等比例缩至 960×540 内，再编码为 JPEG base64。普通状态连接不接收整屏图像，慢连接最多排一帧。主界面折叠预览或不可见时取消帧订阅；功能截图保持原始分辨率。

## 关键时序/延时

| 项 | 值 | 依据 |
|----|-----|------|
| 串口波特率 | 9600 | serial_bridge |
| Arduino 复位等待 | ~3s | `connect_and_wait` / 后台连接 |
| 按键最小 hold | 50ms | `music.HOLD_MS`（已验证最小有效值）|
| 演奏每首前倒计时 | 3s | `music.COUNTDOWN_SECS` |
| 预览推送间隔 | 0.3s | preview.py |
| 惊喜盒子轮询 | 0.3s，出现×4 / 消失×3 确认 | `loco_box/monitor.py` |
| 前端状态轮询 | 800ms–2s | `usePolling`，完成后再等待，隐藏/卸载暂停 |
| WS 重连退避 | 0.5–5s | client.ts，成功后重置 |
