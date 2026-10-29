# 功能详解与扩展指南

本项目是「多功能游戏自动化盒子」。每个功能 = 一个后台动作循环 + 主界面配置面板（可选）+ 专属悬浮窗（可选）。目前有三个功能：`box_monitor`（惊喜盒子）、`throw`（丢球）、`music`（自动演奏）。

读本篇前建议先看 `docs/ARCHITECTURE.md`（进程/窗口/数据流）与 `docs/API.md`（Feature 基类与路由）。三份合起来就是「下一轮扩展」的地图。

## 通用运作方式

- 每个功能是一个 `Feature` 子类（`backend/features/*.py`），在 `create_features()` 中被 import 触发注册，实例化时注入 `FeatureContext`。
- **主界面**：`frontend/src/MainView.vue` 的 `panels` 表把 `feature_id` 映射到配置组件（`frontend/src/views/*.vue`）。
- **悬浮窗**：前端 `invoke('show_xxx_overlay')` 时才创建对应窗口（label 如 `music_overlay`），关闭时释放 WebView 并保存位置。
- 状态与画面：后台线程调用 `ctx.bus.publish_*` → WebSocket → 前端窗口接收。前端 `connectWs(...)` 订阅本窗口共享连接，`onUnmounted` 释放；实时预览需显式订阅 `preview`。拉取状态使用 `usePolling`，避免请求重叠并在隐藏/卸载时停止。

---

## 功能一：惊喜盒子（`box_monitor`）

文件：`backend/features/box_monitor.py`（配置面板 `frontend/src/views/BoxMonitorConfig.vue`，悬浮窗 `box_overlay`）。

**做什么**：循环截取监控区域，识别「幸运惊喜盒」白字 → 出现后预约按键 `1` → 消失后截图存档，反复如此（模拟玩家开盒）。

**识别算法**（复用库 `loco_box/matcher.py`，算法要点见 `docs/ARCHITECTURE.md`「功能运行时速览 · 惊喜盒子」；该算法对「白字+白底」用笔画指纹而非模板匹配）：

1. 判断整个区域是否为白场（纯白文字弹出时背景为白）。
2. top-hat 提取细白笔画 → 阈值二值化 → 笔画掩码。
3. 垂直投影切字符 → 多因子加权评分（覆盖度/IoU/波段/布局/字符数）。
4. 返回 `MatchAnalysis{absent, strong_present, weak_present, score}`。

**状态机**：`loco_box/monitor.py` 的 `MonitorThread`（0.3s 轮询）。

```
WAITING   每 0.3s 检测 strong_present，连续 4 次 → WATCHING
WATCHING  每 0.3s 检测 absent 或 !weak_present，连续 3 次
          → on_screenshot（区域 B 截图 + 当前计数）→ 回 WAITING
```

**后端回调接线**（把库回调桥到事件总线）：
- `_on_box_appear` → 计数 +1、`publish_count`、按 `trigger_delay` 预约 `threading.Timer` → `_send_key`（`press_key("1", hold_ms=50)`，并校验已连接）。
- `_on_screenshot` → `publish_shot(截图b64, count)`。
- `_on_error` → `publish_status("监控错误: ...")` + 自停。

**配置**（`config_schema` + 全局区域）：`delay` 截图延时(s) / `threshold` 匹配阈值 / `brightness` 亮度阈值 / `trigger_delay` 触发延时(s)；区域存在 `template_region`（监控）与 `region_b`（截图）。模板持久化为 `data/template.png`（`POST /api/features/box_monitor/template` 抓取当前监控区域生成）。

**注意**：区域和模板都在 GUI 里框选生成，后端启动时校验：缺区域 / 缺模板 / 模板笔画不足都会 `raise ValueError`（→ HTTP 400 提示）。

---

## 功能二：丢球（`throw`）

文件：`backend/features/throw.py`（配置面板 `frontend/src/views/ThrowConfig.vue`）。

