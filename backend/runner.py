"""Desktop-owned backend process with a parent-lifetime pipe.

Tauri launches ``python -m backend.runner`` with stdin piped. Closing that pipe
(including a desktop crash) requests normal Uvicorn shutdown and runs the app's
lifespan cleanup. Standalone development can still use ``python -m uvicorn``.
"""

import argparse
import sys
import threading
import time
from typing import BinaryIO, Callable, Optional

import uvicorn


def _parent_reader(stream: Optional[BinaryIO]) -> Callable[[], None]:
    if sys.platform != "win32" or stream is None:
        return lambda: stream.read(1) if stream is not None else None

    import ctypes
    import msvcrt
    from ctypes import wintypes

    handle = msvcrt.get_osfhandle(stream.fileno())
    peek = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
    peek.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    peek.restype = wintypes.BOOL

    def wait_for_parent() -> None:
        # Do not issue a blocking stdin read on Windows. With the supported
        # Conda Python 3.9 + NumPy/OpenBLAS runtime, both buffered read() and
        # direct ReadFile can deadlock DLL initialization and new Python threads
        # until the pipe receives a byte. PeekNamedPipe avoids pending pipe I/O;
        # a broken pipe (parent exited) or any available byte requests shutdown.
        available = wintypes.DWORD()
        delay = threading.Event()
        while peek(handle, None, 0, None, ctypes.byref(available), None):
            if available.value:
                return
            delay.wait(0.1)

    return wait_for_parent


def _watch_parent(server: uvicorn.Server, read_parent: Callable[[], None]) -> None:
    try:
        read_parent()
    except (OSError, ValueError):
        pass
    # Uvicorn skips its shutdown phase if should_exit is set before startup
    # completes. Wait for startup to finish so an early parent exit still runs
    # the application lifespan's finally block.
    while not server.started and not server.should_exit:
        time.sleep(0.05)
    server.should_exit = True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    server = uvicorn.Server(uvicorn.Config(
        "backend.main:app", host=args.host, port=args.port,
        timeout_graceful_shutdown=2,
    ))
    read_parent = _parent_reader(getattr(sys.stdin, "buffer", sys.stdin))
    threading.Thread(
        target=_watch_parent, args=(server, read_parent), name="desktop-parent", daemon=True,
    ).start()
    server.run()


if __name__ == "__main__":
    main()
