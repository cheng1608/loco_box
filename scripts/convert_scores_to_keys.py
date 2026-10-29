"""把 data/scores/ 下的旧简谱（音名 H1/M3/L6 格式）原地转成按键谱（键位字母）。

原来每行是 `音符 停顿ms`（音符 = L6/M3/M4/M5/M6/M7/H1/H2/H3），
现在改成 `按键 停顿ms`（按键 = B/F/G/H/J/K/T/Y/U），停顿毫秒不变。

用法：
    .venv/Scripts/python.exe scripts/convert_scores_to_keys.py             # 原地转换
    .venv/Scripts/python.exe scripts/convert_scores_to_keys.py --dry-run   # 只打印，不写盘

幂等：已经写成键位字母的行原样保留，重复运行不会出错。
"""

import argparse
import re
import sys
from pathlib import Path

# 旧音名 → 键位（与 music.py 旧 NOTE_TO_KEY 一致）
NOTE_TO_KEY = {
    "L6": "B", "M3": "F", "M4": "G", "M5": "H",
    "M6": "J", "M7": "K", "H1": "T", "H2": "Y", "H3": "U",
}

SCORES_DIR = Path(__file__).resolve().parents[1] / "data" / "scores"

# 匹配一行：`音名/按键 [分隔] 停顿ms`。字母后不得紧跟字母/数字，避免把 H1 误当成 H。
_LINE = re.compile(r"^\s*([A-Za-z]\d?)(?![A-Za-z0-9])(?:\s*[:=, ]\s*(\d+))?\s*$")


def convert_line(line: str) -> str:
    """转换一行。注释行 / 空行 / 已是按键 / 非法 token 原样返回。"""
    m = _LINE.match(line)
    if not m:
        return line
    token = m.group(1).upper()
    pause = m.group(2)
    key = NOTE_TO_KEY.get(token)
    if key is None:
        return line
    return f"{key} {pause}" if pause else key


def convert_file(path: Path, dry_run: bool) -> int:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out, converted = [], 0
    for ln in lines:
        new = convert_line(ln)
        if new != ln:
            converted += 1
        out.append(new)
    if converted and not dry_run:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return converted


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把 data/scores/ 的简谱音名转成按键谱")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写盘")
    args = parser.parse_args(argv)

    if not SCORES_DIR.is_dir():
        print(f"未找到目录：{SCORES_DIR}", file=sys.stderr)
        return 1

    total = 0
    for path in sorted(SCORES_DIR.glob("*.txt")):
        n = convert_file(path, args.dry_run)
        tag = "（预览）" if args.dry_run else ""
        print(f"{path.name}: 转换 {n} 行{tag}")
        total += n
    print(f"共转换 {total} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
