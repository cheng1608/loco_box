"""独立测试：Arduino 按键通信。

绕过 GUI，直接测试 connect → send → disconnect 是否能让 Arduino 发送按键。
用法：在任意文本框聚焦后运行此脚本，观察是否出现 "1" 字符。
"""

import sys
import time
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loco_box.serial_bridge import SerialBridge


def main():
    # 1. 列出所有串口
    print("=" * 50)
    print("1. 可用串口列表:")
    ports = SerialBridge.list_ports()
    if ports:
        for p in ports:
            print(f"   {p}")
    else:
        print("   (无串口或 pyserial 未安装)")

    # 2. 自动查找 Arduino
    print("\n2. 自动查找 Arduino:")
    com = SerialBridge.find_arduino()
    print(f"   结果: {com}")

    if not com:
        print("\n[失败] 未找到 Arduino。请检查：")
        print("   - Arduino 是否已插入 USB")
        print("   - 设备管理器中是否有 COM 口")
        print("   - 描述中是否包含 'Arduino' 或 'Micro'")
        return

    # 3. 测试连接 + 发送按键
    print(f"\n3. 测试连接 {com} + 发送按键 '1' ...")
    print("   (请立即点击某个文本框使窗口聚焦!)")
    for i in range(3, 0, -1):
        print(f"   {i}...")
        time.sleep(1)

    bridge = SerialBridge(com)
    print(f"   正在连接 {com}...")
    if not bridge.connect():
        print(f"   [失败] 无法连接 {com}")
        return

    print("   已连接，等待 HID 就绪...")
    # connect() 内部已等待 2s，这里再额外等 1s 保险
    time.sleep(1.0)

    print("   发送 '1' ...")
    result = bridge.press_key("1")
    print(f"   send 返回: {result}")

    time.sleep(0.5)
    bridge.disconnect()
    print("   已断开。")

    print("\n如果聚焦的窗口没有出现字符 '1'，则说明：")
    print("   A) Arduino 未正确接收串口数据")
    print("   B) Arduino 的 Keyboard HID 未正确初始化")
    print("   C) 等待时间不够（可尝试调大）")
    print("\n如果出现了 '1'，问题在 GUI 层逻辑。")


if __name__ == "__main__":
    main()
