# 架构文档

## 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                     main.py                             │
│                   (程序入口)                              │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                 ui/app.py (GUI 层)                       │
│   CustomTkinter 窗口：按钮、参数、状态栏、预览区          │
│   ┌─────────────────────────────────────────────────┐  │
│   │  监控区域 │ 截图区域 │ 预览 │ 测试 │ 开始/停止  │  │
│   │  延迟 阈值 亮度 按键 COM                         │  │
│   └─────────────────────────────────────────────────┘  │
└──────┬──────────────────────┬───────────────────────────┘
       │                      │
       │  MonitorThread       │  SerialBridge
       │  (后台监控线程)        │  (串口通信)
       │                      │
┌──────▼──────────┐    ┌──────▼──────────────────────────┐
│  monitor.py     │    │  serial_bridge.py               │
│  状态机循环      │    │  AUTO 端口检测                   │
│  0.3s 轮询      │    │  文本协议: "KEY\n"              │
│  确认计数器      │    │  connect → send → disconnect    │
└──────┬──────────┘    └──────┬──────────────────────────┘
       │                      │
┌──────▼──────────┐    ┌──────▼──────────────────────────┐
│  matcher.py     │    │  Arduino (ATmega32U4)           │
│  WhiteTextMatcher│   │  USB HID 键盘/鼠标               │
│  笔画指纹分析    │    │  协议解析 → Keyboard.write()     │
└──────┬──────────┘    └─────────────────────────────────┘
       │
┌──────▼──────────┐
│  image_ops.py   │
│  mss 截图       │
│  BGR 转换       │
│  边缘检测        │
│  预览渲染        │
└─────────────────┘
```

## 数据流

```
屏幕区域 → mss.grab() → BGR numpy array
    → bgr_to_gray() → 灰度图
    → gaussian_blur() → top-hat 变换
    → 阈值二值化 → 笔画掩码
    → 指纹对比 (覆盖度/IoU/布局/字符数)
    → MatchAnalysis (absent/strong/weak/score)
    → MonitorThread 状态机决策
    → on_box_appear → after(delay) → SerialBridge.send("1")
    → Arduino → Keyboard.press/release → 游戏
```

## 线程模型

| 线程 | 创建者 | 生命周期 |
|------|--------|----------|
| 主线程 | `main.py` | tkinter mainloop，程序生命周期 |
| MonitorThread | `App._start()` | daemon，随"停止"按钮销毁 |
| RegionSelector 线程 | `select_region()` | daemon，框选完毕自毁 |

**线程安全规则**：MonitorThread 回调必须通过 `self.after(0, cb)` 回到主线程才能操作 GUI。

## 关键常量

| 常量 | 值 | 位置 |
|------|-----|------|
| POLL_INTERVAL | 0.3s | monitor.py |
| CONFIRM_APPEAR | 4 次 | monitor.py |
| CONFIRM_ABSENT | 3 次 | monitor.py |
| 默认阈值 | 0.45 | settings.py |
| 默认亮度 | 200 | settings.py |
| 默认按键延迟 | 5.0s | settings.py |
| 串口波特率 | 9600 | serial_bridge.py |
| 窗口尺寸 | 324×666 px | ui/theme.py |
| 预览区域 | 300×520 px | ui/theme.py |

## 白字检测算法

专门针对「白字 + 白底」场景设计，传统模板匹配在此场景下失效。

**步骤**：
1. **白场检测**：判断整个区域是否为纯白（bright_ratio > 0.88）
2. **Top-Hat 变换**：`gray - GaussianBlur(gray)` → 提取细白笔画
3. **阈值二值化**：`tophat > 25 AND gray >= brightness`
4. **笔画掩码分析**：垂直投影 → 峰值检测 → 字符分割
5. **多因子评分**（加权）：
   - 覆盖度 (35%)：模板笔画与帧笔画的重叠比例
   - IoU (20%)：交并比
   - 波段覆盖 (20%)：5 个垂直波段的均匀性
   - 布局相似度 (15%)：字符间距和垂直位置
   - 字符数相似度 (10%)
6. **硬拒条件**：覆盖度 < 0.12 或 min_band < 0.10 或 layout < 0.20
7. **强匹配条件**：score ≥ threshold + 0.08 且多条件同时满足

## Arduino 复位问题

ATmega32U4 芯片特性：USB 串口打开时会触发硬件复位（DTR 脉冲 → RST 电容耦合）。

**影响**：
- 复位 → USB 断开重连 → HID 重新枚举 → 游戏可能丢失键盘识别
- 启动时间 ~1.5s（bootloader + 固件初始化 + USB 枚举）

**解决方案**：不在程序启动时连接串口，只在需要发送按键时 `connect → send → disconnect`。这样 USB HID 保持稳定，只在按键瞬间短暂波动。
