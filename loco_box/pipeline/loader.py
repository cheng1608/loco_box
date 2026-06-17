"""Pipeline JSON 加载、校验、baseTask 继承解析。"""

import json
from copy import deepcopy
from pathlib import Path


class PipelineLoader:
    """加载并校验 JSON pipeline 定义。"""

    @staticmethod
    def load(path: str) -> dict:
        """从 JSON 文件加载 pipeline 定义。"""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # 解析 baseTask 继承
        if data.get("baseTask"):
            base_path = Path(path).parent / data["baseTask"]
            if base_path.suffix != ".json":
                base_path = base_path.with_suffix(".json")
            if base_path.exists():
                data = PipelineLoader._merge(PipelineLoader.load(str(base_path)), data)

        return data

    @staticmethod
    def validate(data: dict) -> list[str]:
        """校验 pipeline 定义，返回错误列表。空列表表示通过。"""
        errors = []
        if not data.get("name"):
            errors.append("missing 'name'")
        if not data.get("tasks"):
            errors.append("missing 'tasks'")
        else:
            for i, task in enumerate(data["tasks"]):
                if not task.get("name"):
                    errors.append(f"task[{i}]: missing 'name'")
        return errors

    @staticmethod
    def _merge(base: dict, override: dict) -> dict:
        """深度合并 override 到 base（override 优先）。"""
        result = deepcopy(base)
        for key, value in override.items():
            if key == "tasks":
                # 任务列表：按名称覆盖
                base_tasks = {t["name"]: t for t in result.get("tasks", [])}
                for t in value:
                    name = t.get("name")
                    if name and name in base_tasks:
                        base_tasks[name] = PipelineLoader._merge(base_tasks[name], t)
                    else:
                        base_tasks[name] = t
                result["tasks"] = list(base_tasks.values())
            elif isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = PipelineLoader._merge(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result

    @staticmethod
    def resolve_region(region_def, regions: dict) -> dict:
        """解析区域引用：字符串名 → 内联 dict。"""
        if isinstance(region_def, str):
            return regions.get(region_def, {})
        return region_def if isinstance(region_def, dict) else {}
