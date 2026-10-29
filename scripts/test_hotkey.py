"""独立测试：RegisterHotKey + F8。按 F8 打印，ESC 退出。"""
import ctypes
import threading
import sys
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_HOTKEY = 0x0312
HWND_MESSAGE = wintypes.HWND(-3)

# 创建 message-only 窗口
hwnd = user32.CreateWindowExW(
    0, wintypes.LPCWSTR("STATIC"), wintypes.LPCWSTR("HotkeyTest"),
    0, 0, 0, 0, 0,
    HWND_MESSAGE, None, kernel32.GetModuleHandleW(None), None
)
print(f"Window: {hwnd}")

# 注册 F8 (VK_F8 = 0x77)
result = user32.RegisterHotKey(hwnd, 1, 0x4000, 0x77)
print(f"RegisterHotKey(F8): {'OK' if result else 'FAILED (err=' + str(ctypes.get_last_error()) + ')'}")

# 注册 ESC (VK_ESCAPE = 0x1B)
result = user32.RegisterHotKey(hwnd, 2, 0x4000, 0x1B)
print(f"RegisterHotKey(ESC): {'OK' if result else 'FAILED'}")

if not result:
    print("Hotkey registration failed. Try running as Administrator.")
    sys.exit(1)

print("\nPress F8 to test, ESC to exit...\n")

count = 0
msg = wintypes.MSG()
pm = ctypes.POINTER(wintypes.MSG)(msg)

while True:
    if user32.PeekMessageW(pm, hwnd, WM_HOTKEY, WM_HOTKEY, 1):
        hid = msg.wParam
        if hid == 1:  # F8
            count += 1
            print(f"F8 pressed! (count={count})")
        elif hid == 2:  # ESC
            print("ESC pressed, exiting.")
            break
    else:
        kernel32.Sleep(50)

user32.UnregisterHotKey(hwnd, 1)
user32.UnregisterHotKey(hwnd, 2)
print("Done.")
