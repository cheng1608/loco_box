# Adapted from Evenstar-tools/roco-pve-viewer @ 287d335 (MIT).
# Copyright (c) 2026 Evenstar-tools. See LICENSE.upstream.
"""Read-only transport decoding. No capture injection, sockets, or key persistence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import struct
import time

from Crypto.Cipher import AES
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

OPCODES = {
    4886: "Next.ZoneBattleEnterNotify",
    4890: "Next.ZoneBattleRoundStartNotify",
    4900: "Next.ZoneBattlePerformStartNotify",
    4908: "Next.ZoneBattleFinishNotify",
}
MAX_STREAM = 8 * 1024 * 1024
# all.pb: dataconfig.BattleMode.BM_PVE_INTERACT = 1 (NORMAL = 5, PK = 6).
WILD_PVE_MODE = 1

# A separate protobuf schema skips every pet-attribute field before admission.
# Field numbers/types come from all.pb, rather than a second wire-format parser.
ROUTING_FIELDS = {
    "ZoneBattleEnterNotify": ("battle_mode", "init_info"),
    "BattleInitInfo": ("battle_id", "enemy_team"),
    "BattleRoleInfo": ("pets",),
    "BattlePetInfo": ("battle_inside_pet_info",),
    "BattleInsidePetInfo": ("is_player_enemy",),
    "ZoneBattleRoundStartNotify": ("state_info", "perform_cmd"),
    "BattleStateInfo": ("battle_id", "enemy_team"),
    "ZoneBattlePerformStartNotify": ("perform_cmd", "settle_info"),
    "BattlePerformCmd": ("seq_num", "perform_info"),
    "BattlePerformInfo": ("sync_data", "data_update", "star_transform", "star_shield_break", "dice_shield_break", "dice_mutate"),
    "BattleSyncData": ("pet_info",),
    "BattleDataUpdate": ("pet", "battler", "other"),
    "BattleOtherRoleInfo": ("pets",),
    "BattleStarTransform": ("pet_info",),
    "BattleStarShieldBreak": ("pet_info",),
    "BattleDiceShieldBreak": ("pet_info",),
    "BattleDiceMutate": ("pet_info",),
    "BattleRoundSettleInfo": ("battle_id",),
    "ZoneBattleFinishNotify": ("settle_info",),
    "BattleSettleInfo": ("battle_id", "real_pve", "real_pvp"),
}


def delta(a, b):
    return ((a - b + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)


def message_dict(msg):
    """Preserve proto2 presence, including present zero values."""
    out = {}
    for f, value in msg.ListFields():
        def convert(v):
            if f.type == f.TYPE_MESSAGE:
                return message_dict(v)
            if f.type == f.TYPE_BYTES:
                return v.decode("utf-8", errors="replace")
            return int(v) if f.type == f.TYPE_ENUM else v
        out[f.name] = [convert(v) for v in value] if f.is_repeated else convert(value)
    return out


class Decoder:
    def __init__(self, descriptor: Path):
        self.pool = descriptor_pool.DescriptorPool()
        self.pool.AddSerializedFile(descriptor_pb2.DESCRIPTOR.serialized_pb)
        pending = list(descriptor_pb2.FileDescriptorSet.FromString(descriptor.read_bytes()).file)
        while pending:
            rest = []
            for item in pending:
                try:
                    self.pool.AddSerializedFile(item.SerializeToString())
                except TypeError:
                    rest.append(item)
            if len(rest) == len(pending):
                raise ValueError("协议描述符依赖不完整")
            pending = rest
        self.classes = {op: message_factory.GetMessageClass(self.pool.FindMessageTypeByName(name))
                        for op, name in OPCODES.items()}
        routing = descriptor_pb2.FileDescriptorProto(name="wild_pve_routing.proto", package="pve_routing", syntax="proto2")
        for name, fields in ROUTING_FIELDS.items():
            original = self.pool.FindMessageTypeByName("Next." + name)
            target = routing.message_type.add(name=name)
            for field_name in fields:
                source = original.fields_by_name[field_name]
                field = target.field.add(name=source.name, number=source.number, type=source.type,
                                         label=3 if source.is_repeated else 1)
                if source.message_type is not None:
                    field.type_name = ".pve_routing." + source.message_type.name
        routing_pool = descriptor_pool.DescriptorPool()
        routing_pool.AddSerializedFile(routing.SerializeToString())
        self.routing_classes = {op: message_factory.GetMessageClass(
            routing_pool.FindMessageTypeByName("pve_routing." + name.rsplit(".", 1)[1]))
            for op, name in OPCODES.items()}

    def decode(self, opcode, body):
        return self._parse(self.classes, opcode, body)

    def route(self, opcode, body):
        """Read battle eligibility only; PetData is absent from this schema."""
        return self._parse(self.routing_classes, opcode, body, discard_unknown=True)

    @staticmethod
    def _parse(classes, opcode, body, discard_unknown=False):
        if opcode not in classes:
            return None
        # The observed tsf4g trailer includes a total padding length byte.
        if len(body) >= 6 and body[-6:-1] == b"tsf4g":
            pad = body[-1]
            if not 6 <= pad <= min(64, len(body)):
                raise ValueError("协议尾部异常")
            body = body[:-pad]
        msg = classes[opcode]()
        msg.ParseFromString(body)
        if discard_unknown:
            msg.DiscardUnknownFields()
        return message_dict(msg)

    def encode_fixture(self, opcode, data):
        """Used only by synthetic offline fixtures/tests."""
        from google.protobuf.json_format import ParseDict
        msg = self.classes[opcode]()
        ParseDict(data, msg)
        return msg.SerializeToString()


@dataclass
class Segment:
    flow: tuple
    sequence: int
    flags: int
    payload: bytes


def tcp_segment(packet: bytes, linktype: int) -> Optional[Segment]:
    """Only server -> client TCP/8195. Fragmented IP datagrams are rejected."""
    if linktype == 1:
        if len(packet) < 14:
            return None
        kind, offset = struct.unpack_from("!H", packet, 12)[0], 14
        while kind in (0x8100, 0x88A8):
            if len(packet) < offset + 4:
                return None
            kind = struct.unpack_from("!H", packet, offset + 2)[0]
            offset += 4
        if kind not in (0x0800, 0x86DD):
            return None
    elif linktype in (0, 108):
        offset = 4
    elif linktype == 113:
        offset = 16
    elif linktype in (12, 101, 228, 229):
        offset = 0
    else:
        return None
    ip = packet[offset:]
    if not ip:
        return None
    version = ip[0] >> 4
    if version == 4:
        if len(ip) < 20 or ip[9] != 6:
            return None
        head = (ip[0] & 15) * 4
        total = struct.unpack_from("!H", ip, 2)[0]
        if head < 20 or total < head or total > len(ip) or struct.unpack_from("!H", ip, 6)[0] & 0x3FFF:
            return None
        src, dst, tcp = ip[12:16], ip[16:20], ip[head:total]
    elif version == 6:
        if len(ip) < 40:
            return None
        total = 40 + struct.unpack_from("!H", ip, 4)[0]
        if total > len(ip):
            return None
        nxt, pos = ip[6], 40
        while nxt in (0, 43, 60, 51):
            if pos + 2 > total:
                return None
            length = (ip[pos + 1] + 2) * 4 if nxt == 51 else (ip[pos + 1] + 1) * 8
            nxt, pos = ip[pos], pos + length
        if nxt != 6 or pos > total:
            return None
        src, dst, tcp = ip[8:24], ip[24:40], ip[pos:total]
    else:
        return None
    if len(tcp) < 20:
        return None
    sport, dport, seq = struct.unpack_from("!HHI", tcp)
    head = (tcp[12] >> 4) * 4
    if sport != 8195 or head < 20 or head > len(tcp):
        return None
    return Segment((src, sport, dst, dport), seq, tcp[13], tcp[head:])


class Stream:
    def __init__(self):
        self.next_seq = None
        self.pending = {}
        self.buffer = bytearray()
        self.key = None
        self.last_seen = time.monotonic()
        self.gap_since = None
        self.last_gcp_seq = None
        self.clear_battle()

    def clear_battle(self):
        self.battle_id = None
        self.battle_active = False
        self.perform_sequence = None

    def clear(self):
        self.key = None
        self.buffer.clear()
        self.pending.clear()
        self.clear_battle()

    def push(self, seq, payload, now):
        if self.next_seq is None:
            self.next_seq = seq
        behind = -delta(seq, self.next_seq)
        if behind > 0:
            if behind >= len(payload):
                return
            payload, seq = payload[behind:], self.next_seq
        if not payload:
            return
        if delta(seq, self.next_seq) > 0:
            if len(payload) > len(self.pending.get(seq, b"")):
                self.pending[seq] = payload
            self.gap_since = self.gap_since or now
            if len(self.pending) > 256 or sum(map(len, self.pending.values())) > MAX_STREAM:
                raise ValueError("重组缓冲超限")
            return
        self.buffer.extend(payload)
        self.next_seq = (seq + len(payload)) & 0xFFFFFFFF
        while self.pending:
            start = min(self.pending, key=lambda v: delta(v, self.next_seq))
            distance = delta(start, self.next_seq)
            if distance > 0:
                break
            part = self.pending.pop(start)
            overlap = -distance
            if overlap < len(part):
                part = part[overlap:]
                self.buffer.extend(part)
                self.next_seq = (self.next_seq + len(part)) & 0xFFFFFFFF
        if not self.pending:
            self.gap_since = None
        if len(self.buffer) > MAX_STREAM:
            raise ValueError("协议缓冲超限")

    def frames(self):
        while len(self.buffer) >= 21:
            if self.buffer[:2] != b"\x33\x66":
                at = self.buffer.find(b"\x33\x66", 1)
                if at < 0:
                    keep = self.buffer[-1:] if self.buffer[-1] == 0x33 else b""
                    self.buffer[:] = keep
                    return
                del self.buffer[:at]
            if len(self.buffer) < 21:
                return
            command = struct.unpack_from("!H", self.buffer, 6)[0]
            seq, head, body = struct.unpack_from("!III", self.buffer, 9)
            if head < 21 or head + body > MAX_STREAM:
                del self.buffer[:2]
                continue
            if len(self.buffer) < head + body:
                return
            extra, content = bytes(self.buffer[21:head]), bytes(self.buffer[head:head + body])
            del self.buffer[:head + body]
            yield command, seq, extra, content


def decrypt(key, body):
    if len(body) < 16 or len(body) % 16:
        raise ValueError("加密数据长度异常")
    variants = [(body[:16], body[16:])] if len(body) >= 32 else []
    variants.append((bytes(16), body))
    for iv, ciphertext in variants:
        plain = AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext)
        if len(plain) >= 10 and plain[4:6] == b"\x55\xaa":
            # Older internal envelope, accepted only when its explicit markers match.
            if len(plain) >= 30 and plain[24:26] == b"\x39\x63" and plain[10:12] == b"\x00\x00" and int.from_bytes(plain[12:16], "big") in (0, 1):
                pad = plain[-1] if plain[-6:-1] == b"tsf4g" else 0
                if pad and not 6 <= pad <= min(64, len(plain) - 30):
                    raise ValueError("协议尾部异常")
                if int.from_bytes(plain[6:10], "big") != len(plain) - pad - 4:
                    raise ValueError("协议记录长度异常")
                return int.from_bytes(plain[16:20], "big") & 0xFFFF, plain[30:]
            if plain[:2] == b"\x00\x00":
                return struct.unpack_from("!H", plain, 2)[0], plain[10:]
    raise ValueError("解码校验失败")


class Engine:
    def __init__(self, decoder, on_message, on_event):
        self.decoder, self.on_message, self.on_event = decoder, on_message, on_event
        self.streams = {}
        self.packet_count = 0
        self.decoded_count = 0

    def clear(self):
        for stream in self.streams.values():
            stream.clear()
        self.streams.clear()

    @staticmethod
    def _has_player_enemy(value):
        if isinstance(value, dict):
            return value.get("is_player_enemy") is True or any(
                Engine._has_player_enemy(item) for item in value.values())
        return isinstance(value, list) and any(Engine._has_player_enemy(item) for item in value)

    def _allow_attributes(self, stream, flow, opcode, payload):
        if opcode != 4886 and stream.battle_id is None:
            return False
        if opcode == 4886:
            # Only the newest encounter may admit attributes, even when a game
            # reconnect leaves a previous TCP connection alive.
            for previous in self.streams.values():
                previous.clear_battle()
        try:
            route = self.decoder.route(opcode, payload)
        except Exception:
            if opcode == 4886:
                self.on_message(flow, opcode, {})
            raise
        if opcode == 4886:
            battle_id = route.get("init_info", {}).get("battle_id")
            if route.get("battle_mode") == WILD_PVE_MODE and battle_id and not self._has_player_enemy(route):
                stream.battle_id, stream.battle_active = battle_id, True
                return True
            # The model must clear the previous encounter even though attributes
            # from this rejected entry were never decoded.
            self.on_message(flow, opcode, route)
            return False

        settle = route.get("settle_info", {})
        for info in (route.get("state_info", {}), settle):
            if "battle_id" in info and info["battle_id"] != stream.battle_id:
                return False
        if opcode == 4908 and settle.get("battle_id") != stream.battle_id:
            return False
        sequence = route.get("perform_cmd", {}).get("seq_num")
        if sequence is not None:
            if stream.perform_sequence is not None and delta(sequence, stream.perform_sequence) <= 0:
                return False
            stream.perform_sequence = sequence
        if self._has_player_enemy(route) or (opcode == 4908 and (
                settle.get("real_pvp", 0) != 0 or settle.get("real_pve", WILD_PVE_MODE) != WILD_PVE_MODE)):
            stream.clear_battle()
            self.on_event("pvp_blocked", flow)
            return False
        # An ended battle retains just enough identity/sequence to revoke stale
        # results if a late player marker arrives, without decoding attributes.
        if not stream.battle_active:
            return False
        if opcode == 4908:
            stream.battle_active = False
        return True

    def feed(self, raw, linktype, now=None):
        now = time.monotonic() if now is None else now
        seg = tcp_segment(raw, linktype)
        if seg is None:
            return
        self.packet_count += 1
        if seg.flags & 2 and seg.flow in self.streams:
            self.streams.pop(seg.flow).clear()
            self.on_event("reconnect", seg.flow)
        if seg.flow not in self.streams:
            if len(self.streams) >= 16:
                oldest = min(self.streams, key=lambda k: self.streams[k].last_seen)
                self.streams.pop(oldest).clear()
                self.on_event("closed", oldest)
            self.streams[seg.flow] = Stream()
            self.on_event("traffic", seg.flow)
        stream = self.streams[seg.flow]
        stream.last_seen = now
        self.on_event("activity", seg.flow)
        try:
            stream.push((seg.sequence + bool(seg.flags & 2)) & 0xFFFFFFFF, seg.payload, now)
            for command, seq, extra, body in stream.frames():
                if command == 0x1002 and len(extra) >= 18:
                    stream.key = extra[2:18]
                    stream.last_gcp_seq = None
                    stream.clear_battle()
                    self.on_event("ready", seg.flow)
                elif command == 0x5002:
                    stream.clear()
                    self.on_event("closed", seg.flow)
                elif command == 0x4013:
                    if stream.key is None:
                        stream.clear_battle()
                        self.on_event("missing_key", seg.flow)
                        continue
                    if stream.last_gcp_seq is not None and delta(seq, stream.last_gcp_seq) <= 0:
                        continue
                    opcode, payload = decrypt(stream.key, body)
                    stream.last_gcp_seq = seq
                    if opcode not in OPCODES:
                        if opcode == 0x132D:
                            stream.battle_active = False
                            self.on_event("battle_closed", seg.flow)
                        continue
                    if not self._allow_attributes(stream, seg.flow, opcode, payload):
                        continue
                    try:
                        data = self.decoder.decode(opcode, payload)
                    except Exception:
                        if opcode == 4886:
                            self.on_message(seg.flow, opcode, {})
                        raise
                    self.decoded_count += 1
                    self.on_message(seg.flow, opcode, data)
        except (ValueError, struct.error) as exc:
            stream.clear_battle()
            stream.buffer.clear()
            stream.pending.clear()
            stream.next_seq = None
            stream.gap_since = None
            self.on_event("decode_error", seg.flow)
        except Exception:
            # Protobuf errors never escape with packet content in the UI/log.
            stream.clear_battle()
            self.on_event("schema_error", seg.flow)
        if seg.flags & 5:
            stream.clear()
            self.streams.pop(seg.flow, None)
            self.on_event("closed", seg.flow)

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        for flow, stream in list(self.streams.items()):
            if now - stream.last_seen > 60:
                self.streams.pop(flow).clear()
                self.on_event("closed", flow)
            elif stream.gap_since is not None and now - stream.gap_since > 2:
                stream.clear_battle()
                stream.pending.clear()
                stream.buffer.clear()
                stream.next_seq = None
                stream.gap_since = None
                self.on_event("gap", flow)
