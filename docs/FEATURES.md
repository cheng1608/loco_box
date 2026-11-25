# 功能详解与扩展指南

本项目是「多功能游戏自动化盒子」。每个功能 = 一个后台任务 + 主界面配置面板（可选）+ 专属悬浮窗（可选）。目前有四个功能：`box_monitor`（惊喜盒子）、`throw`（丢球）、`music`（自动演奏）、`pet_viewer`（精灵查看）。

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

**实现**：启动先申请设备所有权，后台线程确保 Arduino 连接后发送带 owner 的鼠标/Shift 命令；保持与间隔用可打断的 Event.wait。停止唤醒等待，旧线程退出并释放设备后才允许重启。

---

## 功能三：自动演奏（`music`）

直接导入 MIDI，保留多轨起音和和弦，适配九音手碟；旧 TXT 曲库仍可播放。面板提供原文件导入、音轨选择、移调、音域策略、冲突分析和控制；悬浮窗复用同一个播放器状态。

音乐域拆分到 `backend/music/`：MIDI reader 保留准确时间轴，compiler 生成完整键状态，library 保存原文件和逐曲设置并缓存解析，scheduler 提供可暂停单调时钟。`backend/features/music.py` 管理实际调度、播放模式和设备会话；API 独立在 `backend/api/music.py`。

- 每首连接就绪后 3 秒倒计时，按绝对时间播放；和弦以一次完整 HID 报告触发。
- 暂停冻结位置并清理当前会话，继续新建会话，不重敲已响音；停止、切歌立即使旧 generation 失效。
- 曲库选择与实际演奏分离；查看另一首详情不打断当前曲，明确播放及上一曲/下一曲才切换。
- 默认复用转谱脚本的自动识调与音级折叠，全部音符都映射演奏；快速重击、同键映射和超设备容量的音自动分次/顺延。
- 播放和暂停都保留设备所有权；结束/停止/错误后释放，串口保持连接。
- `music.state` 事件每 200ms 推送进度，控制变更立即推送完整状态，REST 轮询兜底；不借助全局状态文字推断音乐进度。
- `settings.json` 合并保存模式和选中曲，逐曲适配设置在 `data/music/settings/`，原文件在 `data/music/originals/`。

五种模式、键位映射、MIDI 限制、旧 TXT 格式和使用步骤见 [MUSIC.md](MUSIC.md)。协议、设备能力、固件升级与编译见 [PROTOCOL.md](PROTOCOL.md)。

---

## 功能四：精灵查看（`pet_viewer`）

从本机网卡读取野生交互 PVE 消息，显示敌方精灵的原始性格及已下发的声音、体型、血脉、异色等属性。主面板为 `frontend/src/views/PetViewerConfig.vue`，独立悬浮窗 label 为 `pet_overlay`。

- `backend/pet_viewer/` 维护 Npcap 采集、TCP 重组、握手解密、Protobuf 解析和战斗状态；`backend/features/pet_viewer.py` 管理可停止线程和 generation，`backend/api/pet_viewer.py` 提供专属接口。
- 使用 `data/pet_viewer/resources/` 的配套协议与配置。缺资源或驱动时显示原因，Box 其余功能仍可启动；资源导入工具为 `scripts/import_pet_resources.py`。
- 主性格按原始 `nature` 编号显示，额外战斗属性修正只在详情中展示。缺失字段保持未知；破盾、变身和捕获结算更新同一遭遇。
- 只接受已确认的野生交互 PVE；PVP/玩家证据阻断完整属性解码并撤销同场历史。示例回放清楚标注、不写真实历史。
- 不依赖 Arduino，也不占用设备。`requires_arduino=False` 和 `blocks_region_selection=False` 使断开硬件及区域框选不影响监听；主窗口退出仍统一停止。
- `pet_viewer.state` 事件与 REST 状态快照供主面板/悬浮窗共用。网卡设置使用 `adapter` 键，空字符串自动选择；真实历史位于 `data/pet_viewer/history.sqlite3`。

使用步骤、资源更新与实战验证边界见 [PET_VIEWER.md](PET_VIEWER.md)。

---

## 如何新增一个功能（扩展指南）

按以下顺序，通常一小时内能接完：

1. **后端**：`backend/features/xxx.py` 写 `@register class XxxFeature(Feature)`，实现 `start(config)/stop()/is_running()`，需要配置就声明 `config_schema`（会同时决定默认值 merge 与前端可选表单）。**在 `backend/features/__init__.py` 的 `create_features()` 里 import 它**（触发注册）——这是最容易漏的一步。
2. **路由（可选）**：功能专属命令可建立独立 router，参考 `backend/api/music.py`，并在 `backend/main.py` 挂载。
3. **面板**：`frontend/src/views/XxxConfig.vue` 写配置组件，在 `MainView.vue` 的 `panels` 表注册 `xxx: XxxConfig`。
4. **悬浮窗（可选）**：
   - `frontend/src-tauri/src/overlays.rs` 添加按需创建/释放逻辑（无边框/透明/置顶；不应抢游戏焦点时加 `.focusable(false)`），暴露异步 `show_xxx_overlay`/`hide_xxx_overlay` 命令，在 `lib.rs` 的 `generate_handler!` 中登记。不要在 `.setup()` 里预建隐藏 WebView。
   - 写视图组件，在 `frontend/src/App.vue` 的 `detectWindow()` 里按窗口 label 分发渲染。
5. **复用底座**：按键先 `acquire(feature_id)`，发送带 `owner=feature_id`，finally 中 `release(feature_id)`；一律走 `ctx.arduino`（内部共享同一持久串口连接）；实时提示走 `ctx.bus.publish_status`。**禁止**直接 new `SerialBridge` 去连接——串口只能被共享底座独占。

### 新功能自检清单

- [ ] `create_features()` 里 import 了模块
- [ ] 运行时按键用的是 `ctx.arduino`（不是自建连接）
- [ ] 后台线程里的任何长等待都能被 `stop()` 打断（用 `Event.wait` 而非裸 `sleep`）
- [ ] `settings.json` 若新增了持久字段，`docs/API.md` 配置一节有提
- [ ] 改动涉及后端 `.py` → **重启 uvicorn** 再验证（见 `docs/CHANGELOG.md` 排查经验）
