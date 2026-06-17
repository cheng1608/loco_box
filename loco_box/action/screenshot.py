"""截图保存动作。"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from loco_box.action.base import BaseAction
from loco_box.controller import Controller
from loco_box.image_ops import save_bgr
from loco_box.types import ActionResult


class ScreenshotAction(BaseAction):
    """截取指定区域并保存为 PNG。

    JSON params:
        region: str|dict    - 区域名（引用 pipeline regions）或内联 dict
        save_dir: str       - 保存目录，默认 data/shots/
        filename: str       - 自定义文件名，默认时间戳
    """

    def execute(self, controller: Controller, params: dict, context: Optional[dict] = None) -> ActionResult:
        region_def = params.get("region")
        if region_def is None:
            return ActionResult(success=False, message="no region specified")

        # 解析 region：从 context 查找或直接使用
        if isinstance(region_def, str) and context and "regions" in context:
            region = context["regions"].get(region_def)
        elif isinstance(region_def, dict):
            region = region_def
        else:
            return ActionResult(success=False, message=f"invalid region: {region_def}")

        save_dir = Path(params.get("save_dir", "data/shots"))
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = params.get("filename") or datetime.now().strftime("shot_%Y%m%d_%H%M%S.png")
        filepath = save_dir / filename

        img = controller.screenshot(region)
        save_bgr(filepath, img)
        # 通知 GUI
        if context and context.get("on_screenshot"):
            context["on_screenshot"](img)
        return ActionResult(success=True, message=str(filepath))
