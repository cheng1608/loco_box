# CLAUDE.md — Agent 参考

## 项目概述

洛克王国 S2 幸运惊喜盒自动化监控工具。Windows 桌面应用，通过屏幕监控 → Arduino 硬件桥接 → USB HID 按键实现游戏自动化。

## 核心架构

```
main.py → App (CustomTkinter GUI)
            → MonitorThread (后台轮询线程, 0.3s/次)
              → image_ops.grab_region() (mss截图, BGR格式)
              → WhiteTextMatcher.analyze() (白字笔画指纹匹配)
              → 命中 → on_box_appear 回调
                → after(Ns) 延时
                → SerialBridge.send("1") (串口 → Arduino → HID按键)
```

## 关键设计约束

1. **Arduino 不能保持串口长连接**：ATmega32U4 打开串口 = 硬件复位 = USB HID 断开重连。每次按键前 `connect() → send() → disconnect()`。
2. **游戏屏蔽 Python 模拟输入**：不能用 pyautogui/keyboard/pynput。Arduino 是唯一可行的输入路径。
3. **COM 口会变**：每次插拔 COM 号可能变化，用 `SerialBridge.find_arduino()` 自动检测。
4. **白字检测不是模板匹配**：是笔画指纹拓扑分析，专门针对白底白字的游戏文字设计。

## 模块速查

| 模块 | 文件 | 职责 |
|------|------|------|
| GUI | `loco_box/ui/app.py` | CustomTkinter 主窗口，状态栏，预览 |
| 监控线程 | `loco_box/monitor.py` | 两阶段状态机：等待出现→等待消失 |
| 白字识别 | `loco_box/matcher.py` | `WhiteTextMatcher`：top-hat + 笔画指纹 |
| 图像工具 | `loco_box/image_ops.py` | mss 截图、BGR转换、边缘检测、预览渲染 |
| 串口桥接 | `loco_box/serial_bridge.py` | `SerialBridge`：AUTO 端口检测、文本协议 |
| 区域选择 | `loco_box/region_selector.py` | 全屏半透明框选（独立 tk 线程） |
| 配置 | `loco_box/settings.py` | JSON 配置持久化 + 模板 PNG |
| Arduino | `scripts/arduino_bridge.ino` | HID 键盘+鼠标，文本协议解析 |

## MonitorThread 状态机

```
WAITING: 每 0.3s 检测 strong_present
  → 连续 4 次 → 状态转 WATCHING → 回调 on_box_appear
WATCHING: 每 0.3s 检测 absent 或 !weak_present
  → 连续 3 次 → 等 delay_sec → 截图 shot_region → 状态转 WAITING
```

## 修改代码注意事项

1. **类型注解**：Python 3.9，不能用 `X | None`（用 `Optional[X]`）
2. **线程安全**：MonitorThread 是 daemon 线程，回调需 `self.after(0, callback)` 回主线程
3. **Arduino 复位**：每次 `serial.Serial()` 打开都会让 ATmega32U4 复位，USB HID 需 1-2s 重新初始化
4. **BGR 通道**：所有图像处理用 BGR 顺序（OpenCV 兼容），灰度用 `[0.114, 0.587, 0.299]` 权重
5. **settings.json**：存用户区域和参数，程序启动自动加载。`com_port` 应始终设为 "AUTO"
