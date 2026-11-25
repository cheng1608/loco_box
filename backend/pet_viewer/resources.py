"""Load local protocol/configuration resources without requiring them at startup."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Tuple


class ResourceError(ValueError):
    pass


def load_resources(directory: Path) -> Tuple[Any, Any, Dict[str, Any]]:
    try:
        return _load_resources(directory)
    except ResourceError:
        raise
    except Exception as exc:
        # Includes protobuf DecodeError and inaccessible filesystem entries.
        # Resource loading failure must never prevent the rest of Box starting.
        raise ResourceError("精灵协议或配置无法加载，请导入匹配当前功能的配套资源") from exc


def _load_resources(directory: Path) -> Tuple[Any, Any, Dict[str, Any]]:
    directory = Path(directory)
    paths = {name: directory / name for name in ("all.pb", "gamedata.json")}
    for name, path in paths.items():
        if not path.is_file():
            raise ResourceError("缺少精灵资源 %s，请先导入配套协议与配置" % name)
        if not 0 < path.stat().st_size <= 32 * 1024 * 1024:
            raise ResourceError("精灵资源 %s 大小异常" % name)
    try:
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig")) if manifest_path.is_file() else {}
        if not isinstance(manifest, dict):
            raise ResourceError("精灵资源版本记录格式无效")
        hashes = manifest.get("files", {})
        if not isinstance(hashes, dict):
            raise ResourceError("精灵资源校验记录格式无效")
        for name, path in paths.items():
            entry = hashes.get(name, {})
            if not isinstance(entry, dict):
                raise ResourceError("精灵资源校验记录格式无效")
            expected = entry.get("sha256")
            if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ResourceError("精灵资源 %s 校验失败，请重新导入完整资源" % name)
        data = json.loads(paths["gamedata.json"].read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or any(not isinstance(data.get(key), dict) for key in ("species", "natures", "medals")):
            raise ResourceError("精灵配置需要 species、natures 和 medals 三张表")
        natures = data["natures"]
        if not natures:
            raise ResourceError("性格配置表为空")
        for ident, item in natures.items():
            if (not ident.isdigit() or not isinstance(item, dict)
                    or not isinstance(item.get("name"), str) or not item["name"]
                    or type(item.get("positive")) not in (int, float) or item["positive"] not in range(79, 85)
                    or type(item.get("negative")) not in (int, float) or item["negative"] not in range(79, 85)):
                raise ResourceError("性格配置表包含无效编号、名称或属性")
        if any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in data["species"].values()):
            raise ResourceError("精灵名称配置格式无效")
        if any(not isinstance(item, str) for item in data["medals"].values()):
            raise ResourceError("奖章配置格式无效")
        # Optional dependencies are imported here, never when registering Feature.
        from .protocol import Decoder
        from .model import Catalog

        decoder = Decoder(paths["all.pb"])
        catalog = Catalog(paths["gamedata.json"])
        return decoder, catalog, {"ready": True, "message": "协议与配置已就绪", "version": str(manifest.get("version", "本地资源"))}
    except ResourceError:
        raise
    except ImportError as exc:
        raise ResourceError("缺少精灵解析依赖，请安装 requirements.txt 中的 protobuf 和 pycryptodome") from exc
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ResourceError("精灵协议或配置无法加载，请导入匹配当前功能的配套资源") from exc
