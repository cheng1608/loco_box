"""Arduino 串口/按键诊断：一次连接，依次测试按键与按住时长。

仅列出串口：.venv/Scripts/python.exe scripts/diagnose_arduino.py --list
测试数字 1：.venv/Scripts/python.exe scripts/diagnose_arduino.py
测试九音键：.venv/Scripts/python.exe scripts/diagnose_arduino.py --music
比较时长：  .venv/Scripts/python.exe scripts/diagnose_arduino.py --keys 1 Y --hold-ms 50 100 200
"""

import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loco_box.handpan import ALL_NOTES
from loco_box.serial_bridge import SerialBridge


def _key(value: str) -> str:
    if len(value) != 1 or not value.isascii() or not value.isalnum():
        raise argparse.ArgumentTypeError("请使用单个英文字母或数字，例如 1、Y")
    return value.upper()


def _hold_ms(value: str) -> int:
    duration = int(value)
    if not 50 <= duration <= 60000:
        raise argparse.ArgumentTypeError("按住时长必须在 50–60000 毫秒之间")
    return duration


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="只列出串口，不连接、不发送按键")
    parser.add_argument("--port", default="AUTO", help="串口名，例如 COM6；默认 AUTO 自动检测")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--keys", nargs="+", type=_key, default=["1"], help="依次发送的字母/数字，默认 1")
    group.add_argument("--music", action="store_true", help="依次测试手碟九键 B F G H J K T Y U")
    parser.add_argument("--hold-ms", nargs="+", type=_hold_ms, default=[50], help="一个或多个按住时长，默认 50 毫秒")
    args = parser.parse_args(argv)

    if args.list:
        print("\n".join(SerialBridge.list_ports()) or "未找到串口，请检查设备连接和 pyserial 依赖。")
        return 0

    port = SerialBridge.find_arduino() if args.port.upper() == "AUTO" else args.port
    if not port:
        print("未自动找到 Arduino。用 --list 查看端口，再用 --port COM端口号 指定。", file=sys.stderr)
        return 1

    keys = [key for key, _ in ALL_NOTES] if args.music else args.keys
    print("请先停止应用中的自动化功能，并手动断开 Arduino 或关闭应用。")
    print("本工具直接连接串口；将向当前聚焦窗口发送按键。")
    print("端口：%s；按键：%s；按住时长：%s ms" % (port, " ".join(keys), args.hold_ms))
    bridge = SerialBridge(port)
    try:
        print("正在连接并等待设备就绪…")
        if not bridge.connect_and_wait():
            print("连接失败：%s。若端口被占用，请在应用中手动断开后重试。" % bridge.last_error, file=sys.stderr)
            return 1
        caps = bridge.capabilities()
        print("固件协议：%s；同时按键容量：%s" % (caps["protocol"], caps["max_keys"]))
        print("请切到记事本或游戏窗口，5 秒后开始；Ctrl+C 可停止。")
        for remaining in range(5, 0, -1):
            print("%s…" % remaining, flush=True)
            time.sleep(1)
        for duration in args.hold_ms:
            for key in keys:
                if not bridge.press_key(key, duration):
                    print("发送失败：%s" % bridge.last_error, file=sys.stderr)
                    return 1
                print("发送 %s，按住 %s ms" % (key, duration), flush=True)
                # Wait through release before the next key or connection close.
                time.sleep(duration / 1000.0 + 1)
        print("完成。字母应显示为小写；若显示大写，请检查固件。")
        return 0
    except KeyboardInterrupt:
        print("\n已停止诊断。")
        return 130
    finally:
        try:
            if bridge.is_connected():
                bridge.panic()
        finally:
            bridge.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
