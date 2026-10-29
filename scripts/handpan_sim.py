"""洛克王国 9 音手碟模拟器（游戏手碟上线前的测试工具）。

聚焦本窗口后，按对应字母键即发出对应音效；也用于接收 Arduino 自动演奏
发送的按键（HID 敲到焦点窗口），验证 midi2score 生成的谱面是否正确。

键位（与 backend/features/music.py 的 NOTE_TO_KEY 一致，大小写不敏感）：
    低音6 -> B；中音3/4/5/6/7 -> F/G/H/J/K；高音1/2/3 -> T/Y/U。

用法：
    .venv/Scripts/python.exe scripts/handpan_sim.py

依赖：numpy（已装）、pygame（多声道并发播放，让尾音自然交叠）。
"""

import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")  # 隐藏 pygame 启动横幅

import tkinter as tk

import numpy as np
import pygame

# ── 音符 ↔ 键盘 映射（与 music.py 的 NOTE_TO_KEY 一致）──────────
NOTE_TO_KEY = {
    "L6": "B",
    "M3": "F", "M4": "G", "M5": "H", "M6": "J", "M7": "K",
    "H1": "T", "H2": "Y", "H3": "U",
}
# 键盘小写字母 -> 音名（Arduino 敲出的是小写、不带 Shift）
KEY_TO_NOTE = {k.lower(): n for n, k in NOTE_TO_KEY.items()}

# ── 音名 -> 频率（Hz，十二平均律，中音1 = C4）──────────────────
NOTE_FREQ = {
    "L6": 220.00,
    "M3": 329.63, "M4": 349.23, "M5": 392.00, "M6": 440.00, "M7": 493.88,
    "H1": 523.25, "H2": 587.33, "H3": 659.25,
}

SR = 44100          # 采样率
DURATION = 1.5      # 单音总长（秒），让尾音充分自然衰减
DECAY_TAU = 0.45    # 指数衰减时间常数（越大尾音越长、越绵）

# 同时可发声的最大音数（手碟音尾约 1.5s，密集弹奏时会叠多个）
MAX_CHANNELS = 32


# ── 音色合成（手碟「叮」：柔和起音 + 长指数衰减 + 谐波分音 + 轻敲击）──
def synth_note(freq: float) -> np.ndarray:
    n = int(SR * DURATION)
    t = np.arange(n) / SR

    # 包络：柔和的 8ms 起音 + 长指数衰减（尾音自然绵延，不突兀）
    env = np.exp(-t / DECAY_TAU)
    attack = int(0.008 * SR)
    env[:attack] = np.linspace(0.0, 1.0, attack)

    # 基频起音时略高、几十毫秒内回落（手碟敲击后的音头 bloom）
    f0 = freq * (1.0 + 0.004 * np.exp(-t / 0.03))
    phase = 2.0 * np.pi * np.cumsum(f0) / SR

    # 分音：以基频为主，八度/五度柔和点缀；去掉原来刺耳的非谐波泛音
    sig = (
        np.sin(phase)
        + 0.30 * np.sin(2.0 * np.pi * freq * 2.00 * t)   # 八度
        + 0.15 * np.sin(2.0 * np.pi * freq * 1.50 * t)   # 五度
        + 0.08 * np.sin(2.0 * np.pi * freq * 3.00 * t)   # 八度 + 五度
    )
    sig *= env

    # 轻敲击瞬态：柔和的低频「砰」取代原来的白噪 click，保留击打质感
    thump_n = int(0.02 * SR)
    thump = np.exp(-np.arange(thump_n) / (0.005 * SR)) * np.sin(
        2.0 * np.pi * freq * 0.8 * np.arange(thump_n) / SR
    )
    sig[:thump_n] += 0.15 * thump

    # 归一化，避免削波
    sig /= np.max(np.abs(sig)) + 1e-9

    # 尾部淡出防爆音
    fade = int(0.05 * SR)
    sig[-fade:] *= np.linspace(1.0, 0.0, fade)

    return (sig * 32767).astype(np.int16)


def build_sounds() -> dict:
    """预合成 9 个音并装载为 pygame.mixer.Sound，返回 {音名: Sound}。

    pygame.mixer 支持多声道并发播放，连续按时尾音会自然交叠，
    不像 winsound 那样「一按就掐断上一个音」。
    """
    pygame.mixer.pre_init(SR, -16, 1)   # 44100Hz / 16bit 有符号 / 单声道
    pygame.mixer.init()
    pygame.mixer.set_num_channels(MAX_CHANNELS)

    sounds = {}
    for note, freq in NOTE_FREQ.items():
        sounds[note] = pygame.mixer.Sound(buffer=synth_note(freq).tobytes())
    return sounds


# ── GUI ────────────────────────────────────────────────────────
def build_gui(sounds: dict) -> tk.Tk:
    root = tk.Tk()
    root.title("洛克王国 9 音手碟模拟器")
    root.configure(bg="#20232a")
    root.resizable(False, False)

    # 三排手碟布局：上排高音、中排中音、下排低音
    rows = [
        ("高音区", ["H1", "H2", "H3"], "#8a5a2b"),
        ("中音区", ["M3", "M4", "M5", "M6", "M7"], "#4a6b3a"),
        ("低音区", ["L6"], "#3a5a7a"),
    ]

    cell_bg = "#2c3038"
    cells = {}   # note -> label

    for reg_name, notes, accent in rows:
        frame = tk.Frame(root, bg="#20232a")
        frame.pack(pady=(8, 0))
        tk.Label(frame, text=reg_name, bg="#20232a", fg="#888",
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=(4, 8))
        for note in notes:
            key = NOTE_TO_KEY[note]
            lb = tk.Label(
                frame, text=f"{note}\n{key}",
                bg=cell_bg, fg="#eee", width=5, height=2,
                font=("Consolas", 14, "bold"),
                relief="flat", bd=0,
            )
            lb.pack(side="left", padx=6)
            cells[note] = lb

    status = tk.Label(root, text="聚焦此窗口，按 B / F G H J K / T Y U 发声",
                      bg="#20232a", fg="#ccc", font=("Microsoft YaHei", 11), pady=12)
    status.pack()

    def flash(note: str) -> None:
        lb = cells[note]
        lb.configure(bg="#e0a030", fg="#1a1a1a")
        root.after(140, lambda: lb.configure(bg=cell_bg, fg="#eee"))

    def on_key(event) -> None:
        ch = event.char.lower()
        note = KEY_TO_NOTE.get(ch)
        if not note:
            return
        try:
            sounds[note].play()
        except Exception as exc:
            status.configure(text=f"播放失败: {exc}")
            return
        flash(note)
        status.configure(text=f"{ch.upper()}  →  {note}  ({NOTE_FREQ[note]:.2f} Hz)")

    root.bind("<KeyPress>", on_key)
    root.focus_set()
    return root


def main() -> int:
    try:
        sounds = build_sounds()
    except Exception as exc:
        print(f"错误: {exc}")
        return 1
    root = build_gui(sounds)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
