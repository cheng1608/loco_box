"""幸运惊喜盒监控工具入口。"""

import customtkinter as ctk

from loco_box.ui.app import App


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
