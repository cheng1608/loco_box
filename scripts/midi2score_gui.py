"""MIDI → 按键谱 转换 · 简单可视化窗口（tkinter）。

独立小工具，不依赖 box 主界面。双击 ``run_midi2score_gui.bat`` 或：

    .venv/Scripts/python.exe scripts/midi2score_gui.py

选一个 .mid → 调参数 → 点「转换」看结果 → 「保存到 data/scores」即可演奏。
依赖 mido（midi2score.py 已容错处理）。
"""

import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from midi2score import convert_midi_to_score, score_to_text
except ImportError:
    from scripts.midi2score import convert_midi_to_score, score_to_text

ROOT = Path(__file__).resolve().parents[1]
MIDI_DIR = Path(__file__).resolve().parent / "music"
SCORES_DIR = ROOT / "data" / "scores"

# 选项显示名 → 实际参数值
TRACK_OPTIONS = [("自动旋律轨", "auto"), ("全部轨道", None)]
STRATEGY_OPTIONS = [("音级折叠（保音准）", "degree"), ("就近映射（保连贯）", "nearest"), ("平滑映射（折中）", "smooth")]
POLY_OPTIONS = [("最高音", "top"), ("最低音", "bottom"), ("最大力度", "loudest")]
ROOT_OPTIONS = [("自动检测", None)] + [(str(i), i) for i in range(12)]


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.current_notes = None
        self.current_stem = "score"
        self._build()
        self._load_midi_list()

    def _build(self) -> None:
        self.root.title("MIDI → 按键谱转换")
        self.root.geometry("700x620")
        self.root.minsize(520, 480)

        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        # 输入文件
        row = ttk.Frame(main)
        row.pack(fill="x", pady=(0, 10))
        ttk.Label(row, text="输入 .mid：").pack(side="left")
        self.midi_var = tk.StringVar()
        self.midi_box = ttk.Combobox(row, textvariable=self.midi_var)
        self.midi_box.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="浏览…", command=self.browse).pack(side="left")

        # 选项（2x2）
        opts = ttk.Frame(main)
        opts.pack(fill="x", pady=(0, 10))
        opts.columnconfigure(1, weight=1)
        opts.columnconfigure(3, weight=1)
        self.track_box, self.track_map = self._combo(opts, 0, 0, "轨道", TRACK_OPTIONS)
        self.strategy_box, self.strategy_map = self._combo(opts, 0, 2, "音高映射", STRATEGY_OPTIONS)
        self.poly_box, self.poly_map = self._combo(opts, 1, 0, "和弦折叠", POLY_OPTIONS)
        self.root_box, self.root_map = self._combo(opts, 1, 2, "主音", ROOT_OPTIONS)

        ttk.Button(main, text="转换", command=self.convert).pack(pady=(0, 10))

        # 结果
        self.result_label = ttk.Label(main, text="结果")
        self.result_label.pack(anchor="w", pady=(0, 4))

        txt_frame = ttk.Frame(main)
        txt_frame.pack(fill="both", expand=True)
        self.result_text = tk.Text(txt_frame, wrap="none", font=("Consolas", 10))
        yscroll = ttk.Scrollbar(txt_frame, orient="vertical", command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=yscroll.set)
        self.result_text.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        # 底部按钮
        btns = ttk.Frame(main)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="保存到 data/scores", command=self.save).pack(side="left")
        ttk.Button(btns, text="另存为…", command=self.save_as).pack(side="left", padx=6)
        ttk.Button(btns, text="打开 scores 文件夹", command=self.open_folder).pack(side="right")

    def _combo(self, parent, row, col, label, options, default_idx=0):
        ttk.Label(parent, text=label + "：").grid(row=row, column=col, sticky="e", padx=(0, 6), pady=4)
        labels = [lbl for lbl, _ in options]
        value_map = {lbl: val for lbl, val in options}
        var = tk.StringVar(value=labels[default_idx])
        box = ttk.Combobox(parent, textvariable=var, values=labels, state="readonly")
        box.grid(row=row, column=col + 1, sticky="ew", pady=4)
        return box, value_map

    def _load_midi_list(self) -> None:
        full = []
        if MIDI_DIR.is_dir():
            full = [
                str(MIDI_DIR / p.name)
                for p in sorted(MIDI_DIR.iterdir())
                if p.is_file() and p.suffix.lower() == ".mid"
            ]
        self.midi_box["values"] = full
        if full:
            self.midi_var.set(full[0])

    def browse(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 .mid 文件",
            filetypes=[("MIDI 文件", "*.mid *.midi"), ("所有文件", "*.*")],
        )
        if path:
            self.midi_var.set(path)

    def convert(self) -> None:
        path = self.midi_var.get().strip()
        if not path:
            messagebox.showwarning("提示", "请先选择 .mid 文件")
            return
        p = Path(path)
        if not p.is_file():
            messagebox.showerror("错误", f"文件不存在：{path}")
            return
        try:
            notes = convert_midi_to_score(
                str(p),
                track=self.track_map[self.track_box.get()],
                root=self.root_map[self.root_box.get()],
                polyphony=self.poly_map[self.poly_box.get()],
                strategy=self.strategy_map[self.strategy_box.get()],
            )
        except Exception as exc:  # mido 缺失 / 轨道越界 / 未知策略等
            messagebox.showerror("转换失败", str(exc))
            return
        if not notes:
            messagebox.showwarning("提示", "未提取到音符（可能为空或只有打击乐）")
            return
        self.current_notes = notes
        self.current_stem = p.stem
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", score_to_text(notes, song_name=p.stem))
        self.result_label.config(text=f"结果（{len(notes)} 个音）")

    def save(self) -> None:
        if self.current_notes is None:
            messagebox.showwarning("提示", "请先转换")
            return
        SCORES_DIR.mkdir(parents=True, exist_ok=True)
        out = SCORES_DIR / (self.current_stem + ".txt")
        out.write_text(score_to_text(self.current_notes, song_name=self.current_stem), encoding="utf-8")
        messagebox.showinfo("已保存", f"已保存到：\n{out}")

    def save_as(self) -> None:
        if self.current_notes is None:
            messagebox.showwarning("提示", "请先转换")
            return
        out = filedialog.asksaveasfilename(
            title="另存为",
            defaultextension=".txt",
            initialfile=self.current_stem + ".txt",
            filetypes=[("按键谱", "*.txt"), ("所有文件", "*.*")],
        )
        if not out:
            return
        Path(out).write_text(score_to_text(self.current_notes, song_name=self.current_stem), encoding="utf-8")
        messagebox.showinfo("已保存", f"已保存到：\n{out}")

    def open_folder(self) -> None:
        SCORES_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(SCORES_DIR))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("错误", str(exc))


if __name__ == "__main__":
    try:  # HiDPI 下让 tkinter 文字更清晰
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()
