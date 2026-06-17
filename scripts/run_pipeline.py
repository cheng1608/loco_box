"""无头运行一个 JSON pipeline。

用法:
    python scripts/run_pipeline.py tasks/surprise_box.json
    python scripts/run_pipeline.py tasks/surprise_box.json --com COM7

Ctrl+C 停止。
"""

import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loco_box.controller import Controller
from loco_box.pipeline.engine import PipelineCallbacks, PipelineEngine
from loco_box.pipeline.loader import PipelineLoader


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_pipeline.py <pipeline.json> [--com COMx]")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Pipeline file not found: {path}")
        sys.exit(1)

    # 解析 --com 参数
    com_port = "AUTO"
    if "--com" in sys.argv:
        idx = sys.argv.index("--com")
        if idx + 1 < len(sys.argv):
            com_port = sys.argv[idx + 1]

    print(f"Loading: {path}")
    pipeline_def = PipelineLoader.load(str(path))
    errors = PipelineLoader.validate(pipeline_def)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)

    print(f"Pipeline: {pipeline_def['name']}")
    print(f"Tasks: {len(pipeline_def['tasks'])}")
    print(f"Connecting to Arduino ({com_port})...")

    controller = Controller(com_port)
    if not controller.connect():
        # 自动检测失败，尝试用参数指定的端口
        if com_port == "AUTO":
            found = Controller.find_arduino()
            if found:
                controller = Controller(found)
                if not controller.connect():
                    print(f"Failed to connect to {found}. Running without Arduino.")
                else:
                    print(f"Connected to {found}")
            else:
                print("No Arduino found. Running without Arduino.")
        else:
            print(f"Failed to connect to {com_port}. Running without Arduino.")
    else:
        print(f"Connected to Arduino.")

    engine = PipelineEngine(
        pipeline_def,
        controller,
        callbacks=PipelineCallbacks(
            on_status=lambda msg: print(f"[STATUS] {msg}"),
            on_error=lambda msg: print(f"[ERROR] {msg}"),
            on_task_enter=lambda name: print(f"[TASK] → {name}"),
            on_task_exit=lambda name, ok: print(f"[TASK] ← {name} {'✓' if ok else '✗'}"),
            on_screenshot=lambda img: print(f"[SHOT] {img.shape}"),
        ),
    )

    def handle_sigint(sig, frame):
        print("\nStopping...")
        engine.stop()

    signal.signal(signal.SIGINT, handle_sigint)

    print("Running. Press Ctrl+C to stop.\n")
    engine.run()

    print(f"\nDone. Tasks executed: {engine.tasks_executed}")
    controller.disconnect()


if __name__ == "__main__":
    main()
