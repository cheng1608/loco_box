r"""Validate and import local pet-viewer resources without executing an installer.

Usage: .venv\Scripts\python.exe scripts/import_pet_resources.py --source PATH
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Dict, Optional, Tuple
import uuid


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = ROOT / "data" / "pet_viewer" / "resources"
DECODER_COMMIT = "287d33587f200d0c55026a0a66227d5c8a6a1ed6"
RELEASE = "https://github.com/Evenstar-tools/roco-pve-viewer/releases/tag/v0.1.14"
KNOWN_HASHES = {
    "all.pb": "8fe02b1a8ef8ee7bf191ef8ffc59d9d64077cf46c8c9af8591a3062241602825",
    "gamedata.json": "b021f08802c582d7d48fb627867d7c05053dcca83c148a92876e404966c01b55",
}


def find_resources(source: Path) -> Tuple[Path, Path]:
    """Find exactly one complete pair inside the explicitly selected directory."""
    root = source.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("来源必须是包含资源的目录，不是安装程序文件")
    candidates = []
    direct = root / "all.pb"
    descriptors = [direct] if direct.is_file() else root.rglob("all.pb")
    for descriptor in descriptors:
        catalog = descriptor.with_name("gamedata.json")
        if not catalog.is_file():
            continue
        # Do not leave the directory selected by the user through a link.
        try:
            descriptor.resolve().relative_to(root)
            catalog.resolve().relative_to(root)
        except ValueError:
            continue
        candidates.append((descriptor, catalog))
        if len(candidates) > 1:
            raise ValueError("找到多套资源，请将 --source 指向要导入的 assets 目录")
    if not candidates:
        raise ValueError("未找到同一目录下的 all.pb 和 gamedata.json")
    for path in candidates[0]:
        if not 0 < path.stat().st_size <= 50 * 1024 * 1024:
            raise ValueError("资源为空或超过 50 MB：" + path.name)
    return candidates[0]


def _validate(path: Path) -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from backend.pet_viewer.resources import load_resources

    load_resources(path)


def import_resources(
    source: Path,
    destination: Path = DEFAULT_DESTINATION,
    version: Optional[str] = None,
    source_release: Optional[str] = None,
) -> Dict[str, Any]:
    """Stage and validate a complete set, then swap directories with rollback.

    Previous resources remain in a uniquely named sibling backup directory.
    Encounter history is outside the resources directory and is never touched.
    """
    sources = find_resources(source)
    target = destination.expanduser().resolve()
    if not target.name:
        raise ValueError("资源目标必须是独立目录，不能是磁盘根目录")
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not target.is_dir():
        raise ValueError("资源目标已存在且不是目录")
    lock = parent / ("." + target.name + ".import.lock")
    try:
        lock_fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError("另一次资源导入尚未结束；若之前异常退出，请确认没有导入进程后移除 " + str(lock)) from exc
    os.close(lock_fd)
    stage = None
    backup = None
    try:
        stage = Path(tempfile.mkdtemp(prefix="." + target.name + ".staging-", dir=str(parent)))
        files = {}
        for source_path in sources:
            staged_file = stage / source_path.name
            shutil.copyfile(str(source_path), str(staged_file))
            contents = staged_file.read_bytes()
            files[source_path.name] = {
                "bytes": len(contents),
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
        known = all(files[name]["sha256"] == checksum for name, checksum in KNOWN_HASHES.items())
        manifest = {
            "version": version or ("v0.1.14" if known else "本地资源"),
            "source_release": source_release or (RELEASE if known else "本机导入"),
            "decoder_commit": DECODER_COMMIT,
            "files": files,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        _validate(stage)
        if target.exists():
            backup = parent / (target.name + ".backup-" + uuid.uuid4().hex)
            os.replace(str(target), str(backup))
        try:
            os.replace(str(stage), str(target))
        except OSError:
            if backup is not None:
                os.replace(str(backup), str(target))
            raise
        return {"destination": str(target), "backup": str(backup) if backup else None, **manifest}
    finally:
        # Only remove our own staging directory, resolved within the chosen parent.
        if stage is not None and stage.exists() and stage.resolve().parent == parent:
            shutil.rmtree(str(stage))
        lock.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="导入并验证精灵查看协议与配置；不运行安装程序")
    parser.add_argument("--source", required=True, type=Path, help="包含资源的 assets 目录或程序安装目录")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION, help="资源目标目录")
    parser.add_argument("--version", help="资源版本说明；已知 v0.1.14 文件自动识别")
    parser.add_argument("--source-release", help="资源来源说明或发布页地址")
    args = parser.parse_args()
    try:
        result = import_resources(args.source, args.destination, args.version, args.source_release)
    except (ValueError, OSError, ImportError) as exc:
        print("资源导入失败：" + str(exc), file=sys.stderr)
        return 1
    print("资源已验证并导入：" + result["destination"])
    print("版本：" + result["version"])
    if result["backup"]:
        print("旧资源已保留：" + result["backup"])
    print("请重新启动精灵监听，加载新的资源。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
