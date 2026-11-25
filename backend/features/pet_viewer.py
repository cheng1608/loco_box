"""Independent, read-only wild encounter viewer with cancellable capture."""

import copy
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from backend.core.config import DATA_DIR
from backend.features import Feature, register
from backend.pet_viewer.capture import CaptureError, Npcap, read_capture
from backend.pet_viewer.history import HistoryError, HistoryStore
from backend.pet_viewer.resources import ResourceError, load_resources


@register
class PetViewerFeature(Feature):
    id = "pet_viewer"
    name = "精灵查看"
    requires_arduino = False
    blocks_region_selection = False
    config_schema = [{"key": "adapter", "label": "监听网卡", "type": "string", "default": ""}]

    def __init__(self, ctx, resource_dir: Optional[Path] = None,
                 history_path: Optional[Path] = None, capture_factory=None) -> None:
        super().__init__(ctx)
        self.resource_dir = Path(resource_dir) if resource_dir is not None else DATA_DIR / "pet_viewer/resources"
        self._history = HistoryStore(history_path if history_path is not None else DATA_DIR / "pet_viewer/history.sqlite3")
        self._capture_factory = capture_factory or Npcap
        self._lock = threading.RLock()
        self._lifecycle = threading.Lock()
        self._generation = 0
        self._revision = 0
        self._session_id = uuid.uuid4().hex
        self._thread = None
        self._stop_event = threading.Event()
        self._running = False
        self._engine = None
        self._model = None
        self._catalog = None
        self._decoder = None
        self._resource_stamp = None
        self._resources = {"ready": False, "message": "尚未检查资源", "version": ""}
        self._source = "实时"
        self._history_error = ""
        self._packet_count = 0
        self._decoded_count = 0
        self._snapshot = self._empty_snapshot("stopped", "未开始监听", "先开始监听，再登录进入游戏世界")

    @staticmethod
    def _empty_snapshot(phase, status, message):
        return {"phase": phase, "status": status, "message": message, "pets": [],
                "selected": None, "battle_id": None, "blocked_battle_id": None}

    def _load_resources_locked(self):
        try:
            stamp = tuple((name, (self.resource_dir / name).stat().st_mtime_ns,
                           (self.resource_dir / name).stat().st_size)
                          for name in ("all.pb", "gamedata.json", "manifest.json")
                          if (self.resource_dir / name).is_file())
        except OSError:
            stamp = ()
        if stamp == self._resource_stamp and self._resources["ready"]:
            return
        self._resource_stamp = stamp
        try:
            self._decoder, self._catalog, self._resources = load_resources(self.resource_dir)
        except (ResourceError, OSError) as exc:
            self._decoder = self._catalog = None
            self._resources = {"ready": False, "message": str(exc), "version": ""}

    def _state_locked(self):
        value = copy.deepcopy(self._snapshot)
        # Protobuf identifiers can be uint64. Preserve them across JavaScript JSON.
        for pet in value["pets"]:
            pet["id"] = str(pet["id"])
        if value["selected"] is not None:
            value["selected"]["id"] = str(value["selected"]["id"])
        for key in ("battle_id", "blocked_battle_id"):
            if value.get(key) is not None:
                value[key] = str(value[key])
        if self._engine is not None:
            self._packet_count = self._engine.packet_count
            self._decoded_count = self._engine.decoded_count
        value.update(running=self._running, revision=self._revision, session_id=self._session_id,
                     source=self._source, resources=dict(self._resources), npcap_available=Npcap.available(),
                     packet_count=self._packet_count, decoded_count=self._decoded_count,
                     history_error=self._history_error)
        return value

    def state(self) -> Dict[str, Any]:
        with self._lock:
            if not self._running:
                self._load_resources_locked()
            return self._state_locked()

    def _publish_locked(self):
        self._revision += 1
        self.ctx.bus.publish_event("pet_viewer.state", self._state_locked())

    def _accept_snapshot(self, generation, snapshot, force=False):
        with self._lock:
            if generation != self._generation or self._stop_event.is_set():
                return False
            unchanged = snapshot == self._snapshot
            previous_error = self._history_error
            if not force and unchanged and not self._history.pending_deletions:
                return True
            self._snapshot = copy.deepcopy(snapshot)
            try:
                changed = self._history.record(dict(snapshot, source=self._source))
                if changed is not None and not self._history.pending_deletions:
                    self._history_error = ""
            except HistoryError as exc:
                self._history_error = str(exc)
            if force or not unchanged or self._history_error != previous_error:
                self._publish_locked()
            return True

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def adapters(self) -> Dict[str, Any]:
        try:
            adapters = self._capture_factory().adapters()
            return {"available": True, "adapters": [{"name": a.name, "description": a.description} for a in adapters],
                    "message": "" if adapters else "没有可用网卡，请连接网络后刷新"}
        except CaptureError as exc:
            return {"available": False, "adapters": [], "message": str(exc)}
        except (OSError, AttributeError):
            return {"available": False, "adapters": [], "message": "无法读取网卡，请检查 Npcap 驱动"}

    def start(self, config: Dict[str, Any]) -> None:
        adapter = config.get("adapter", "")
        if not isinstance(adapter, str) or len(adapter) > 1024:
            raise ValueError("网卡配置无效，请重新选择")
        with self._lifecycle:
            with self._lock:
                if self._running and self._source == "实时" and not self._stop_event.is_set():
                    return
            self._start_locked(adapter, demo=False)

    def demo(self) -> Dict[str, Any]:
        with self._lifecycle:
            self._start_locked("", demo=True)
        return self.state()

    def _start_locked(self, adapter, demo):
        self._stop_current()
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise ValueError("上次监听仍在停止，请稍后重试")
            self._source = "示例回放" if demo else "实时"
            self._load_resources_locked()
            if not self._resources["ready"]:
                self._snapshot = self._empty_snapshot("error", "资源未就绪", self._resources["message"])
                self._publish_locked()
                raise ValueError(self._resources["message"])
            try:
                capture = None if demo else self._capture_factory()
            except (CaptureError, OSError) as exc:
                self._snapshot = self._empty_snapshot("error", "监听未启动", str(exc))
                self._publish_locked()
                raise ValueError(str(exc)) from exc
            from backend.pet_viewer.model import BattleState
            from backend.pet_viewer.protocol import Engine

            self._stop_event = threading.Event()
            stop = self._stop_event
            generation = self._generation
            model = BattleState(self._catalog)
            model.begin_capture()
            self._model = model
            self._packet_count = self._decoded_count = 0
            self._running = True

            def message(flow, opcode, data):
                with self._lock:
                    if generation != self._generation or stop.is_set():
                        return
                    model.handle(flow, opcode, data)
                    self._accept_snapshot(generation, model.snapshot())

            def event(name, flow):
                if name == "activity":
                    return
                with self._lock:
                    if generation != self._generation or stop.is_set():
                        return
                    model.on_event(name, flow)
                    self._accept_snapshot(generation, model.snapshot())

            engine = Engine(self._decoder, message, event)
            self._engine = engine
            self._accept_snapshot(generation, model.snapshot(), force=True)

            def work():
                try:
                    if demo:
                        replay = Path(__file__).resolve().parents[1] / "pet_viewer/synthetic-demo.pcap"
                        previous = None
                        for stamp, linktype, raw in read_capture(replay):
                            if stop.is_set() or (previous is not None and stop.wait(min(max(stamp - previous, 0), 0.4))):
                                break
                            engine.feed(raw, linktype, stamp)
                            engine.tick(stamp)
                            previous = stamp
                        with self._lock:
                            if generation == self._generation and not stop.is_set():
                                model.phase = "ended"
                                model.status = "示例回放完成"
                                model.message = "当前为合成示例，未写入遭遇历史"
                                self._accept_snapshot(generation, model.snapshot(), force=True)
                    else:
                        capture.run(engine, stop, adapter or None)
                except Exception as exc:
                    with self._lock:
                        if generation == self._generation and not stop.is_set():
                            message_text = str(exc) if isinstance(exc, CaptureError) else "读取中断，请检查网卡、资源和游戏版本后重试"
                            model.clear("error", "读取中断", message_text)
                            self._accept_snapshot(generation, model.snapshot(), force=True)
                finally:
                    engine.clear()
                    with self._lock:
                        if self._thread is threading.current_thread():
                            self._packet_count, self._decoded_count = engine.packet_count, engine.decoded_count
                            self._engine = None
                            self._thread = None
                            self._running = False
                            if generation != self._generation:
                                self._model = None
                                self._snapshot = self._empty_snapshot("stopped", "已停止", "先开始监听，再登录进入游戏世界")
                            self._publish_locked()

            self._thread = threading.Thread(target=work, name="pet-viewer-capture", daemon=True)
            try:
                self._thread.start()
            except RuntimeError as exc:
                stop.set()
                engine.clear()
                self._generation += 1
                self._thread = self._engine = self._model = None
                self._running = False
                self._snapshot = self._empty_snapshot("error", "监听未启动", "无法启动监听线程，请稍后重试")
                self._publish_locked()
                raise ValueError("无法启动监听线程，请稍后重试") from exc

    def _stop_current(self):
        with self._lock:
            self._generation += 1
            self._stop_event.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            alive = thread is not None and thread.is_alive()
            self._running = alive
            self._model = None
            self._snapshot = self._empty_snapshot("stopping" if alive else "stopped", "正在停止" if alive else "已停止",
                                                  "正在释放网卡，请稍候" if alive else "先开始监听，再登录进入游戏世界")
            self._publish_locked()

    def stop(self) -> None:
        with self._lifecycle:
            self._stop_current()

    def select(self, pet_id: int) -> Dict[str, Any]:
        with self._lock:
            if self._model is None or pet_id not in self._model.pets:
                raise ValueError("当前遭遇中没有这只精灵")
            self._model.selected = pet_id
            self._snapshot = self._model.snapshot()
            self._publish_locked()
            return self._state_locked()

    def history(self, limit=50, offset=0) -> Dict[str, Any]:
        with self._lock:
            try:
                had_pending = bool(self._history.pending_deletions)
                result = self._history.page(limit, offset)
                if had_pending:
                    previous_error = self._history_error
                    self._history_error = self._history.pending_error
                    if previous_error != self._history_error:
                        self._publish_locked()
                if self._catalog is not None:
                    result["items"] = [self._catalog.nature_history(row) for row in result["items"]]
                return result
            except HistoryError as exc:
                raise ValueError(str(exc)) from exc
