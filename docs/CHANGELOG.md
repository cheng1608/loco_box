# 更新记录（Changelog）

> 本文件记录**面向开发的架构级变更**。每次完成一轮开发，在这里追加一条，方便后续接手的开发者/AI 快速了解演进脉络。
>
> 日期格式：`YYYY-MM-DD`。分组：`新增` / `变更` / `修复` / `重构`。

## 2026-10-29 — 启动可靠性与运行资源重构

- 日常启动改为复用本地 release 桌面程序，按源码内容判断是否需要构建；开发、构建、诊断有独立入口。构建/后端日志写入 `data/logs/`。
- 修复后端未就绪时功能列表加载失败后永久空白；前端自动重试，断线期间保留表单并禁用操作，配置初始化也可重试。
- 首次渲染前识别窗口，按需导入视图和功能面板，Element Plus 改为组件级导入；各窗口共享自己的 WebSocket，轮询避免重叠并在不可见时暂停。
- Rust 将后端管理、悬浮窗管理分成独立模块；校验后端服务身份与协议，保留启动失败信息，悬浮窗使用时才创建、关闭时释放。
- FastAPI lifespan 统一启动与释放资源；图像/框选依赖延迟导入，`import backend.main` 不再创建线程。
- 实时预览显式订阅，预览图限制 960×540，原始截图分辨率不变；空闲 WebSocket 断开立即释放订阅，慢连接不积压旧帧。
- 修复丢球长等待无法立即停止、停止后仍多发 Shift 的问题；保留共享 Arduino 持久连接策略。
- 移除旧 customtkinter 运行依赖，MIDI/模拟器依赖移至 `requirements-tools.txt`。新增 Python 与真实浏览器启动回归，构建包含 TypeScript 检查。

当前 release 可执行文件仍需要仓库 Python 环境，不是可独立分发的安装包。

### 验证

- 前端类型检查与生产构建通过，6 项 Chromium 回归通过；后端 13 项测试通过；Rust 健康检查测试通过。
- 本机实际 release 桌面验证：真实预览出图、三个悬浮窗创建/释放、重复启动复用、关闭后端退出、再次启动均通过。两次已有构建的启动中，窗口与后端就绪为 1.8/1.9s，包含 PowerShell 启动器约 2.45/2.65s；仅代表当前机器的这两次样本，首次编译不计入。
- 前端 JS 总量约 1061kB → 217kB，CSS 372kB → 70kB；按需窗口不加载无关的主面板库。
- 新增父进程生命周期管道在整机验证中暴露 Windows/Conda 的阻塞 stdin 与 NumPy/OpenBLAS DLL 初始化冲突，已改用 `PeekNamedPipe` 非阻塞检查并新增真实子进程回归。这是本次重构发现并修复的兼容边界，不是旧版空白界面的原始原因。
- 未进行实际 Arduino HID 输入/游戏内动作验收；CI 工作流已更新，本次只在本地验证，未触发云端运行。

## 2026-09-18 — 乐谱格式改为「按键 + 停顿」

### 背景
原来乐谱用音名（`H1`/`M3`/`L6`）记音，播放时由 `music.py` 的 `NOTE_TO_KEY` 转成键位字母。现直接改用键位字母记谱，去掉这层转换。

### 变更
- **`backend/features/music.py`**：删除 `NOTE_TO_KEY`，新增 `VALID_KEYS`；`parse_score` 直接解析 `按键 停顿ms`（按键 = B/F/G/H/J/K/T/Y/U），非法按键静默跳过。
- **`scripts/midi2score.py`**：`DEGREE_TARGETS`/`ALL_NOTES` 直接产出键位字母，MIDI 转换结果即按键谱。
- **`scripts/convert_scores_to_keys.py`（新增）**：一键把 `data/scores/` 里已有的音名谱原地转成按键谱（幂等）。

### 迁移
已用 `convert_scores_to_keys.py` 把 `data/scores/` 下 7 首谱面（1762 行）全部转成按键格式。

## 2026-09-02 — 自动演奏「音乐播放器化」改造

### 背景
自动演奏链路（简谱 → Arduino → 按键）此前已打通，但交互是「单个下拉选谱 + 循环开关」。本轮将其升级为音乐播放器式的**歌单 + 悬浮播放控件**体验。

### 新增
- **歌单面板**：主界面「自动演奏」页改为列表，展示 `data/scores/` 下全部 `.txt`（显示时去掉后缀），点击选曲并高亮当前曲，保留「打开文件夹」便于加歌。
- **演奏悬浮窗控件**：悬浮窗改为四个图标按钮 —— 上一曲 / 暂停·播放 / 下一曲 / 播放模式（模式按钮图标随当前模式变化）。
- **五态播放模式**：`sequential`(列表播放) / `single`(单曲播放) / `repeat_one`(单曲循环) / `repeat_all`(列表循环) / `shuffle`(随机播放)。悬浮窗模式按钮按此顺序循环切换。
  - `single`（单曲播放）语义 = **只播完当前这一首就停**，不自动切下一首。
  - 手动「下一曲」任何模式下都生效（shuffle 时为随机）；「上一曲」始终按歌单列表 -1（不回随机历史）。
