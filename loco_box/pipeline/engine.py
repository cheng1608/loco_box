"""PipelineEngine — 流水线状态机。加载 JSON，顺序执行每个任务节点。"""

import threading
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from loco_box.controller import Controller
from loco_box.pipeline.loader import PipelineLoader
from loco_box.pipeline.runner import TaskRunner
from loco_box.pipeline.task import TaskContext
from loco_box.types import TaskResult


@dataclass
class PipelineCallbacks:
    """流水线生命周期回调。所有回调在引擎线程中调用。"""
    on_status: Callable[[str], None] = lambda msg: None
    on_screenshot: Callable[[np.ndarray], None] = lambda img: None
    on_error: Callable[[str], None] = lambda msg: None
    on_task_enter: Callable[[str], None] = lambda name: None
    on_task_exit: Callable[[str, bool], None] = lambda name, ok: None
    on_stopped: Callable[[], None] = lambda: None


class PipelineEngine:
    """MAA 式流水线引擎。

    用法:
        engine = PipelineEngine(pipeline_def, controller, callbacks=...)
        engine.run()          # 阻塞运行
        engine.run_async()    # 后台线程运行
        engine.stop()         # 停止
    """

    MAX_ITERATIONS = 9999

    def __init__(
        self,
        pipeline_def: dict,
        controller: Controller,
        callbacks: Optional[PipelineCallbacks] = None,
    ):
        self._pipeline = pipeline_def
        self._controller = controller
        self._callbacks = callbacks or PipelineCallbacks()
        self._runner = TaskRunner(controller, on_status=self._callbacks.on_status)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._current_task: Optional[str] = None
        self._iterations = 0
        self._tasks_executed = 0

    # ─── 公开 API ──────────────────────────────────
    def run(self) -> bool:
        """阻塞运行流水线，返回是否正常完成。"""
        self._stop_event.clear()
        self._callbacks.on_status("Pipeline starting")
        try:
            self._execute_loop()
            return True
        except Exception as e:
            self._callbacks.on_error(str(e))
            return False
        finally:
            self._callbacks.on_stopped()
            self._callbacks.on_status("Pipeline stopped")

    def run_async(self) -> None:
        """在后台守护线程中运行。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._execute_loop_safe, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """请求停止流水线。"""
        self._stop_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def current_task(self) -> Optional[str]:
        return self._current_task

    @property
    def iterations(self) -> int:
        return self._iterations

    @property
    def tasks_executed(self) -> int:
        return self._tasks_executed

    # ─── 内部 ──────────────────────────────────────
    def _execute_loop_safe(self):
        try:
            self._execute_loop()
        except Exception as e:
            self._callbacks.on_error(str(e))
        finally:
            self._callbacks.on_stopped()
            self._callbacks.on_status("Pipeline stopped")

    def _execute_loop(self):
        tasks = self._pipeline.get("tasks", [])
        if not tasks:
            self._callbacks.on_error("No tasks in pipeline")
            return

        regions = self._pipeline.get("regions", {})
        max_iter = self._pipeline.get("max_iterations", self.MAX_ITERATIONS)
        entry = tasks[0]["name"]
        task_map = {t["name"]: t for t in tasks}

        context = TaskContext(regions=regions, variables={
            "on_screenshot": self._callbacks.on_screenshot,
            "on_status": self._callbacks.on_status,
        })
        current = entry

        while not self._stop_event.is_set() and self._iterations < max_iter:
            if current is None:
                break

            task_def = task_map.get(current)
            if task_def is None:
                self._callbacks.on_error(f"Task not found: {current}")
                break

            self._current_task = current
            self._callbacks.on_task_enter(current)

            result: TaskResult = self._runner.run(task_def, context)
            self._tasks_executed += 1

            self._callbacks.on_task_exit(current, result.completed)

            if not result.completed and result.error:
                self._callbacks.on_status(f"Task error: {result.error}")

            next_task = result.next_task
            if next_task is None:
                break
            if next_task == current:
                self._iterations += 1
            current = next_task
