"""极简裸测：串口 → Arduino → 按键 "1"。

完全不依赖项目代码，只用 pyserial 标准库。
用法：python scripts/test_raw.py
"""

import time
import sys

# ── 1. 检查 pyserial ──────────────────────────
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[FATAL] pyserial 未安装。运行: pip install pyserial")
    sys.exit(1)

print("pyserial 版本:", serial.__version__)

# ── 2. 列出所有串口 ────────────────────────────
print("\n=== 所有串口 ===")
ports = list(serial.tools.list_ports.comports())
if not ports:
    print("(无任何串口设备！请确认 Arduino 已插入)")
    sys.exit(1)

for i, p in enumerate(ports):
    print(f"  [{i}] {p.device}  |  {p.description}  |  HWID: {p.hwid[:60]}")

# ── 3. 匹配 Arduino ────────────────────────────
arduino_port = None
for p in ports:
    desc = (p.description or "").lower()
    hwid = (p.hwid or "").lower()
    if "arduino" in desc or "micro" in desc:
        arduino_port = p.device
        print(f"\n自动匹配 Arduino → {p.device} ({p.description})")
        break

if not arduino_port:
    print("\n未自动匹配到 Arduino，请手动输入编号:")
    choice = input("> ").strip()
    try:
        arduino_port = ports[int(choice)].device
    except (ValueError, IndexError):
        print("无效选择，退出。")
        sys.exit(1)

print(f"使用端口: {arduino_port}")

# ── 4. 打开串口 ────────────────────────────────
print(f"\n正在打开 {arduino_port} ...")
try:
    ser = serial.Serial(arduino_port, 9600, timeout=1)
    print(f"打开成功！dtr={ser.dtr}")
except Exception as e:
    print(f"[FAIL] 无法打开串口: {e}")
    sys.exit(1)

# ── 5. 等待 Arduino 复位 + HID 就绪 ─────────────
print("等待 Arduino 复位 + USB HID 枚举 (5s) ...")
for i in range(5, 0, -1):
    print(f"  {i}...")
    time.sleep(1)

# ── 6. 发送 "1" ────────────────────────────────
print("\n>>> 发送 '1' <<<")
print("(请确保某个可输入文字的窗口已聚焦！)")
time.sleep(1)

cmd = "1\n"
bytes_written = ser.write(cmd.encode())
ser.flush()
print(f"写入 {bytes_written} 字节: {cmd.strip()!r}")

time.sleep(0.5)

# ── 7. 收尾 ────────────────────────────────────
ser.close()
print("串口已关闭。")
print("\n如果聚焦窗口未出现 '1'，可能原因:")
print("  A) Arduino 未烧录 bridge 固件")
print("  B) USB HID 枚举时间 > 5s，需更久等待")
print("  C) COM 口选错了（试试其他口）")
print("  D) Arduino 硬件问题")
