# Loco Box v2.0 开发计划

> **文档状态**: 设计稿，待开发  
> **当前版本基线**: v1.1 (`refactor: 精简界面布局并缩短状态提示`)  
> **最后更新**: 2026-06-09  
> **指令**: 在用户明确要求开始 v2 开发之前，**不要实现本文档中的任何代码**。本文档供 AI 或开发者在未来会话中直接读取并执行。

---

## 1. 背景与动机

### 1.1 项目现状（v1 / v1.1）

洛克王国 s2「幸运惊喜盒」监控工具。当前核心能力：

- 用户在**监控区域**框选包含「幸运惊喜盒」五个白字的区域
- 用户在**截图区域**框选打完盒子后的画面
- 后台线程轮询监控区域，用 **白色笔画指纹匹配**（`WhiteTextMatcher`）检测文字出现与消失
- 文字消失并连续确认后，延迟截图并在 UI 预览区显示
- 配置持久化到 `data/settings.json` 与 `data/template.png`

技术栈：`customtkinter`、`mss`、`numpy`、`Pillow`。无 OCR、无深度学习依赖。

### 1.2 v1.1 UI 变更（已完成）

- 开始/停止合并为同一行工具栏上的**切换按钮**（绿「开始」/ 红「停止」）
- 移除「监控 / 截图」区域尺寸文字行
- 状态栏压缩为单行，文案精简

### 1.3 v2.0 愿景

v2.0 不只是一个「幸运惊喜盒监控器」，而是一个**多功能游戏辅助工具箱**。

**v2 第一阶段目标**（本文档范围）：

> 在保留 v1 快速盒子检测能力的前提下，增加**精灵名识别与会话内计数统计**。

用户打完盒子后，监控区域内会出现精灵名字（非「幸运惊喜盒」文字）。需要 OCR 读出名字并计数。统计数据的展示方式与持久化方案**尚未确定**。

---

## 2. 已确认需求

| 编号 | 需求 | 说明 |
|------|------|------|
| R1 | 盒子出现/消失检测必须**快且准** | 复用 v1 笔画匹配，不改为 OCR |
| R2 | 精灵名识别**不要求快** | 仅在特定时机触发一次 OCR |
| R3 | 精灵名位于**监控区域**内 | 与盒子检测共用同一 `monitor_region` ROI |
| R4 | 统计形式为**计数** | 如 `{"迪莫": 2, "喵呜": 1}` |
| R5 | 统计数据为**会话级临时数据** | 仅在用户点击「开始」到「停止」之间存活 |
| R6 | 统计数据的 UI / 导出 / 持久化 | **暂不实现**，用途未想好 |
| R7 | 无法获取游戏字体文件 | **放弃**字体模板匹配方案 |
| R8 | OCR 触发门禁 | 仅当「有文字」且「不是幸运惊喜盒」时才进入 OCR 链路 |

### 2.1 明确不做（本阶段）

- 不将统计数据写入 `data/` 或任何文件
- 不设计统计面板 / 导出功能（可预留接口）
- 不替换 v1 快速检测链路
- 不实现字体模板匹配
- 不在用户要求前开始编码

---

## 3. 核心设计：双链路架构

### 3.1 设计原则

**快慢分离**：轮询循环只跑轻量快速链路；OCR 仅在截图后的单次门禁通过时执行。

```
                    ┌─────────────────────────────────────┐
  每 ~300ms 轮询     │  链路 1：快速检测（v1 笔画匹配）      │
  monitor_region ──►│  目标：幸运惊喜盒 出现 / 消失          │
                    │  耗时：~5ms/帧                       │
                    └──────────────┬──────────────────────┘
                                   │ 消失确认 + 延迟
                                   ▼
                    ┌─────────────────────────────────────┐
                    │  grab shot_region → 截图预览        │
                    └──────────────┬──────────────────────┘
                                   │ 截图完成后，对 monitor_region 做一次门禁
                                   ▼
                    ┌─────────────────────────────────────┐
                    │  门禁：has_text AND NOT is_box       │
                    └──────────────┬──────────────────────┘
                          否       │ 是
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
              跳过 OCR，回待机           ┌─────────────────────────┐
                                        │  链路 2：慢速 OCR         │
                                        │  目标：读出精灵名         │
                                        │  耗时：~30–100ms，仅一次  │
                                        └────────────┬────────────┘
                                                     ▼
                                        ┌─────────────────────────┐
                                        │  session_stats.record() │
                                        │  会话 Counter += 1        │
                                        └─────────────────────────┘
```

