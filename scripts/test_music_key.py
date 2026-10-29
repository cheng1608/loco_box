"""音乐按键串口测试：绕过 GUI，直接发送手碟 9 音对应按键。

用途：诊断「自动演奏没出音」到底是 固件 / 串口 / 游戏键位 哪一层的问题。

用法：
  1. 打开一个记事本（Notepad），保持窗口聚焦
  2. 运行: .venv/Scripts/python.exe scripts/test_music_key.py
  3. 观察记事本里出现的字符，按结尾的对照表判断

判读：
  发送 "1"   → 记事本出现 1            （串口链路正常）
  发送 "Y"   → 记事本出现小写 y        （固件小写修复已生效，问题在游戏/应用层）
  发送 "Y"   → 记事本出现大写 Y        （固件仍是旧版，字母被加了 Shift）
  字母完全不出现                        （Arduino 固件 / 硬件问题）
"""

import sys
import time
import os
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[FATAL] pyserial 未安装。运行: pip install pyserial")
    sys.exit(1)

# 9 音 → 按键（与 backend/features/music.py 的 NOTE_TO_KEY 一致）
NOTE_TO_KEY = {
    "L6": "B",
    "M3": "F", "M4": "G", "M5": "H", "M6": "J", "M7": "K",
    "H1": "T", "H2": "Y", "H3": "U",
}

# 摇篮曲（与 data/scores/摇篮曲.txt 一致），用于在游戏里实测整曲
LULLABY = [
    ("H2", "Y", 500), ("H1", "T", 500), ("M7", "K", 500),
    ("M6", "J", 500), ("M5", "H", 500), ("M4", "G", 500),
    ("M3", "F", 800), ("M5", "H", 500), ("M6", "J", 500),
    ("M7", "K", 500), ("H1", "T", 500), ("H2", "Y", 800),
    ("H1", "T", 1200),
]

HOLD_MS = 100


def find_arduino():
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").lower()
        if "arduino" in desc or "micro" in desc:
            return p.device, p.description
    return None, None


def free_port_from_app():
    """若应用正在使用串口，先通过后端 API 断开，否则打不开 COM 口。"""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8790/api/arduino/disconnect", method="POST"
        )
        urllib.request.urlopen(req, timeout=2)
        print("已通过后端 API 断开应用占用的串口。")
        time.sleep(0.5)
    except Exception:
        pass  # 后端没起 / 本来就没占用，忽略


def main():
    print("=" * 60)
    print("音乐按键串口测试")
    print("=" * 60)

    # 1. 列出串口
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("[FATAL] 无串口设备，请确认 Arduino 已插入")
        sys.exit(1)
    for p in ports:
        print(f"  {p.device}  |  {p.description}")

    # 2. 找 Arduino
    com, desc = find_arduino()
    if not com:
        print("\n未自动找到 Arduino，请手动输入 COM 口名（如 COM8）：")
        com = input("> ").strip()
    print(f"\n使用端口: {com}  ({desc or ''})")

    # 3. 打开串口（先让应用释放端口）
    free_port_from_app()
    try:
        ser = serial.Serial(com, 9600, timeout=1)
    except Exception as e:
        print(f"[FAIL] 打开串口失败: {e}")
        print("       → 应用可能仍占用端口，请在应用里点「断开 Arduino」后重试")
        sys.exit(1)

    # 4. 等复位 + HID 就绪
    print("\n等待 Arduino 复位 + USB HID 枚举 (5s) ...")
    print(">>> 请立即切换到【记事本】窗口并保持聚焦！ <<<")
    for i in range(5, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    # 5. 基线：数字 1
    print("\n[1/3] 基线数字 '1'（确认串口链路正常）")
    ser.write(b"1:100\n")
    ser.flush()
    time.sleep(1.5)

    # 6. 逐个发送 9 音按键（大写，与后端一致）
    print("\n[2/3] 逐个发送 9 音按键（大写，与后端一致）")
    print("  期望记事本出现【小写】字母；出现大写说明固件带 Shift")
    for note, key in NOTE_TO_KEY.items():
        ser.write(f"{key}:{HOLD_MS}\n".encode())
        ser.flush()
        print(f"  发送 {note} → {key}")
        time.sleep(1.2)

    # 7. 整曲（摇篮曲），供切到游戏里实测
    print("\n[3/3] 整曲测试：摇篮曲（13 音，带真实停顿）")
    print(">>> 若要在游戏里试，请现在切回游戏窗口！ <<<")
    time.sleep(3)
    for note, key, pause in LULLABY:
        ser.write(f"{key}:{HOLD_MS}\n".encode())
        ser.flush()
        print(f"  {note} → {key}  停 {pause}ms")
        time.sleep(pause / 1000.0)

    ser.close()
    print("\n" + "=" * 60)
    print("完成。对照记事本 / 游戏里的表现：")
    print("  数字 '1' 出现           → 串口链路 OK")
    print("  大写键 → 小写字母       → 固件修复生效，问题在游戏/应用层")
    print("  大写键 → 大写字母       → 固件仍是旧版（带 Shift），需重新烧录")
    print("  字母完全没出现          → Arduino 固件 / 硬件问题")
    print("=" * 60)


if __name__ == "__main__":
    main()
