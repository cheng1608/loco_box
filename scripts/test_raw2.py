"""极简裸测 v2：测试不同按键时长。

用法：python scripts/test_raw2.py
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

# ── 测试不同按键时长 ────────────────────────
durations = [0, 50, 100, 200]  # ms
print("\n将依次测试不同按键时长。请聚焦一个文本框！\n")

for dur in durations:
    if dur == 0:
        cmd = b"1\n"          # Keyboard.write (瞬间)
        label = "write (0ms)"
    else:
        cmd = f"1:{dur}\n".encode()  # press → delay(dur) → release
        label = f"press+{dur}ms+release"

    print(f"测试 [{label}] ...")
    time.sleep(1)

    ser = serial.Serial(arduino_port, 9600, timeout=1)
    time.sleep(5.0)  # 等 Arduino 复位
    ser.write(cmd)
    ser.flush()
    ser.close()

    print(f"  已发送。看看文本框出现了 '1' 吗？")
    input("  按 Enter 继续下一个测试...")

print("\n完成。请告诉我哪些时长生效了。")
