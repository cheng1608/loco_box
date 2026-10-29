# Arduino 串口协议

## 物理层

- **接口**：USB CDC Serial (COM 口)
- **波特率**：9600 bps
- **数据位**：8
- **停止位**：1
- **校验**：无
- **流控**：无

## 数据链路层

**帧格式**：`<命令>\n`

- 每条命令以换行符 `\n` 结尾
- 命令不区分大小写（固件内部转大写处理）
- 同一时刻只处理一条命令

## 命令参考

### 键盘按键

| 命令 | 键码 | 说明 |
|------|------|------|
| `0` ~ `9` | `0` ~ `9` | 数字键 |
| `A` ~ `Z` | a ~ z | **大小写语义见下方注意** |
| `a` ~ `z` | a ~ z | 原始字母键 |
| `ESC` | `KEY_ESC` | Escape |
| `TAB` | `KEY_TAB` | Tab |
| `SPACE` | ` ` | 空格 |
| `ENTER` | `KEY_RETURN` | 回车 |
| `LCTRL` | `KEY_LEFT_CTRL` | 左 Ctrl |
| `LSHIFT` | `KEY_LEFT_SHIFT` | 左 Shift |
| `LEFT` | `KEY_LEFT_ARROW` | 方向左 |
| `RIGHT` | `KEY_RIGHT_ARROW` | 方向右 |
| `UP` | `KEY_UP_ARROW` | 方向上 |
| `DOWN` | `KEY_DOWN_ARROW` | 方向下 |
| `F1` ~ `F12` | `KEY_F1` ~ `KEY_F12` | 功能键 |

### 长按

| 格式 | 示例 | 说明 |
|------|------|------|
| `<键>:<毫秒>` | `1:500` | 按住 1 键 500ms 后松开 |
| `<键>:<毫秒>` | `LCTRL:2000` | 按住左 Ctrl 2 秒后松开 |

### 鼠标

| 命令 | 说明 |
|------|------|
| `MOUSE_LEFT` | 鼠标左键点击 |
| `MOUSE_RIGHT` | 鼠标右键点击 |

鼠标同样支持长按：`MOUSE_LEFT:200` = 按住左键 200ms 后松开（`Mouse.press → delay → Mouse.release`）。不带时长则 `Mouse.click()` 瞬时点击。

### 字母大小写语义（重要）

HID 键盘协议里**大写字母 = SHIFT + 对应键**。固件 `keyToCode()` 刻意把单个大写字母 `A`~`Z` **转成小写**后再 `Keyboard.press`，即发送 `"A"` 与 `"a"` 都会敲出小写 `a`、且**不会带 Shift**。这是为了绕过「HID 大写 = 组合键」的坑，确保自动演奏敲出的都是干净的单键。

含义：
- 想敲小写字母 → 直接发 `A`~`Z` 或 `a`~`z` 都行（自动演奏即如此：发的是大写 `F/G/H/...`）。
- 固件**无法**产生大写字母（无对应命名键）。如需大写，需给固件加 `Shift` 组合或特殊处理。
- 多字符命令（`ESC`、`F1`、`MOUSE_LEFT` 等）内部仍先 `toUpperCase()` 再匹配，不受此影响。

## Python 调用示例

```python
from loco_box.serial_bridge import SerialBridge

bridge = SerialBridge("AUTO")  # AUTO = 自动检测 COM 口
bridge.connect()
bridge.send("1")               # 点击数字 1
bridge.send("1", 500)          # 按住 1 半秒
bridge.send("ESC")             # 按 ESC
bridge.send("MOUSE_LEFT")      # 鼠标左键点击
bridge.send("LCTRL:3000")      # 按住左 Ctrl 3 秒
bridge.disconnect()
```

> 实际程序不走「每次 connect/disconnect」：启动/首次运行时 `connect()` 一次并等 ~3s 复位完成，之后**保持连接**、按键瞬间发送（见 `docs/ARCHITECTURE.md` 串口策略）。上面的 connect/disconnect 仅为演示协议用法。
>
> 当前架构里 `SerialBridge` 被 `backend/core/arduino.py` 的 `ArduinoController` 单例封装（`ctx.arduino`），所有 Feature 共享同一个持久连接，**不应**再各自直接 new `SerialBridge`。

## Arduino 固件逻辑

固件源码：`scripts/arduino_bridge/arduino_bridge.ino`（Arduino IDE 上传，板型选 Arduino Leonardo / Micro）。

```
loop():
  读串口字节
    → 遇到 \n 或 \r → 解析 cmdbuffer → execute()
    → 其他字符 → 追加到 cmdBuffer

execute(raw):
  解析 "键:时长" 格式
  → 查找键码
  → 时长 > 0 → press → delay → release (长按)
  → 时长 = 0 → write (点击)
  → 鼠标命令 → 时长>0 则 press→delay→release，否则 Mouse.click()
```

> **游戏帧问题**：`Keyboard.write()` 瞬时按下/松开太快，多数游戏检测不到。因此**长按必须用 `键:毫秒`** 形式（按住 ≥50ms 再松开）。`music.py` 的 `HOLD_MS = 50` 是已验证的最小有效值；丢球/惊喜盒子同样带 hold。

## 故障排查

| 现象 | 可能原因 | 解决方案 |
|------|----------|----------|
| `find_arduino()` 返回 None | Arduino 未插或驱动未装 | 检查 USB 连接 |
| `connect()` 返回 False | 串口被占用（如 Arduino IDE） | 关闭 IDE 串口监视器 |
| 发送成功但游戏无反应 | Arduino 复位后 HID 未就绪 | 连接后等 3s 再发送 |
| COM 口号码变化 | Windows 重新分配 | 使用 `AUTO` 模式自动检测 |
