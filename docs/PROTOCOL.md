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
| `A` ~ `Z` | `A` ~ `Z` | 字母键 |
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

## Arduino 固件逻辑

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
  → 鼠标命令 → Mouse.click()
```

## 故障排查

| 现象 | 可能原因 | 解决方案 |
|------|----------|----------|
| `find_arduino()` 返回 None | Arduino 未插或驱动未装 | 检查 USB 连接 |
| `connect()` 返回 False | 串口被占用（如 Arduino IDE） | 关闭 IDE 串口监视器 |
| 发送成功但游戏无反应 | Arduino 复位后 HID 未就绪 | 连接后等 1.5s 再发送 |
| COM 口号码变化 | Windows 重新分配 | 使用 `AUTO` 模式自动检测 |