### 3.2 链路 1：快速检测（复用 v1）

**职责**：检测「幸运惊喜盒」出现 → 持续监视 → 消失 → 触发截图。

**实现基础**：现有 `loco_box/monitor.py` + `loco_box/matcher.py`。

| 参数 | v1 当前值 | 说明 |
|------|-----------|------|
| `POLL_INTERVAL` | `0.3` 秒 | 轮询间隔，可保持或微调 |
| `CONFIRM_APPEAR` | `4` | 连续强匹配次数 → 确认出现 |
| `CONFIRM_ABSENT` | `3` | 连续消失确认次数 → 确认消失 |
| `delay_sec` | 用户配置，默认 `1` | 消失确认后延迟再截图 |

**匹配逻辑**（`WhiteTextMatcher.analyze` 返回值 `MatchAnalysis`）：

```python
@dataclass
class MatchAnalysis:
    absent: bool          # True = 视为无目标文字（白屏、无笔画、低重合等）
    strong_present: bool  # 强匹配：确认为幸运惊喜盒
    weak_present: bool    # 弱匹配：可能为幸运惊喜盒
    score: float
```

**出现判定**：`strong_present == True`，连续 `CONFIRM_APPEAR` 次。  
**消失判定**：`absent == True` 或 `weak_present == False`，连续 `CONFIRM_ABSENT` 次。

**注意**：链路 1 只回答「是不是幸运惊喜盒」，不解析具体文字内容。

### 3.3 链路 2：慢速 OCR（新增）

**职责**：在盒子流程完成、门禁通过后，从**监控区域**图像中识别精灵名。

**触发频率**：每次盒子消失截图流程结束后，**最多触发 1 次** OCR（不对轮询循环每帧执行）。

**OCR 引擎**（待开发时选型，优先级如下）：

1. **Windows 内置 OCR**（`Windows.Media.Ocr`）：零模型体积，适合先 POC
2. **RapidOCR**（`rapidocr-onnxruntime`，mobile 模型）：准确率更高，exe 增大约 50–80MB
3. **CnOCR**（`cnocr[ort]`，`ch_ppocr_mobile_v2.0`）：备选

**OCR 优化策略**（实现时采用）：

- 输入为 `monitor_region` 裁剪图（`np.ndarray` BGR），非全屏
- **跳过文字检测模型**，仅做识别（位置固定、横排工整）
- 识别前预处理：放大 2x、白字二值化（可复用 `extract_text_strokes` 逻辑）
- 可选：与上一帧 ROI 做像素 hash diff，无变化则跳过（本链路触发次数少，优先级低）

**OCR 输出**：清洗后的精灵名字符串，如 `"迪莫"`。需处理 OCR 误识别（空格、标点、错字），清洗规则开发时根据样图调整。

### 3.4 门禁逻辑（Gate）

**目的**：防止对「幸运惊喜盒」文字或空白画面做无意义 OCR。

**判定条件**（两者同时满足才进入链路 2）：

```python
def should_run_ocr(match: MatchAnalysis, frame_meta: dict) -> bool:
    # 条件 A：有文字（基于笔画分析，零 OCR 成本）
    has_text = (
        frame_meta["stroke_pixels"] >= MIN_STROKE_PIXELS  # 建议初值 20–40，待样图标定
        and frame_meta["char_count"] >= 1
    )
    # 条件 B：不是幸运惊喜盒
    not_box = not match.strong_present and not match.weak_present
    return has_text and not_box
```

**`frame_meta` 来源**：`extract_text_strokes()` 的返回值（`matcher.py` 中已有 `_analyze_mask`）。

**典型场景真值表**：

| 画面内容 | `strong/weak_present` | `has_text` | 进入 OCR？ |
|----------|----------------------|------------|-----------|
| 幸运惊喜盒 | 命中 | 是 | **否** |
| 精灵名 | 未命中 | 是 | **是** |
| 空白/白屏 | 未命中 | 否 | **否** |
| 其他 UI 文字 | 未命中 | 是 | **是**（计入统计，后续可加黑名单） |

---

## 4. 状态机

### 4.1 状态定义

```
IDLE        等待盒子出现
WATCHING    盒子已确认出现，监视消失
CAPTURING   消失已确认，延迟等待中（尚未截图）
ANALYZING   截图已完成，执行门禁 + 可选 OCR
```

### 4.2 转移表

