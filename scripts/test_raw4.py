"""极简裸测 v4：5s 准备 → 依次发送 4 种按键（间隔 4s） → 关闭。

用法：python scripts/test_raw4.py
运行后立即切回游戏窗口！观察游戏里第几次出现 '1'。
"""

import time
import sys

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[FATAL] pyserial 未安装")
    sys.exit(1)

# ── 找 Arduino ────────────────────────────
ports = list(serial.tools.list_ports.comports())
arduino_port = None
for p in ports:
    desc = (p.description or "").lower()
    if "arduino" in desc or "micro" in desc:
        arduino_port = p.device
        print(f"Arduino → {p.device} ({p.description})")
        break

if not arduino_port:
    print("未找到 Arduino，手动输入 COM 口名 (如 COM8):")
    arduino_port = input("> ").strip()

# ── 打开串口 + 5s 准备 ──────────────────────
print(f"\n打开 {arduino_port}，5s 后开始发送...")
print(">>> 现在切回游戏窗口！ <<<")
ser = serial.Serial(arduino_port, 9600, timeout=1)

for i in range(5, 0, -1):
    print(f"  {i}...")
    time.sleep(1)

# ── 依次发送 4 种方式，间隔 4s ──────────────
tests = [
    (b"1\n",     "① Keyboard.write('1') — 瞬间按下松开"),
    (b"1:50\n",  "② press('1')→50ms→release"),
    (b"1:100\n", "③ press('1')→100ms→release"),
    (b"1:200\n", "④ press('1')→200ms→release"),
]

for cmd, label in tests:
    print(f"\n>>> {label}")
    ser.write(cmd)
    ser.flush()
    time.sleep(4.0)

ser.close()
print("\n==========")
print("完成。游戏里第几次出现了 '1'？")