**做什么**：无限循环「鼠标左键长按 → 松开后间隔 → Shift 长按 → 松开后间隔」，无任何识别。用于在游戏里不断丢球。

**四段时间**（ms，`config_schema` 默认值）：`mouse_hold` 200 / `mouse_gap` 150 / `shift_hold` 50 / `shift_gap` 50。

**实现**：`_loop` 后台线程，先确保 Arduino 已连接（未连接则后台 connect + 就绪提示），然后 `while self._active` 依次 `send("MOUSE_LEFT", mouse_hold)`、sleep gap、`send("LSHIFT", shift_hold)`、sleep gap。`stop()` 只翻 `_active=False`，无事件，靠下轮循环判断退出。

---

## 功能三：自动演奏（`music`）⭐ 本轮重点

文件：`backend/features/music.py`（面板 `frontend/src/views/MusicConfig.vue`，悬浮窗 `music_overlay`，图标 `frontend/src/components/MusicIcons.ts`）。

**做什么**：把 `data/scores/` 里的按键谱当「歌曲」，演奏时用 Arduino HID 敲一台 9 音手碟。交互做成音乐播放器：歌单面板选曲 → 悬浮窗里上一曲/暂停·播放/下一曲/播放模式。

> 完整**域设计**（手碟 9 音音阶、音符↔键盘映射、简谱格式约定、时序模型、播放模式语义、真实谱面示例）见 **[docs/MUSIC.md](MUSIC.md)**；本节只讲后端实现与接线，域细节不再重复。

### 播放模式（五态）

后端 `MODES = ("sequential", "single", "repeat_one", "repeat_all", "shuffle")`。

| key | 中文 | 当前曲自然播完后 |
|-----|------|------------------|
| `sequential` | 列表播放（默认） | 列表内下一首；到底则停 |
| `single` | 单曲播放 | **停**（只播当前这一首）|
| `repeat_one` | 单曲循环 | 重复当前这一首 |
| `repeat_all` | 列表循环 | 列表内下一首，到尾回第一首 |
| `shuffle` | 随机播放 | 随机挑一首（排除当前曲） |

手动「下一曲 / 上一曲」与模式无关：`_advance_manual(±1)`，shuffle 时「下一曲」取随机、其余按列表 `±1`（可环绕）。改键只改 `_current` 并落盘；若正在播放，再由 `_next_event`/`_prev_event` 打断当前曲、外层循环按新 `_current` 续。

### 暂停 / 续播语义

`pause()` 置 `_paused=True`（不打断当前正在敲的音）；`_loop` 在**下一个音符边界**看到 `_paused` 就发布「已暂停」并 `while self._paused and self._active: time.sleep(0.1)` 原地等待。`resume()` 清标志、发布「继续演奏」，随后从**停住的那个音**继续。`stop()` 同时清 `_paused` 并 set `_stop_event`，等待循环跳出。

### 演奏线程伪码（`_loop`）

```
若 Arduino 未连接：开后台线程 connect（与首曲倒计时并行，约 3s 复位）
while self._active:
    for 3..1: publish "准备开始 · i"; _stop_event.wait(1) 可中断退出
    # 仅第一首歌的倒计时后检查一次连接结果（此后 connect_thread 置 None，不再重复连接）
    notes = 读当前曲 → parse
    if 无有效音: 按模式 _advance_after_song()（None→播放结束），continue
    for i, (key, pause_ms) in enumerate(notes):
        if _paused: 等待续播
        if _next/_prev_event.set(): clear + break  # 切歌
        publish "演奏中 · {曲名} · 第 i/n 音"
        arduino.send(key, HOLD_MS)   # 失败→停
        _stop_event.wait(pause_ms/1000)  # 停止可中断
    else:  # 自然播完，未被 break
        按模式 _advance_after_song()，None → 播放结束
```