- **暂停 / 续播**：暂停在音符边界生效，续播从**停住的那一个音**继续（从暂停处精确续播）。
- **每首前倒计时**：每首歌开始前统一倒计时 3 秒（`COUNTDOWN_SECS = 3`），原首曲 5 秒倒计时一并改为 3 秒。

### 变更
- 模式显示名：`顺序播放` → `列表播放`（内部 key `sequential` 不变，无需迁移旧配置）。
- `data/scores/` 简谱文件格式沿用：每行 `音符 停顿ms`，注释行以 `#` 开头（详见 `docs/FEATURES.md` 的简谱一节）。
- 图标方案：新建 `frontend/src/components/MusicIcons.ts`，用**内联 SVG + Vue `defineComponent`** 手写 8 个图标，不引入 `@element-plus/icons-vue`。

### 修复
- **实例属性遮蔽方法名 bug（关键）**：`music.py` 早期版本里 `self._loop = bool(...)` 把「循环模式」存到了与演奏线程方法 `_loop()` 同名的地方，导致 `threading.Thread(target=self._loop)` 拿到的是布尔值 `False` 而非方法，线程启动即崩，症状为「点开始无倒计时、无按键、永远显示运行中」。修复 = 布尔标志改名 `_loop_mode`（后进一步重构为 `_mode` 枚举）。

### 排查经验（重要）
后端是**长驻进程**，改了 `backend/**` 的 `.py` 后**必须重启 uvicorn** 才会生效。曾出现「面板能加载但切不了播放模式、报 `未知播放模式：single`、倒计时还是 5 秒」——原因是 8790 端口上仍跑着旧版本后端。处置：`netstat -ano | grep :8790` 找到 PID → `taskkill //PID <pid> //F` → 用 `backend/main.py` 头注释里的命令重新拉起。前台改完代码、后台进程不重启，是最容易踩的坑。

## 2026-09 上旬 — 重构为 Vue3 + FastAPI + Tauri 2 多窗口架构（未提交基线）

> 工作区里 `backend/`、`frontend/` 均为未提交的新目录；旧 `main.py`、`loco_box/ui/`（CustomTkinter 桌面版）已在工作区删除。本次重构把「单机 Python GUI」改为「本地 Web 前端 + 本地后端 + 系统级悬浮窗」。

### 新增
- **FastAPI 后端**（`backend/`，端口 8790）：REST `/api/**` + WebSocket `/ws` 事件推送；进程内单例 `state`（Arduino 控制器 / 事件总线 / 配置 / 功能注册表）。
- **Feature 插件框架**（`backend/features/__init__.py`）：抽象基类 + `@register` 装饰器 + `create_features(ctx)` 自动装配。新增功能只需继承 `Feature` 并注册（见 `docs/FEATURES.md`）。
- **Vue3 + Element Plus 前端**（`frontend/src/`）：主窗口（侧栏功能切换 + 中央面板 + 右侧可折叠实时预览）+ 多个独立悬浮窗视图。
- **Tauri 2**（`frontend/src-tauri/`）：声明式创建多个无边框/透明/置顶 WebView 窗口（见 `docs/ARCHITECTURE.md`），通过 `invoke` 暴露窗口显隐命令；主窗口关闭即退出整个进程并杀掉后端子进程。
- **全局实时预览**：`backend/core/preview.py` 周期性截主屏，经 WS `frame` 事件推给前端（仅当有 WS 订阅者时）。
- **一键启动**：`start.bat` 探测 `/api/health`，未运行则以隐藏窗口拉起 `npm run tauri dev`（前端自建后端），轮询等待就绪后退出。

### 变更
- 三个功能的宿主从 tkinter 线程 + 回调改为 **Feature 对象 + 事件总线**：
  - 惊喜盒子：复用 `loco_box.matcher/monitor`，截图/状态经 `ctx.bus` 推送。
  - 丢球：循环「鼠标左键长按 → Shift」，四段时长可配。
  - 自动演奏：新增音乐播放器式逻辑（见本日条目）。
- 串口连接策略保持：启动/首次运行时连接一次并等 3 秒复位，之后**保持连接**、按键瞬间发送（见 `docs/PROTOCOL.md`）。

### 文档
- 本仓库文档目录 `docs/` 于本轮整体刷新为当前架构（技术栈 / 架构 / API / 功能 / 协议 / 变更记录）。