| 当前状态 | 条件 | 下一状态 | 动作 |
|----------|------|----------|------|
| `IDLE` | 连续 `CONFIRM_APPEAR` 次 `strong_present` | `WATCHING` | `on_status("已出现，监控中")` |
| `IDLE` | 轮询超时 | `IDLE` | `on_status("等待出现 …")` |
| `WATCHING` | 连续 `CONFIRM_ABSENT` 次消失 | `CAPTURING` | `on_status("消失确认 · {delay}s后截图")` |
| `WATCHING` | 轮询 | `WATCHING` | `on_status("消失中 …")` |
| `CAPTURING` | `delay_sec` 到期 | `ANALYZING` | `on_screenshot(shot_region)` |
| `ANALYZING` | `should_run_ocr` 为真 | `IDLE` | `name = ocr.recognize(monitor_roi)` → `stats.record(name)` |
| `ANALYZING` | `should_run_ocr` 为假 | `IDLE` | 跳过 OCR |
| 任意 | 用户停止 / 异常 | `IDLE` | 清理，线程退出 |

### 4.3 与 v1 状态机的关系

v1 `MonitorThread._run` 用 `watching: bool` 隐式表达 `IDLE ↔ WATCHING`。v2 在此基础上扩展 `CAPTURING` 与 `ANALYZING`，或抽离为独立 `Coordinator` 类。推荐**重构**而非在 `monitor.py` 内硬塞 OCR 逻辑。

---

## 5. 会话统计（Session Stats）

### 5.1 生命周期

```
用户点击「开始」
  → SessionStats.reset()        # 新建空 Counter
  → 启动 Coordinator 后台线程

每次 OCR 成功返回精灵名
  → SessionStats.record(name)   # Counter[name] += 1

用户点击「停止」
  → 停止线程
  → SessionStats 对象丢弃（或保留供内存查询直至下次 start）

不写入磁盘，不跨会话保留。
```

### 5.2 数据结构

```python
# 逻辑类型，实现时可简化
SessionStats:
    _counts: dict[str, int]   # 精灵名 → 出现次数

    def reset() -> None: ...
    def record(name: str) -> None: ...       # 清洗后非空才计入
    def snapshot() -> dict[str, int]: ...    # 返回副本，供未来 UI 读取
    def total() -> int: ...                  # 总识别次数
```

### 5.3 数据用途（待定，预留）

以下功能**本阶段不实现**，但 `snapshot()` 应保留以便后续扩展：

- 本次监控结束前的实时列表面板
- 导出 CSV / JSON
- 按精灵汇总胜率等

---

## 6. 模块规划

### 6.1 目标目录结构

```
loco_box/
  pipelines/
    __init__.py
    fast.py           # 链路 1 封装：封装 matcher.analyze 与出现/消失判定
    gate.py           # 门禁：should_run_ocr(match, frame_meta)
    ocr.py            # 链路 2 抽象：OcrEngine 协议 + 具体实现
    coordinator.py    # 状态机，串联 fast / gate / ocr / stats
  session_stats.py    # 会话级 Counter
  monitor.py          # v1 保留或标记 deprecated，逻辑迁入 coordinator
  matcher.py          # 保留，v2 继续复用
  image_ops.py        # 保留，可新增 ocr 预处理函数
  ...
```

### 6.2 接口草案（供 AI 实现时参照）

#### `loco_box/pipelines/ocr.py`

```python
from typing import Protocol
import numpy as np

class OcrEngine(Protocol):
    def recognize(self, bgr: np.ndarray) -> str:
        """输入 BGR ROI，返回识别文本（已 strip）。"""
        ...
```

具体实现类（开发时二选一或使用策略模式）：

- `WindowsOcrEngine`
- `RapidOcrEngine`

#### `loco_box/pipelines/gate.py`

```python
from loco_box.matcher import MatchAnalysis

MIN_STROKE_PIXELS: int = 30  # 待样图标定

def should_run_ocr(match: MatchAnalysis, frame_meta: dict) -> bool: ...
```

#### `loco_box/pipelines/fast.py`

```python
from loco_box.matcher import MatchAnalysis, WhiteTextMatcher
from loco_box.types import Region
import numpy as np

class FastBoxDetector:
    """对单帧 ROI 做盒子匹配，维护 appear/absent 计数。"""

    CONFIRM_APPEAR: int = 4
    CONFIRM_ABSENT: int = 3

    def __init__(self, matcher: WhiteTextMatcher, threshold: float): ...
    def tick(self, frame_bgr: np.ndarray) -> FastTickResult: ...
```

