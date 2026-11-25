# Adapted from Evenstar-tools/roco-pve-viewer @ 287d335 (MIT).
# Copyright (c) 2026 Evenstar-tools. See LICENSE.upstream.
"""Npcap read-only binding. Intentionally exposes no packet-send APIs."""
from __future__ import annotations
import ctypes as C
from dataclasses import dataclass
import os
from pathlib import Path
import struct
import threading
import time

FILTER = b"tcp src port 8195"


class CaptureError(RuntimeError):
    pass


@dataclass
class Adapter:
    name: str
    description: str
    flags: int


class PcapIf(C.Structure):
    pass


PcapIf._fields_ = [("next", C.POINTER(PcapIf)), ("name", C.c_char_p), ("description", C.c_char_p),
                  ("addresses", C.c_void_p), ("flags", C.c_uint)]


class BpfProgram(C.Structure):
    _fields_ = [("length", C.c_uint), ("instructions", C.c_void_p)]


class PacketHeader(C.Structure):
    # Windows libpcap timeval uses two 32-bit long values, including on x64.
    _fields_ = [("seconds", C.c_int32), ("microseconds", C.c_int32), ("caplen", C.c_uint32), ("length", C.c_uint32)]


class Npcap:
    @staticmethod
    def available():
        return (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/Npcap/wpcap.dll").is_file()

    def __init__(self):
        if os.name != "nt":
            raise CaptureError("实时采集仅支持 Windows")
        folder = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "Npcap"
        dll = folder / "wpcap.dll"
        if not dll.is_file():
            raise CaptureError("未安装 Npcap：请从 npcap.com 安装官方驱动后重新打开程序")
        self.dll_directory = os.add_dll_directory(str(folder))
        try:
            self.lib = C.CDLL(str(dll))
        except OSError as exc:
            raise CaptureError("Npcap 无法加载，请检查驱动安装及 64 位版本") from exc
        specs = {
            "pcap_findalldevs": ([C.POINTER(C.POINTER(PcapIf)), C.c_char_p], C.c_int),
            "pcap_freealldevs": ([C.POINTER(PcapIf)], None),
            "pcap_open_live": ([C.c_char_p, C.c_int, C.c_int, C.c_int, C.c_char_p], C.c_void_p),
            "pcap_close": ([C.c_void_p], None),
            "pcap_compile": ([C.c_void_p, C.POINTER(BpfProgram), C.c_char_p, C.c_int, C.c_uint32], C.c_int),
            "pcap_setfilter": ([C.c_void_p, C.POINTER(BpfProgram)], C.c_int),
            "pcap_freecode": ([C.POINTER(BpfProgram)], None),
            "pcap_setnonblock": ([C.c_void_p, C.c_int, C.c_char_p], C.c_int),
            "pcap_datalink": ([C.c_void_p], C.c_int),
            "pcap_next_ex": ([C.c_void_p, C.POINTER(C.POINTER(PacketHeader)), C.POINTER(C.POINTER(C.c_ubyte))], C.c_int),
        }
        for name, (args, result) in specs.items():
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = args, result
        if hasattr(self.lib, "pcap_init"):
            self.lib.pcap_init.argtypes = [C.c_uint, C.c_char_p]
            self.lib.pcap_init.restype = C.c_int
            err = C.create_string_buffer(256)
            if self.lib.pcap_init(1, err) != 0:
                raise CaptureError("Npcap 初始化失败")

    def adapters(self):
        ptr = C.POINTER(PcapIf)()
        err = C.create_string_buffer(256)
        if self.lib.pcap_findalldevs(C.byref(ptr), err) != 0:
            raise CaptureError("无法列出网卡，请检查 Npcap 服务或管理员权限")
        result, cur = [], ptr
        try:
            while cur:
                item = cur.contents
                if item.name:
                    name = item.name.decode("utf-8", errors="replace")
                    desc = (item.description or item.name).decode("utf-8", errors="replace")
                    if not item.flags & 1:  # skip loopback
                        result.append(Adapter(name, desc, item.flags))
                cur = item.next
        finally:
            if ptr:
                self.lib.pcap_freealldevs(ptr)
        return result

    def open(self, adapter):
        err = C.create_string_buffer(256)
        # Promiscuous mode is disabled; no other hosts' traffic is requested.
        handle = self.lib.pcap_open_live(adapter.name.encode("utf-8"), 65535, 0, 100, err)
        if not handle:
            raise CaptureError("无法读取所选网卡；若 Npcap 限管理员访问，请以管理员身份运行")
        program = BpfProgram()
        try:
            if self.lib.pcap_compile(handle, C.byref(program), FILTER, 1, 0xFFFFFFFF) != 0:
                raise CaptureError("无法设置游戏流量过滤器")
            try:
                if self.lib.pcap_setfilter(handle, C.byref(program)) != 0:
                    raise CaptureError("游戏流量过滤器未生效")
            finally:
                self.lib.pcap_freecode(C.byref(program))
            if self.lib.pcap_setnonblock(handle, 1, err) != 0:
                raise CaptureError("无法启用可停止的读取模式")
            linktype = self.lib.pcap_datalink(handle)
            if linktype not in (0, 1, 12, 101, 108, 113, 228, 229):
                raise CaptureError("所选网卡的数据格式尚不支持")
            return handle, linktype
        except Exception:
            self.lib.pcap_close(handle)
            raise

    def run(self, engine, stop_event: threading.Event, selection=None):
        adapters = self.adapters()
        if selection:
            candidates = [a for a in adapters if a.name == selection]
        else:
            candidates = [a for a in adapters if a.flags & 2] or adapters
        handles, errors = [], []
        try:
            for adapter in candidates[:8]:
                try:
                    handles.append(self.open(adapter))
                except CaptureError as exc:
                    errors.append(str(exc))
            if not handles:
                raise CaptureError(errors[0] if errors else "没有可用网卡，请连接网络后重试")
            while not stop_event.is_set():
                activity = False
                for handle, linktype in handles:
                    for _ in range(64):
                        header, data = C.POINTER(PacketHeader)(), C.POINTER(C.c_ubyte)()
                        result = self.lib.pcap_next_ex(handle, C.byref(header), C.byref(data))
                        if result == 0:
                            break
                        if result < 0:
                            raise CaptureError("网卡读取已中断，请重新选择网卡")
                        if 0 < header.contents.caplen <= 65535:
                            engine.feed(C.string_at(data, header.contents.caplen), linktype)
                            activity = True
                        if stop_event.is_set():
                            break
                engine.tick()
                if not activity:
                    stop_event.wait(0.02)
        finally:
            for handle, _ in handles:
                self.lib.pcap_close(handle)
            engine.clear()


def read_capture(path):
    """Bounded classic PCAP + PCAPNG reader for user-selected offline files."""
    with open(path, "rb") as f:
        magic = f.read(4)
        formats = {b"\xd4\xc3\xb2\xa1": ("<", 1e6), b"\xa1\xb2\xc3\xd4": (">", 1e6),
                   b"\x4d\x3c\xb2\xa1": ("<", 1e9), b"\xa1\xb2\x3c\x4d": (">", 1e9)}
        if magic in formats:
            endian, units = formats[magic]
            rest = f.read(20)
            if len(rest) != 20:
                raise CaptureError("PCAP 文件头不完整")
            linktype = struct.unpack(endian + "HHIIII", rest)[-1] & 0xFFFF
            while header := f.read(16):
                if len(header) != 16:
                    raise CaptureError("PCAP 文件被截断")
                sec, sub, length, _ = struct.unpack(endian + "IIII", header)
                if length > 1024 * 1024:
                    raise CaptureError("单个数据包过大")
                raw = f.read(length)
                if len(raw) != length:
                    raise CaptureError("PCAP 文件被截断")
                yield sec + sub / units, linktype, raw
        elif magic == b"\x0a\x0d\x0d\x0a":
            f.seek(0)
            endian, interfaces = "<", []
            while header := f.read(8):
                if len(header) != 8:
                    raise CaptureError("PCAPNG 文件被截断")
                if header[:4] == b"\x0a\x0d\x0d\x0a":
                    bom = f.read(4)
                    if bom not in (b"\x4d\x3c\x2b\x1a", b"\x1a\x2b\x3c\x4d"):
                        raise CaptureError("PCAPNG 字节顺序不支持")
                    endian = "<" if bom == b"\x4d\x3c\x2b\x1a" else ">"
                    kind, size = struct.unpack(endian + "II", header)
                    interfaces = []
                    prefix = bom
                else:
                    kind, size = struct.unpack(endian + "II", header)
                    prefix = b""
                if size < 12 + len(prefix) or size > 16 * 1024 * 1024 or size % 4:
                    raise CaptureError("PCAPNG 块长度异常")
                block = prefix + f.read(size - 8 - len(prefix))
                if len(block) != size - 8 or struct.unpack(endian + "I", block[-4:])[0] != size:
                    raise CaptureError("PCAPNG 文件不完整")
                if kind == 1:
                    if len(block) < 12:
                        raise CaptureError("PCAPNG 网卡块异常")
                    linktype, _, _ = struct.unpack_from(endian + "HHI", block)
                    units = 1e6
                    pos = 8
                    while pos + 4 <= len(block) - 4:
                        code, length = struct.unpack_from(endian + "HH", block, pos)
                        pos += 4
                        if pos + length > len(block) - 4:
                            raise CaptureError("PCAPNG 选项不完整")
                        if code == 9 and length == 1:
                            value = block[pos]
                            units = 2 ** (value & 127) if value & 128 else 10 ** value
                        pos += (length + 3) & ~3
                        if code == 0: break
                    interfaces.append((linktype, units))
                elif kind == 6:
                    if len(block) < 24:
                        raise CaptureError("PCAPNG 数据块不完整")
                    interface, high, low, length, _ = struct.unpack_from(endian + "IIIII", block)
                    if interface >= len(interfaces) or length > 1024 * 1024 or 20 + length > len(block) - 4:
                        raise CaptureError("PCAPNG 数据长度异常")
                    linktype, units = interfaces[interface]
                    yield ((high << 32) | low) / units, linktype, block[20:20 + length]
        else:
            raise CaptureError("请选择 PCAP 或 PCAPNG 文件")
