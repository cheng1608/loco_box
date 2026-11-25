"""One persistent Arduino connection with atomic per-feature ownership."""

import threading
from typing import Dict, Optional

from loco_box.serial_bridge import SerialBridge


class DeviceBusyError(ValueError):
    """The requested input device is already owned by another feature."""


class ArduinoController:
    def __init__(self) -> None:
        self._bridge: Optional[SerialBridge] = None
        self._lock = threading.RLock()
        self._config = None
        self._owner: Optional[str] = None
        self._last_error = ""

    def set_config(self, config) -> None:
        self._config = config

    @property
    def last_error(self) -> str:
        bridge = self._bridge
        return self._last_error or (bridge.last_error if bridge else "")

    def current_owner(self) -> Optional[str]:
        return self._owner

    def acquire(self, owner: str) -> bool:
        with self._lock:
            if not isinstance(owner, str) or not owner:
                self._last_error = "Device owner must be a nonempty name"
                return False
            if self._owner is not None and self._owner != owner:
                self._last_error = "Device is owned by " + self._owner
                return False
            self._owner = owner
            self._last_error = ""
            return True

    def release(self, owner: str) -> None:
        with self._lock:
            if self._owner != owner:
                return
            # Serialize release with writes so no old worker can send afterward.
            if self._bridge and self._bridge.is_connected():
                if not self._bridge.panic():
                    self._bridge.disconnect()
            self._owner = None

    def is_connected(self) -> bool:
        bridge = self._bridge
        return bridge is not None and bridge.is_connected()

    def port(self) -> Optional[str]:
        bridge = self._bridge
        return bridge.port if bridge else None

    def _resolve_port(self, com_port: str) -> Optional[str]:
        if com_port and com_port.upper() != "AUTO":
            return com_port
        detected = SerialBridge.find_arduino()
        if detected:
            return detected
        if self._config is not None:
            saved = self._config.get_global("com_port", "AUTO")
            if saved and str(saved).upper() != "AUTO":
                return str(saved)
        return None

    def connect(self, com_port: str = "AUTO", owner: str = "manual") -> bool:
        """Open/probe once on a worker thread; existing connections stay open."""
        with self._lock:
            if self._bridge and self._bridge.is_connected():
                return True
            # A worker may reach this call after its run was stopped. Check its
            # lease under the same lock as opening, so it cannot revive a port.
            if not self._allows(owner):
                return False
            port = self._resolve_port(com_port)
            if not port:
                self._last_error = "No Arduino serial port found"
                return False
            bridge = SerialBridge(port)
            if not bridge.connect_and_wait():
                self._last_error = bridge.last_error
                return False
            self._bridge = bridge
            self._last_error = ""
            if self._config is not None:
                self._config.set_global("com_port", port)
            return True

    def capabilities(self) -> Dict:
        bridge = self._bridge
        if bridge is not None:
            return bridge.capabilities()
        return {"protocol": 0, "max_keys": 0, "state": False, "watchdog_ms": 0, "firmware": "disconnected"}

    def _allows(self, owner: str) -> bool:
        # Named workers must hold a lease. Manual requests may use idle devices.
        allowed = self._owner == owner or (owner == "manual" and self._owner is None)
        if not allowed:
            self._last_error = "Device is owned by %s" % (self._owner or "no active feature")
        return allowed

    def disconnect(self, owner: str = "manual", force: bool = False) -> bool:
        with self._lock:
            if not force and not self._allows(owner):
                return False
            if self._bridge:
                if self._bridge.is_connected():
                    self._bridge.panic()
                self._bridge.disconnect()
                self._bridge = None
            self._owner = None
            self._last_error = ""
            return True

    def send(self, key: str, hold_ms: int = 0, owner: str = "manual") -> bool:
        with self._lock:
            if not self._allows(owner):
                return False
            self._last_error = ""
            if self._bridge is None or not self._bridge.is_connected():
                self._last_error = "Serial device is disconnected"
                return False
            return self._bridge.send(key, hold_ms)

    def begin_music(self, session: str) -> bool:
        with self._lock:
            if not self._allows("music") or self._bridge is None:
                return False
            self._last_error = ""
            return self._bridge.begin_music(session)

    def send_state(self, session: str, seq: int, mask: int) -> bool:
        with self._lock:
            if not self._allows("music") or self._bridge is None:
                return False
            self._last_error = ""
            return self._bridge.send_state(session, seq, mask)

    def heartbeat(self, session: str) -> bool:
        with self._lock:
            if not self._allows("music") or self._bridge is None:
                return False
            self._last_error = ""
            return self._bridge.heartbeat(session)

    def end_music(self, session: str) -> None:
        with self._lock:
            if self._owner == "music" and self._bridge is not None:
                self._bridge.end_music(session)

    def press_key(self, key: str, hold_ms: int = 50, owner: str = "manual") -> bool:
        return self.send(key, hold_ms, owner=owner)
