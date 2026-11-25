# 后端 API 参考

后端是单机 FastAPI（默认 `http://127.0.0.1:8790`）。前端所有请求都经 `frontend/src/api/client.ts` 的 `http<T>()` 封装（自动带 `Content-Type: application/json`，非 2xx 时抛出带 `detail` 的 `Error`）。

## 约定

- 所有 JSON 请求体字段用 snake_case（如 `hold_ms`），与 Python 一致。
- 错误统一返回 `{"detail": "..."}`，HTTP 状态码 400（业务校验失败）/ 404 / 409 / 500。
- 前端仅通过 REST 做「指令」，实时画面/状态走 WebSocket（见下）。

## REST 端点

### 基础 & 健康

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | `{status, service:"loco_box", ready, protocol:1, pid}`；表示服务身份与就绪状态，不表示桌面窗口存在或 Arduino 已连接 |
| GET | `/api/status` | `{arduino_connected, port, owner, capabilities}` |
| GET | `/api/ports` | `{ports: string[]}` 当前所有串口名 |

### Arduino

| 方法 | 路径 | 请求体 | 说明 |
|------|------|--------|------|
| POST | `/api/arduino/connect` | `{port: "AUTO"}` | 连接；`AUTO` 自动检测（`find_arduino` 优先、配置兜底）。阻塞约 3s（复位等待），请只在启动/首次时调用 |
| POST | `/api/arduino/disconnect` | — | 先停止依赖 Arduino 的功能，再全释放并断开；精灵监听继续运行 |
| POST | `/api/key` | `{key, hold_ms?}` | 发送一次按键，hold 默认 50ms |
| POST | `/api/mouse` | `{button?:"MOUSE_LEFT"}` | 发送鼠标点击 |

### 功能（Feature 通用）

功能通过 `{feature_id}` 统一启停，`feature_id ∈ {box_monitor, throw, music, pet_viewer}`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/features` | `{features:[{id,name,running}]}` |
| GET | `/api/features/{id}/config` | `{config}` = 默认值 merge 已存值 |
| PUT | `/api/features/{id}/config` | 请求体 `{config:{...}}`，合并更新该功能命名空间，保留未提交字段 |
| POST | `/api/features/{id}/start` | 启动；校验失败 400，设备被占用 409 |
| POST | `/api/features/{id}/stop` | 停止 |
| POST | `/api/features/box_monitor/template` | 抓当前监控区域为白字模板并保存 |

### 区域框选

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/region/select` | 弹出全屏半透明框选，阻塞直到选完；`{ok, region?, cancelled?}`。有阻止框选的功能运行中时返回 409；独立精灵监听不阻止框选 |

### 自动演奏（`music`）

音乐路由在 `backend/api/music.py`。导入接收原始字节，不使用 multipart。播放控制返回完整 state；失败保留清晰 HTTP detail。

| 方法 | 路径 | 请求 / 返回 |
|---|---|---|
| GET | `/api/music/library` | `{songs}`，刷新 MIDI 与旧 TXT 曲库 |
| POST | `/api/music/import?filename=...` | application/octet-stream 原文件 → `{song, duplicate}`；单文件 16MB，超限 413 |
| GET | `/api/music/songs/{id}` | `{song, tracks, settings, analysis}` |
| DELETE | `/api/music/songs/{id}` | 从曲库移除，返回 `{ok, song_id, songs, state}`；正演奏/准备的曲目需先 stop，未释放时 409；不存在 404；文件操作失败 500 并回滚 |
| GET / PUT | `/api/music/songs/{id}/settings` | GET 同详情；PUT 直接提交设置对象，合并保存并返回新详情 |
| GET | `/api/music/state` | 播放器完整状态 |
| POST | `/api/music/select` | `{song_id}` 或旧 `{name}`，仅选择查看 |
| POST | `/api/music/play` | 可选 `{song_id}`，播放选中曲；播放中明确切换 |
| POST | `/api/music/pause` / `resume` / `stop` | 暂停、续播、停止 |
| POST | `/api/music/next` / `prev` | 上下曲，播放中切换实际曲目 |
| POST | `/api/music/mode` | `{mode}`，五种模式见 MUSIC.md |
| GET | `/api/music/scores` / `scores/{name}` | 兼容旧 TXT 列表 / 原文 |
| POST | `/api/music/open_folder` | 打开旧 TXT 目录 data/scores |
| POST | `/api/music/parse` | 旧调试 `{score}` → `{count, notes}` |

state 保留 `playlist/current/mode/running/paused`，增加 `phase`（stopped/preparing/countdown/playing/paused/finished/error）、`selected_song_id`、`playing_song_id`、`playing_name`、`position_ms`、`duration_ms`、`speed`、`countdown_remaining`、`revision`、`error` 以及 `device`（connected/protocol/max_keys/midi_supported）。

settings 和 analysis 字段见 [MUSIC.md](MUSIC.md)。手动 key/mouse 在设备占用时返回 409，未连接或发送失败返回 503。控制命令接受后仍可能异步连接失败，客户端必须显示 state.error。

### 精灵查看（`pet_viewer`）

路由位于 `backend/api/pet_viewer.py`。实时监听走通用 Feature 启停；`features.pet_viewer` 配置为 `{adapter:""}`，空值表示自动选择网卡。