`FastTickResult` 建议字段：

```python
@dataclass
class FastTickResult:
    match: MatchAnalysis
    frame_meta: dict
    box_appeared: bool      # 本 tick 是否触发「出现确认」
    box_disappeared: bool   # 本 tick 是否触发「消失确认」
    appear_hits: int
    absent_hits: int
```

#### `loco_box/pipelines/coordinator.py`

```python
class MonitorCoordinator:
    """替代/包装 MonitorThread，驱动双链路状态机。"""

    def __init__(
        self,
        monitor_region: Region,
        shot_region: Region,
        matcher: WhiteTextMatcher,
        ocr: OcrEngine,
        stats: SessionStats,
        delay_sec: float,
        threshold: float,
        on_screenshot: Callable[[np.ndarray], None],
        on_status: Callable[[str], None],
        on_error: Callable[[str], None],
    ): ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
```

#### `loco_box/session_stats.py`

```python
class SessionStats:
    def reset(self) -> None: ...
    def record(self, name: str) -> None: ...
    def snapshot(self) -> dict[str, int]: ...
    def total(self) -> int: ...
```

### 6.3 UI 层变更（开发时）

`loco_box/ui/app.py` 需调整：

| 变更点 | 说明 |
|--------|------|
| `_start()` | 创建/重置 `SessionStats`；启动 `MonitorCoordinator` 而非 `MonitorThread` |
| `_stop()` | 停止 coordinator；stats 可暂留内存 |
| OCR 引擎初始化 | 懒加载，避免启动时加载模型拖慢 UI |
| 统计展示 | **本阶段不改 UI**，不显示 Counter |
| 配置项 | 暂不新增；OCR 引擎选择可硬编码或环境变量 |

---

## 7. 现有代码引用

实现 v2 时应优先阅读并复用以下文件：

| 文件 | 复用内容 |
|------|----------|
| `loco_box/matcher.py` | `WhiteTextMatcher`、`MatchAnalysis`、`extract_text_strokes`、`_analyze_mask` |
| `loco_box/monitor.py` | 轮询节奏、`CONFIRM_*` 常量、状态流转参考 |
| `loco_box/image_ops.py` | `grab_region`、`bgr_to_gray`、预处理扩展点 |
| `loco_box/types.py` | `Region = dict`，键为 `left/top/width/height` |
| `loco_box/settings.py` | `AppConfig` 持久化；**stats 不加入 AppConfig** |
| `loco_box/ui/app.py` | 启停切换、区域框选、预览显示回调 |

---

## 8. 开发阶段划分

### Phase 0 — 准备（开发前）

- [ ] 用户提供：监控区域内「精灵名」样图（至少 2–3 个不同名字）
- [ ] 用户提供：同一区域内「幸运惊喜盒」样图（确认门禁不会误触发 OCR）
- [ ] 用样图 POC 对比 Windows OCR vs RapidOCR 准确率
- [ ] 标定 `MIN_STROKE_PIXELS` 与 OCR 预处理参数

### Phase 1 — 骨架（无 OCR）

- [ ] 创建 `session_stats.py`
- [ ] 创建 `pipelines/gate.py`、`pipelines/fast.py`
- [ ] 创建 `pipelines/coordinator.py`，状态机跑通 v1 等效行为（无 OCR，门禁始终跳过）
- [ ] `app.py` 切换到 `MonitorCoordinator`
- [ ] 验证：启停、截图、状态栏与 v1 行为一致

### Phase 2 — OCR 接入

- [ ] 实现 `pipelines/ocr.py`（先选一个引擎）
- [ ] coordinator 在 `ANALYZING` 状态调用 gate + ocr + stats.record
- [ ] 精灵名清洗：去空格、去标点、长度上下限
- [ ] 日志或 debug 模式打印 `snapshot()`（不做了 UI）

### Phase 3 — 打磨

- [ ] 误识别处理：与「幸运惊喜盒」相似的 OCR 结果过滤
- [ ] 可选：精灵名黑名单 / 白名单
- [ ] exe 打包体积与 OCR 依赖评估
- [ ] README 更新

### Phase 4 — 统计展示（需求明确后）

- [ ] UI 面板显示 `snapshot()`
- [ ] 导出 / 持久化（若需要）

---

## 9. 测试要点

### 9.1 链路 1 回归

