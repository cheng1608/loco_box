# Arduino 串口与和弦协议 v2

固件入口是 `scripts/arduino_bridge/arduino_bridge.ino`，状态机在同目录 `BridgeState.h`。目标为 ATmega32U4 的 Arduino Micro / Leonardo 兼容板。

## 连接与能力

使用 USB CDC、9600 baud、8N1，无流控。ATmega32U4 使用原生 USB，不应把配置的 baud 值当成传统 UART 吞吐上限。Arduino 官方说明见 [Serial.begin](https://docs.arduino.cc/language-reference/en/functions/communication/serial/begin/)。

Python 通过唯一的 `ArduinoController` 持久连接，首次打开后等待板卡和 USB 稳定，再探测能力；后续按键和切歌不重新打开串口。打开原生 USB CDC 并不必然使所有 ATmega32U4 板卡复位。老固件探测超时后按 protocol 1 处理，MIDI 与 TXT 均使用单键演奏，和弦顺序敲出。

每帧为 ASCII 行，以 LF 或 CR 结束；最大命令内容 95 字节。超长帧被整帧丢弃，不允许截断后误执行。v2 命令使用大写，session 区分大小写，允许 `[A-Za-z0-9_-]`，长度 1～32。

| 请求 | 成功应答 / 作用 |
|---|---|
| `HELLO 2` | `CAPS 2 <max_keys> 1500 2.0.0`，max_keys 为 9 或 6 |
| `BEGIN <session>` | `OK BEGIN <session>`，全释放并建立新会话；同会话重试幂等 |
| `STATE <session> <seq> <mask>` | 设置完整键集合，一次键盘 HID 报告；成功无逐帧 ACK |
| `PING <session>` | `OK PING <session> <lastseq>`，续期 watchdog |
| `STOP <session>` | `OK STOP <session>`，全释放并废弃会话 |
| `PANIC` | `OK PANIC`，无条件释放键盘和鼠标、废弃会话 |

seq 为十进制 uint32，mask 为十进制 0～511。序号递增，同序号同 mask 可重试；旧序号或同序号不同 mask 拒绝。会话失效后旧 STATE 不会恢复按键。后端约每 350ms PING，固件 1500ms 无有效会话活动则全释放。

mask 的 bit 0～8 固定为 `B F G H J K T Y U`，例如 B+F+G 是 7，九键全按是 511，全释放是 0。它表示完整当前状态，不是增量按键列表。

错误应答为 `ERR <code>`：`SESSION`、`SEQUENCE`、`CAPACITY`、`BUSY`、`ARGUMENT`、`DURATION`、`COMMAND`、`FRAME_TOO_LONG`。STATE 没有成功 ACK，下一次写入/心跳会收集错误。STOP 应答失败时主机尝试 PANIC；释放仍失败则关闭连接，固件 watchdog 最终清理会话。

## 和弦 HID 报告

默认自定义键盘 bitmap descriptor，一次 `HID().SendReport` 提交完整键集合。键盘修饰位与 usage 0～119 独立表示，可同时触发全部九音。鼠标保留独立 report ID。

`LOCOBOX_6KRO=1` 改为标准六键数组报告，用于需兼容六键报告的环境；后端依据能力在播放前检查容量。不能将 Arduino 标准 Keyboard 库的六键缓存与自定义报告混用。原库接口和报告结构可查 [Arduino Keyboard](https://github.com/arduino-libraries/Keyboard/blob/master/src/Keyboard.h)。

编译成功不等于游戏实机兼容已经验证。九键模式需要在实际 Windows/游戏环境验证同时触发；如游戏不识别，可编译六键模式，软件会明确报告超容量音符。

## 旧版命令兼容

支持 `<KEY>[:<hold_ms>]`，时长 0～60000ms。字母 A～Z / a～z 都发送不带 Shift 的原始字母键。命名键包括数字、ESC、TAB、SPACE、ENTER、LCTRL、RCTRL、LSHIFT、RSHIFT、方向键和 F1～F12；鼠标为 MOUSE_LEFT / MOUSE_RIGHT。

例如 `F:50`、`1:50`、`MOUSE_LEFT:200`。不带时长最短 1ms，仅供通用命令兼容；游戏按键应至少 50ms。v2 不使用阻塞 delay 保持按键，而是按每个键的截止时间释放，因此串口 STOP/PANIC 可以及时处理。音乐会话期间拒绝旧式键鼠命令。

旧固件仍采用原有阻塞单键逻辑，不能做到和弦或立即全释放。应用停止旧 TXT 后已发送短按按原定时结束。

## 后端使用

所有功能必须先 `ctx.arduino.acquire(feature_id)`，连接和发送时带 `owner=feature_id`，在 finally 中 `release(feature_id)`。同一时刻只有一个功能拥有设备，暂停演奏仍保留所有权。manual 仅能向空闲设备发键。停止后迟到的命名 worker 写入和重新连接都会被拒绝；查询已有连接不会重新打开串口。

演奏使用 `begin_music(session)`、`send_state(session, seq, mask)`、`heartbeat(session)`、`end_music(session)`。release 在同一串口锁内全释放再清 owner，防止交错；状态/能力读取使用缓存，不等待握手 I/O。

手动断开会先停止所有 Feature，再关闭连接。应用 shutdown 同样先停止功能，最终 `disconnect(force=True)`。

## 编译与烧录

在 Arduino IDE 中使用「文件 → 打开」，选择仓库里的 `scripts/arduino_bridge/arduino_bridge.ino`，直接打开现成工程，无需复制代码。安装 Arduino AVR Boards 和 Mouse 库，按实际板选择 Micro 或 Leonardo。

工程的两个文件必须同时存在，且内容不同：

```text
arduino_bridge/
├── arduino_bridge.ino   主程序，包含 setup()、loop() 和串口处理
└── BridgeState.h        状态机类，以 #ifndef LOCOBOX_BRIDGE_STATE_H 开头
```

IDE 中 `BridgeState.h` 会作为另一个标签页显示。不要把 `.ino` 主程序再次粘贴到 `.h` 标签中：主程序包含 `#include "BridgeState.h"`，复制进去会使头文件递归包含自己，出现大量 `#include nested too deeply` 错误。仅加 `#pragma once` 或删除该 include 不能恢复丢失的状态机类，需要恢复完整正确的 `BridgeState.h`。

如果文件刚被外部工具修复，关闭当前工程，遇到保存旧编辑内容的询问选择不保存，再重新打开 `.ino`，让 IDE 读取磁盘上的两个文件。先点击「验证」编译，通过后再上传。固件验证命令只编译，不自动刷写。

可复现命令（已安装 Arduino CLI）：

```powershell
arduino-cli core update-index
arduino-cli core install arduino:avr@1.8.8
arduino-cli lib install Mouse@1.0.1
arduino-cli compile --fqbn arduino:avr:micro scripts/arduino_bridge
arduino-cli compile --fqbn arduino:avr:leonardo scripts/arduino_bridge

# 六键兼容模式
arduino-cli compile --fqbn arduino:avr:micro --build-property compiler.cpp.extra_flags=-DLOCOBOX_6KRO=1 scripts/arduino_bridge
```

CI 编译 Micro / Leonardo 的两种模式，并执行可在桌面运行的固件状态机测试。后端串口测试使用内存中的假设备，不会打开真实 COM 口。