| 方法 | 路径 | 请求 / 返回 |
|---|---|---|
| GET | `/api/pet-viewer/state` | 当前完整状态，包含就绪检查、监听阶段和精灵列表 |
| GET | `/api/pet-viewer/adapters` | `{available, adapters:[{name,description}], message}`；缺少驱动也返回明确状态 |
| POST | `/api/pet-viewer/demo` | 开始合成报文回放，返回状态；来源为“示例回放”，不写真实历史 |
| POST | `/api/pet-viewer/select` | `{pet_id:int}`，切换当前展示的已登记敌方精灵，返回状态 |
| GET | `/api/pet-viewer/history?limit=50&offset=0` | `{items,total}`，分页读取真实遭遇历史 |

state 包含 `running`、`revision`、`phase`、`status`、`message`、`source`、`resources:{ready,message,version?}`、`npcap_available`、`packet_count`、`decoded_count`、`pets`、`selected`（对象或 null）、`battle_id`，以及历史写入错误提示 `history_error`。每只精灵包含原始性格编号/名称、性格提示、修正详情和已下发的其他属性。具体字段以接口类型为准，缺失属性不会补成有效零值。

精灵查看不访问 Arduino。停止监听、监听错误、PVP 阻断与正常战斗结束具有不同的状态语义，客户端应直接使用 `phase/status/message`，不根据全局状态文字推断。资源与使用说明见 [PET_VIEWER.md](PET_VIEWER.md)。

## WebSocket `/ws`

用途：后端 → 前端事件推送。`/ws` 仅接收状态、计数、截图和功能事件；`/ws?preview=1` 额外订阅实时预览帧。前端 `connectWs(handlers, {preview?: boolean})` 在同一窗口共享一条连接，断线按 0.5–5 秒退避重连，返回取消订阅函数。折叠预览或主窗口不可见时取消帧订阅。后端监听客户端断开，即使没有事件也会清理订阅。

事件由 `backend/core/events.py` 的 `EventBus` 发布（消息 `type` 字段区分）：

| type | 载荷字段 | 含义 |
|------|----------|------|
| `frame` | `data`(base64 JPEG) | 主屏预览，等比例缩至 960×540 内，300ms/帧；仅明确订阅 preview 的连接接收，慢连接仅保留最新一帧 |
| `shot` | `data`, `count` | 惊喜盒子消失后的区域截图 + 当前计数 |
| `count` | `count` | 惊喜盒子命中计数 |
| `status` | `text` | 状态文本（倒计时 / 演奏进度 / 连接提示等） |
| `event` | `name`, `data` | 通用事件；music.state 携带完整播放状态，周期进度最多 5Hz；music_state_changed 提醒关键状态变更；pet_viewer.state 携带精灵查看完整状态 |

跨线程说明：`EventBus.publish_*` 可在任意后台线程调用，内部经 `loop.call_soon_threadsafe` 投递到 asyncio 事件循环再广播，避免直接操作 `asyncio.Queue` 的线程安全隐患。

## Feature 插件基类

```python
class Feature(ABC):
    id: str                 # 唯一标识（路由 /{id}/... 用它）
    name: str               # 前端侧栏显示名
    requires_arduino: bool   # 默认 True；纯监听功能设 False
    blocks_region_selection: bool  # 默认 True；精灵监听设 False
    config_schema: List[Dict]  # 参数声明（供文档/默认值，type 可为 select/number/text/bool）
    def default_config(self) -> Dict        # 由 config_schema 生成
    def start(self, config: Dict) -> None   # 参数=默认 merge 已存；业务错误 raise ValueError
    def stop(self) -> None
    def is_running(self) -> bool
```

`FeatureContext`（`ctx`）注入三个单例：

| 属性 | 对象 | 说明 |
|------|------|------|
| `ctx.arduino` | `ArduinoController` | `acquire(owner)` / `release(owner)` / `connect(com)` / `send(key, hold_ms, owner=...)` / `capabilities()` / `port()` |
| `ctx.bus` | `EventBus` | `publish_status(text)` 最常用；另有 `publish_shot/frame/count/event` |
| `ctx.config` | `ConfigStore` | `get(feature_id)` / `update(feature_id, patch)`（合并）/ `set(feature_id, dict)`（整份替换）/ `get_global(key)` / `set_global(key, value)` |

注册流程见 `docs/FEATURES.md`「如何新增一个功能」。

## 配置持久化（`data/settings.json`）

```
{
  "com_port": "COM8",            # 最近一次成功连接的 COM 口（find_arduino 失败时兜底）
  "features": {
    "box_monitor": { ... },      # 每功能的独立命名空间
    "throw":      { ... },
    "music":      { "mode": "...", "current": "...", "selected_song_id": "..." },
    "pet_viewer": { "adapter": "" }  # 空字符串自动选择网卡
  }
}
```

配置受 RLock 保护，读取返回副本，写入临时文件后原子替换。局部字段请使用 `ConfigStore.update`，避免覆盖播放设置。MIDI 逐曲设置独立保存，见 MUSIC.md。运行数据在 `data/`（已 gitignore）。

加载时兼容 UTF-8 BOM；旧版顶层盒子参数自动归入 `features.box_monitor` 并清除顶层残留。新旧字段同时存在时，以命名空间内的新值为准，保留其他功能和全局字段；迁移写入失败不会截断原配置。
