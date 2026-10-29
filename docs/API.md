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
| GET | `/api/status` | `{arduino_connected, port}` |
| GET | `/api/ports` | `{ports: string[]}` 当前所有串口名 |

### Arduino

| 方法 | 路径 | 请求体 | 说明 |
|------|------|--------|------|
| POST | `/api/arduino/connect` | `{port: "AUTO"}` | 连接；`AUTO` 自动检测（`find_arduino` 优先、配置兜底）。阻塞约 3s（复位等待），请只在启动/首次时调用 |
| POST | `/api/arduino/disconnect` | — | 断开 |
| POST | `/api/key` | `{key, hold_ms?}` | 发送一次按键，hold 默认 50ms |
| POST | `/api/mouse` | `{button?:"MOUSE_LEFT"}` | 发送鼠标点击 |

### 功能（Feature 通用）

功能通过 `{feature_id}` 统一启停，`feature_id ∈ {box_monitor, throw, music}`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/features` | `{features:[{id,name,running}]}` |
| GET | `/api/features/{id}/config` | `{config}` = 默认值 merge 已存值 |
| PUT | `/api/features/{id}/config` | 请求体 `{config:{...}}`，**整份替换**该功能的命名空间 |
| POST | `/api/features/{id}/start` | 启动；业务错误返回 400 `detail` |
| POST | `/api/features/{id}/stop` | 停止 |
| POST | `/api/features/box_monitor/template` | 抓当前监控区域为白字模板并保存 |

### 区域框选

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/region/select` | 弹出全屏半透明框选，阻塞直到选完；`{ok, region?, cancelled?}`。有任一功能运行中时返回 409 |

### 自动演奏（`music`）

| 方法 | 路径 | 请求体 | 说明 |
|------|------|--------|------|
| GET | `/api/music/scores` | — | `{scores:[...txt 文件名]}` 歌单 |
| GET | `/api/music/scores/{name}` | — | `{name, content}` 读按键谱原文（name 做 basename 防穿越） |
| POST | `/api/music/open_folder` | — | 用系统文件管理器打开 `data/scores/` |
| POST | `/api/music/parse` | `{score}` | 调试用：返回解析出的 `{count, notes:[{key,pause}]}` |
| GET | `/api/music/state` | — | `{playlist, current, mode, running, paused}` 播放器整体状态 |
| POST | `/api/music/select` | `{name}` | 在歌单中选中当前曲（不改播放） |
| POST | `/api/music/next` | — | 下一曲（播放中会打断当前曲切歌） |
| POST | `/api/music/prev` | — | 上一曲（同上） |
| POST | `/api/music/mode` | `{mode}` | 切换播放模式；非法模式返回 400 |
| POST | `/api/music/pause` | — | 暂停（音符边界生效） |
| POST | `/api/music/resume` | — | 从暂停处续播 |

`mode` 合法值见 `docs/FEATURES.md` 播放模式一节。

## WebSocket `/ws`

用途：后端 → 前端事件推送。`/ws` 仅接收状态、计数、截图和功能事件；`/ws?preview=1` 额外订阅实时预览帧。前端 `connectWs(handlers, {preview?: boolean})` 在同一窗口共享一条连接，断线按 0.5–5 秒退避重连，返回取消订阅函数。折叠预览或主窗口不可见时取消帧订阅。后端监听客户端断开，即使没有事件也会清理订阅。

事件由 `backend/core/events.py` 的 `EventBus` 发布（消息 `type` 字段区分）：

| type | 载荷字段 | 含义 |
|------|----------|------|
| `frame` | `data`(base64 JPEG) | 主屏预览，等比例缩至 960×540 内，300ms/帧；仅明确订阅 preview 的连接接收，慢连接仅保留最新一帧 |
| `shot` | `data`, `count` | 惊喜盒子消失后的区域截图 + 当前计数 |
| `count` | `count` | 惊喜盒子命中计数 |
| `status` | `text` | 状态文本（倒计时 / 演奏进度 / 连接提示等） |
| `event` | `name`, `data` | 通用事件 |

跨线程说明：`EventBus.publish_*` 可在任意后台线程调用，内部经 `loop.call_soon_threadsafe` 投递到 asyncio 事件循环再广播，避免直接操作 `asyncio.Queue` 的线程安全隐患。

## Feature 插件基类

```python
class Feature(ABC):
    id: str                 # 唯一标识（路由 /{id}/... 用它）
    name: str               # 前端侧栏显示名
    config_schema: List[Dict]  # 参数声明（供文档/默认值，type 可为 select/number/text/bool）
    def default_config(self) -> Dict        # 由 config_schema 生成
    def start(self, config: Dict) -> None   # 参数=默认 merge 已存；业务错误 raise ValueError
    def stop(self) -> None
    def is_running(self) -> bool
```

`FeatureContext`（`ctx`）注入三个单例：

| 属性 | 对象 | 说明 |
|------|------|------|
| `ctx.arduino` | `ArduinoController` | `is_connected()` / `connect(com)` / `send(key, hold_ms)` / `press_key(key, hold_ms)` / `port()` |
| `ctx.bus` | `EventBus` | `publish_status(text)` 最常用；另有 `publish_shot/frame/count/event` |
| `ctx.config` | `ConfigStore` | `get(feature_id)` / `set(feature_id, dict)`（整份替换）/ `get_global(key)` / `set_global(key, value)` |

注册流程见 `docs/FEATURES.md`「如何新增一个功能」。

## 配置持久化（`data/settings.json`）

```
{
  "com_port": "COM8",            # 最近一次成功连接的 COM 口（find_arduino 失败时兜底）
  "features": {
    "box_monitor": { ... },      # 每功能的独立命名空间
    "throw":      { ... },
    "music":      { "mode": "...", "current": "..." }
  }
}
```

要点：`ConfigStore.set(feature_id, cfg)` 是**整份替换**该命名空间；启动时后端只读不写；程序目录为 `data/`（已 gitignore）。