- 盒子出现 → 消失 → 延迟 → 截图，全流程与 v1 一致
- 停止后线程正确退出，无泄漏

### 9.2 门禁

| 输入 | 期望 |
|------|------|
| 幸运惊喜盒画面 | `should_run_ocr == False` |
| 空白监控区 | `should_run_ocr == False` |
| 精灵名画面 | `should_run_ocr == True` |

### 9.3 会话统计

- 开始 → 识别 3 次「迪莫」、1 次「喵呜」→ `snapshot() == {"迪莫": 3, "喵呜": 1}`
- 停止 → 再开始 → `snapshot()` 重置为空

### 9.4 性能

- 轮询循环仅含 `grab_region` + `matcher.analyze`，不含 OCR
- OCR 单次耗时记录到日志，目标 < 200ms（可接受，因仅触发一次）

---

## 10. 未决问题与风险

| 编号 | 问题 | 影响 | 建议 |
|------|------|------|------|
| Q1 | 精灵名样图未提供 | 无法选型 OCR、无法标定参数 | Phase 0 阻塞项 |
| Q2 | 精灵名字数范围未知 | OCR 清洗规则、门禁 char_count 阈值 | 样图确认后定 |
| Q3 | 监控区同时有盒子字和精灵名？ | 门禁逻辑可能需时序判断（先消失盒子再出现精灵名） | 需用户确认游戏 UI 时序 |
| Q4 | OCR 误识别非精灵名 UI 文字 | 统计污染 | 后续加白名单或置信度过滤 |
| Q5 | exe 体积增加 | 用户下载体验 | 优先试 Windows OCR |
| Q6 | 统计数据最终用途 | UI 设计 | 等用户决定后进入 Phase 4 |

### 10.1 关于 Q3 的重要说明

当前设计假设时序为：

```
幸运惊喜盒出现 → 消失 → 截图 → 此时监控区应为精灵名（非盒子字）
```

若游戏 UI 在盒子消失后监控区**立即切换**为精灵名，则门禁在 `ANALYZING` 时刻抓取 `monitor_region` 即可。

若存在**重叠或过渡帧**，可能需要在截图后再等短暂延迟，或对 `monitor_region` 多帧采样取 OCR 结果。需样图与实机验证。

---

## 11. 依赖变更预览（Phase 2 时）

当前 `requirements.txt`：

```
customtkinter>=5.2.2
mss>=9.0.1
numpy>=1.24.0
Pillow>=10.0.0
```

Phase 2 可能新增（择一）：

```
# 方案 A：RapidOCR
rapidocr-onnxruntime>=1.3.0
onnxruntime>=1.16.0

# 方案 B：CnOCR
cnocr[ort]>=2.3.0

# 方案 C：Windows OCR
# 无 pip 依赖，需 winrt / winsdk，仅 Windows
```

---

## 12. AI 开发启动清单

当用户说「开始 v2 开发」时，AI 应：

1. **阅读本文档全文**
2. **阅读** `loco_box/matcher.py`、`loco_box/monitor.py`、`loco_box/ui/app.py`
3. **确认** Phase 0 是否完成（是否有样图）
4. **按 Phase 1 → 2 → 3 顺序实现**，不要跳过 Phase 1 直接接 OCR
5. **不要**实现 Phase 4（统计 UI / 持久化），除非用户另行要求
6. **不要**删除 v1 匹配逻辑；fast 链路必须保留
7. **保持** v1.1 UI 风格与现有代码约定（`Region` 类型、回调风格、`on_status` 简短文案）
8. 每个 Phase 完成后建议用户实机验证再继续

---

## 13. 术语表

| 术语 | 含义 |
|------|------|
| 监控区域 | `monitor_region` / `template_region`，盒子检测 + 精灵名 OCR 共用 |
| 截图区域 | `shot_region` / `region_b`，盒子消失后截取的游戏画面 |
| 快速链路 | 笔画指纹匹配，检测幸运惊喜盒出现/消失 |
| 慢速链路 | OCR 识别精灵名 |
| 门禁 | `should_run_ocr`，决定是否进入慢速链路 |
| 会话 | 用户一次「开始」到「停止」的监控周期 |

---

## 14. 版本历史

| 版本 | 说明 |
|------|------|
| v1.0 | 初始监控：笔画匹配 + 截图 |
| v1.1 | UI 精简：单行工具栏、切换启停、单行状态栏 |
| v2.0（计划） | 双链路：保留快速盒子检测 + 会话级精灵名 OCR 计数 |
