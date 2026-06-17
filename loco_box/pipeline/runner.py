"""TaskRunner — 执行单个任务节点：轮询识别 → 命中后动作 → 返回路由。"""

import time

from loco_box.action.registry import ActionRegistry
from loco_box.controller import Controller
from loco_box.pipeline.loader import PipelineLoader
from loco_box.pipeline.task import TaskContext
from loco_box.recognition.registry import RecognizerRegistry
from loco_box.types import TaskResult


class TaskRunner:
    def __init__(self, controller: Controller, on_status=None):
        self._controller = controller
        self._rec_registry = RecognizerRegistry()
        self._act_registry = ActionRegistry()
        self._on_status = on_status or (lambda msg: None)

    def run(self, task_def: dict, context: TaskContext) -> TaskResult:
        """执行一个任务节点，返回路由结果。"""
        task_name = task_def.get("name", "unnamed")
        task_type = task_def.get("type", "recognize_then_act")

        if task_type == "act_only":
            return self._run_act_only(task_def, context)
        else:
            return self._run_recognize_then_act(task_def, context)

    def _run_recognize_then_act(self, task_def: dict, context: TaskContext) -> TaskResult:
        task_name = task_def["name"]
        rec_def = task_def.get("recognition", {})
        act_def = task_def.get("action", {})
        timeout_ms = task_def.get("timeout_ms", 0)
        poll_ms = task_def.get("poll_interval_ms", 300)

        rec_type = rec_def.get("type", "")
        rec_params = rec_def.get("params", {})
        region_def = rec_def.get("region")

        try:
            recognizer = self._rec_registry.create(rec_type, rec_params)
        except KeyError as e:
            return TaskResult(task_name, completed=False, error=str(e))

        # 解析识别区域
        region = PipelineLoader.resolve_region(region_def, context.regions)

        recognizer.reset()
        start = time.time()
        context.poll_count = 0

        while True:
            context.poll_count += 1
            context.screenshot = self._controller.screenshot(region)
            result = recognizer.recognize(context.screenshot, rec_params)
            context.recognition_result = result

            if result.matched:
                # 识别命中 → 执行动作
                self._on_status(f"{task_name}: 命中 (hits={result.metadata.get('hits',0)})")
                if act_def:
                    try:
                        action = self._act_registry.create(act_def.get("type", ""))
                        act_result = action.execute(self._controller, act_def.get("params", {}),
                                                    {"regions": context.regions, "recognition": result})
                        if not act_result.success:
                            return TaskResult(task_name, completed=False, error=act_result.message,
                                              next_task=task_def.get("on_error", task_def.get("next")))
                    except KeyError as e:
                        return TaskResult(task_name, completed=False, error=str(e),
                                          next_task=task_def.get("on_error"))

                return TaskResult(task_name, completed=True, next_task=task_def.get("next"))

            # 状态反馈（每 5 次轮询更新一次）
            hits = result.metadata.get("hits", 0)
            confirm = rec_params.get("confirm_count", 4)
            if context.poll_count % 5 == 1:
                if hits > 0:
                    self._on_status(f"{task_name}: {hits}/{confirm}")
                else:
                    self._on_status(f"{task_name}: 轮询中...")

            # 超时检查
            if timeout_ms > 0 and (time.time() - start) * 1000 > timeout_ms:
                return TaskResult(task_name, completed=False, error="timeout",
                                  next_task=task_def.get("on_error", task_def.get("next")))

            time.sleep(poll_ms / 1000.0)

    def _run_act_only(self, task_def: dict, context: TaskContext) -> TaskResult:
        task_name = task_def["name"]
        act_def = task_def.get("action", {})
        try:
            action = self._act_registry.create(act_def.get("type", ""))
            act_result = action.execute(self._controller, act_def.get("params", {}),
                                        {"regions": context.regions})
            if not act_result.success:
                return TaskResult(task_name, completed=False, error=act_result.message,
                                  next_task=task_def.get("on_error"))
            return TaskResult(task_name, completed=True, next_task=task_def.get("next"))
        except KeyError as e:
            return TaskResult(task_name, completed=False, error=str(e))