要点：
- **每首歌前都有 3s 倒计时**（含第一首），不是只在启动时倒计时一次——这是为了给用户每次切到游戏窗口的时间。
- **暂停点在音符边界**；切歌打断只发生在音符边界。
- 所有可等待处都用 `_stop_event.wait` 或 `_paused` 轮询，保证 `stop()` 最多延迟一拍就能停。
- 演奏进度经 `publish_status` 逐音广播，前端悬浮窗底部状态行实时显示。

### 控制入口（路由在 `docs/API.md`）

`/api/music/state` 是播放器唯一状态源（`playlist/current/mode/running/paused`），悬浮窗与面板都轮询它；`select/next/prev/mode/pause/resume` 是变更指令。

### 状态落盘

`mode` + `current` 持久化到 `settings.json` 的 `music` 命名空间（`_save_state()`）。启动时若 `current` 已不在歌单（文件被删）会回退到歌单第一首。

### 悬浮窗按钮与状态

四按钮（`music_overlay`）：上一曲 / 暂停·播放 / 下一曲 / 播放模式。播放/暂停按钮三态逻辑：
`!running → startFeature('music')`；`running && paused → musicResume()`；`running && !paused → musicPause()`。
模式按钮按 `MODES` 顺序取下一模式 `setMusicMode(next)`，图标随 `mode` 在 `MusicIcons.ts` 的五种图标间切换。关闭悬浮窗 = `stopFeature('music')` + `hide_music_overlay`。

### 自定义 / 加歌

1. 往 `data/scores/` 丢一个 UTF-8 `.txt` 按键谱（格式见上）。
2. 主界面音乐页点「打开文件夹」或「刷新」即可看到。
3. 键位若要换歌（不同音阶），改 `VALID_KEYS`（键位集合）与 `scripts/midi2score.py` 的 `DEGREE_TARGETS`/`ALL_NOTES`，键值保持大写字母（固件会转小写）。

---

## 如何新增一个功能（扩展指南）

按以下顺序，通常一小时内能接完：

1. **后端**：`backend/features/xxx.py` 写 `@register class XxxFeature(Feature)`，实现 `start(config)/stop()/is_running()`，需要配置就声明 `config_schema`（会同时决定默认值 merge 与前端可选表单）。**在 `backend/features/__init__.py` 的 `create_features()` 里 import 它**（触发注册）——这是最容易漏的一步。
2. **路由（可选）**：功能专属命令在 `backend/api/routes.py` 里用 `state.features.get("xxx")` 拿实例添加端点；参考 `music` 那组（`/api/music/*`）的写法：先 `_get_music()` 守卫再调用公开方法。
3. **面板**：`frontend/src/views/XxxConfig.vue` 写配置组件，在 `MainView.vue` 的 `panels` 表注册 `xxx: XxxConfig`。
4. **悬浮窗（可选）**：
   - `frontend/src-tauri/src/overlays.rs` 添加按需创建/释放逻辑（无边框/透明/置顶；不应抢游戏焦点时加 `.focusable(false)`），暴露异步 `show_xxx_overlay`/`hide_xxx_overlay` 命令，在 `lib.rs` 的 `generate_handler!` 中登记。不要在 `.setup()` 里预建隐藏 WebView。
   - 写视图组件，在 `frontend/src/App.vue` 的 `detectWindow()` 里按窗口 label 分发渲染。
5. **复用底座**：按键一律走 `ctx.arduino`（内部共享同一持久串口连接）；实时提示走 `ctx.bus.publish_status`。**禁止**直接 new `SerialBridge` 去连接——串口只能被共享底座独占。

### 新功能自检清单

- [ ] `create_features()` 里 import 了模块
- [ ] 运行时按键用的是 `ctx.arduino`（不是自建连接）
- [ ] 后台线程里的任何长等待都能被 `stop()` 打断（用 `Event.wait` 而非裸 `sleep`）
- [ ] `settings.json` 若新增了持久字段，`docs/API.md` 配置一节有提
- [ ] 改动涉及后端 `.py` → **重启 uvicorn** 再验证（见 `docs/CHANGELOG.md` 排查经验）
