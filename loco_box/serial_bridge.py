"""Persistent, serialized USB CDC transport with negotiated firmware capabilities.

Protocol 1 keeps the original timed single-key commands. Protocol 2 uses complete
keyboard states; the device releases a lost music session after its watchdog.
Native USB CDC does not use ``baudrate`` as a UART throughput limit.
"""

import re
import threading
import time
from typing import Dict, List, Optional

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

_SERIAL_ERRORS = (OSError, ValueError) if serial is None else (OSError, ValueError, serial.SerialException)
_SESSION = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")
_KEY = re.compile(r"(?:[A-Za-z0-9]|ESC|TAB|SPACE|ENTER|LCTRL|RCTRL|LSHIFT|RSHIFT|LEFT|RIGHT|UP|DOWN|F(?:[1-9]|1[0-2])|MOUSE_LEFT|MOUSE_RIGHT)\Z", re.IGNORECASE)
_LEGACY_CAPS = {"protocol": 1, "max_keys": 1, "state": False, "watchdog_ms": 0, "firmware": "legacy"}


class SerialBridge:
    ACK_TIMEOUT = 0.25
    PROBE_TIMEOUT = 0.5
    MAX_RESPONSE = 1024

    def __init__(self, port: str = "AUTO", baudrate: int = 9600):
        self.port = port
        self.baudrate = baudrate
        self._ser = None
        self._lock = threading.RLock()
        self._caps = dict(_LEGACY_CAPS)
        self._rx = bytearray()
        self._last_error = ""
        self._stream_error = ""
        self._session = None
        self._sequence = -1
        self._mask = 0

    @property
    def last_error(self) -> str:
        return self._last_error

    def _fail(self, message: str) -> bool:
        self._last_error = message
        return False

    def connect(self) -> bool:
        with self._lock:
            if self.is_connected():
                return True
            if serial is None:
                return self._fail("pyserial is not installed")
            try:
                self._ser = serial.Serial(self.port, self.baudrate, timeout=0.02, write_timeout=0.2)
                self._rx.clear()
                self._caps = dict(_LEGACY_CAPS)
                self._session = None
                self._stream_error = self._last_error = ""
                return True
            except _SERIAL_ERRORS as exc:
                self._ser = None
                return self._fail(str(exc))

    def disconnect(self) -> None:
        with self._lock:
            try:
                if self._ser is not None:
                    self._ser.close()
            except _SERIAL_ERRORS as exc:
                self._last_error = str(exc)
            finally:
                self._ser = None
                self._session = None
                self._rx.clear()

    def is_connected(self) -> bool:
        connection = self._ser
        return connection is not None and connection.is_open

    def connect_and_wait(self, reset_wait: float = 3.0) -> bool:
        """Open once, allow board/USB settling, then perform a bounded probe.

        The settling delay preserves compatibility with clones and bootloaders;
        opening CDC is not inherently a hardware reset on every ATmega32U4.
        Call on a worker thread. Existing connections have no repeated delay.
        """
        with self._lock:
            if self.is_connected():
                return True
            if not self.connect():
                return False
            time.sleep(reset_wait)
            self.probe_capabilities()
            return self.is_connected()

    def capabilities(self) -> Dict:
        # Published as a replacement dictionary; status polling never waits for IO.
        return dict(self._caps)

    def _write(self, line: str) -> bool:
        if not self.is_connected():
            return self._fail("Serial device is disconnected")
        payload = (line + "\n").encode("ascii")
        try:
            if self._ser.write(payload) != len(payload):
                self._stream_error = "Incomplete serial write"
                # A partial line cannot safely be followed by another command.
                # Closing leaves music release to the device watchdog.
                self.disconnect()
                return self._fail(self._stream_error)
            # write_timeout bounds writes; flush() can wait indefinitely on drivers.
            return True
        except _SERIAL_ERRORS as exc:
            self._stream_error = str(exc)
            self.disconnect()
            return self._fail(self._stream_error)

    def _read_lines(self) -> List[str]:
        """Consume a bounded snapshot. Never wait for the next frame here."""
        if not self.is_connected():
            return []
        try:
            waiting = min(int(self._ser.in_waiting), self.MAX_RESPONSE)
            if waiting:
                self._rx.extend(self._ser.read(waiting))
            if len(self._rx) > self.MAX_RESPONSE:
                self._rx.clear()
                self._stream_error = "Firmware response exceeds limit"
                self._fail(self._stream_error)
                return []
            lines = []
            while b"\n" in self._rx:
                raw, _, remaining = self._rx.partition(b"\n")
                self._rx = bytearray(remaining)
                try:
                    line = raw.rstrip(b"\r").decode("ascii")
                except UnicodeDecodeError:
                    self._stream_error = "Invalid firmware response"
                    self._fail(self._stream_error)
                    continue
                if line.startswith("ERR "):
                    self._stream_error = line
                    self._fail(line)
                if line:
                    lines.append(line)
            return lines
        except _SERIAL_ERRORS as exc:
            self._stream_error = str(exc)
            self.disconnect()
            self._fail(self._stream_error)
            return []

    def _request(self, command: str, expected: str, timeout: Optional[float] = None,
                 recovering: bool = False) -> Optional[str]:
        self._read_lines()  # discard stale ACKs, but preserve protocol errors
        if self._stream_error and not recovering:
            self._fail(self._stream_error)
            return None
        if recovering:
            self._stream_error = ""
        if not self._write(command):
            return None
        deadline = time.monotonic() + (self.ACK_TIMEOUT if timeout is None else timeout)
        while self.is_connected():
            for line in self._read_lines():
                if line.startswith("ERR "):
                    return None
                if line == expected or line.startswith(expected + " "):
                    self._last_error = ""
                    return line
            if self._stream_error:
                return None
            if time.monotonic() >= deadline:
                self._fail("Firmware acknowledgement timed out: " + command.split()[0])
                return None
            time.sleep(0.002)
        return None

    def probe_capabilities(self, timeout: Optional[float] = None) -> Dict:
        with self._lock:
            response = self._request("HELLO 2", "CAPS", self.PROBE_TIMEOUT if timeout is None else timeout,
                                     recovering=True)
            self._caps = dict(_LEGACY_CAPS)
            if response is not None:
                fields = response.split()
                try:
                    if len(fields) != 5 or fields[1] != "2":
                        raise ValueError("Unsupported firmware capabilities")
                    max_keys, watchdog = int(fields[2]), int(fields[3])
                    if max_keys not in (6, 9) or not 500 <= watchdog <= 10000:
                        raise ValueError("Invalid firmware capabilities")
                    self._caps = {"protocol": 2, "max_keys": max_keys, "state": True,
                                  "watchdog_ms": watchdog, "firmware": fields[4]}
                    self._last_error = ""
                except ValueError as exc:
                    self._fail(str(exc))
            elif self.is_connected() and not self._stream_error:
                # Original firmware ignores HELLO. Silence is its legacy signature.
                self._last_error = ""
            return dict(self._caps)

    def send(self, key: str, hold_ms: int = 0) -> bool:
        with self._lock:
            if not isinstance(key, str) or not _KEY.fullmatch(key):
                return self._fail("Unknown key")
            if isinstance(hold_ms, bool) or not isinstance(hold_ms, int) or not 0 <= hold_ms <= 60000:
                return self._fail("hold_ms must be an integer in 0..60000")
            if self._session is not None:
                return self._fail("Music session is active")
            self._read_lines()
            if self._stream_error:
                return self._fail(self._stream_error)
            self._last_error = ""
            return self._write("%s:%s" % (key, hold_ms) if hold_ms else key)

    def begin_music(self, session: str) -> bool:
        with self._lock:
            if not isinstance(session, str) or not _SESSION.fullmatch(session):
                return self._fail("Invalid music session")
            if not self._caps["state"]:
                return self._fail("Firmware v2 is required for MIDI chords")
            if self._session == session:
                return True
            if self._request("BEGIN " + session, "OK BEGIN " + session, recovering=True) is None:
                return False
            self._session, self._sequence, self._mask = session, -1, 0
            return True

    def send_state(self, session: str, seq: int, mask: int) -> bool:
        with self._lock:
            if session != self._session or self._session is None:
                return self._fail("Music session does not own the device")
            if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq <= 0xFFFFFFFF:
                return self._fail("Invalid music sequence")
            if isinstance(mask, bool) or not isinstance(mask, int) or not 0 <= mask <= 511:
                return self._fail("Invalid key mask")
            if seq < self._sequence or (seq == self._sequence and mask != self._mask):
                return self._fail("Music sequence must increase")
            if bin(mask).count("1") > self._caps["max_keys"]:
                return self._fail("Chord exceeds firmware key capacity")
            self._read_lines()
            if self._stream_error:
                return self._fail(self._stream_error)
            if not self._write("STATE %s %s %s" % (session, seq, mask)):
                return False
            self._sequence, self._mask = seq, mask
            self._last_error = ""
            return True

    def heartbeat(self, session: str) -> bool:
        with self._lock:
            if session != self._session or self._session is None:
                return self._fail("Music session does not own the device")
            expected = "OK PING " + session
            response = self._request("PING " + session, expected)
            if response != "%s %s" % (expected, max(0, self._sequence)):
                return self._fail(self._last_error or "Device sequence differs from host")
            return True

    def end_music(self, session: str) -> None:
        with self._lock:
            if session != self._session or self._session is None:
                return
            if self._request("STOP " + session, "OK STOP " + session, recovering=True) is None:
                self.panic()
            self._session = None

    def panic(self) -> bool:
        with self._lock:
            self._session = None
            if not self._caps["state"]:
                return True  # Original firmware only releases at the timed deadline.
            return self._request("PANIC", "OK PANIC", recovering=True) is not None

    def press_key(self, key: str, hold_ms: int = 50) -> bool:
        return self.send(key, hold_ms)

    @staticmethod
    def list_ports() -> List[str]:
        if serial is None:
            return []
        return ["%s - %s" % (p.device, p.description) for p in serial.tools.list_ports.comports()]

    @staticmethod
    def find_arduino() -> Optional[str]:
        if serial is None:
            return None
        for p in serial.tools.list_ports.comports():
            desc = (p.description or "").lower()
            if "arduino" in desc or "micro" in desc:
                return p.device
        return None
