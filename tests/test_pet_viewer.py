"""Protocol, lifecycle and storage regressions using wholly synthetic encounters."""

import json
import sqlite3
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from Crypto.Cipher import AES
from google.protobuf import descriptor_pb2

from backend.features import FeatureContext
from backend.features.pet_viewer import PetViewerFeature
from backend.pet_viewer.capture import CaptureError
from backend.pet_viewer.history import HistoryStore
from backend.pet_viewer.model import BattleState
from backend.pet_viewer.protocol import Decoder, Engine
from backend.pet_viewer.resources import ResourceError, load_resources


KEY = b"0123456789abcdef"
FLOW = (b"\xc0\x00\x02\x01", 8195, b"\xc0\x00\x02\x02", 40000)


def resources(directory):
    """Minimal proto2 test schema. No game resource files are needed in CI."""
    schema = {
        "ZoneBattleEnterNotify": {"battle_mode": "u", "init_info": "BattleInitInfo"},
        "BattleInitInfo": {"battle_id": "U", "enemy_team": ["BattleRoleInfo"]},
        "BattleRoleInfo": {"pets": ["BattlePetInfo"], "base": "BattleRoleBase"},
        "BattleRoleBase": {"role_uin": "U"},
        "BattlePetInfo": {"battle_inside_pet_info": "BattleInsidePetInfo", "battle_common_pet_info": "PetData", "full_for_data_level": "b"},
        "BattleInsidePetInfo": {"is_player_enemy": "b", "pet_id": "U", "npc_obj_id": "U", "base_conf_id": "u", "conf_id": "u", "is_entered": "b"},
        "PetData": {"nature": "u", "base_conf_id": "u", "voice": "i", "height": "u", "weight": "u", "blood_id": "u",
                    "mutation_type": "u", "wear_medal_conf_id": "u", "changed_nature_pos_attr_type": "u",
                    "changed_nature_neg_attr_type": "u", "nature_attr_change_way": "u"},
        "ZoneBattleRoundStartNotify": {"state_info": "BattleStateInfo", "perform_cmd": "BattlePerformCmd"},
        "BattleStateInfo": {"battle_id": "U", "enemy_team": ["BattleRoleInfo"]},
        "ZoneBattlePerformStartNotify": {"perform_cmd": "BattlePerformCmd", "settle_info": "BattleRoundSettleInfo"},
        "BattlePerformCmd": {"seq_num": "u", "perform_info": ["BattlePerformInfo"]},
        "BattlePerformInfo": {"type": "u", "sync_data": "BattleSyncData", "data_update": "BattleDataUpdate",
                              "star_transform": "BattleStarTransform", "star_shield_break": "BattleStarShieldBreak",
                              "dice_shield_break": "BattleDiceShieldBreak", "dice_mutate": "BattleDiceMutate"},
        "BattleSyncData": {"pet_info": ["BattlePetInfo"]},
        "BattleDataUpdate": {"pet": "BattlePetInfo", "battler": "BattleRoleInfo", "other": "BattleOtherRoleInfo", "uin": "U"},
        "BattleOtherRoleInfo": {"pets": ["BattlePetInfo"], "role_uin": "U"},
        "BattleRoundSettleInfo": {"battle_id": "U"},
        "ZoneBattleFinishNotify": {"settle_info": "BattleSettleInfo"},
        "BattleSettleInfo": {"battle_id": "U", "real_pve": "u", "real_pvp": "u"},
    }
    for name in ("BattleStarTransform", "BattleStarShieldBreak", "BattleDiceShieldBreak", "BattleDiceMutate"):
        schema[name] = {"pet_info": "BattlePetInfo", "pet_id": "U", "base_conf_id": "u", "old_base_conf_id": "u", "is_shiny": "b"}
    descriptor = descriptor_pb2.FileDescriptorProto(name="synthetic_pet_viewer.proto", package="Next", syntax="proto2")
    scalar_types = {"u": 13, "U": 4, "i": 5, "b": 8}
    for name, fields in schema.items():
        message = descriptor.message_type.add(name=name)
        for number, (field_name, kind) in enumerate(fields.items(), 1):
            repeated = isinstance(kind, list)
            kind = kind[0] if repeated else kind
            field = message.field.add(name=field_name, number=number, label=3 if repeated else 1,
                                      type=scalar_types.get(kind, 11))
            if kind not in scalar_types:
                field.type_name = ".Next." + kind
    result = descriptor_pb2.FileDescriptorSet()
    result.file.add().CopyFrom(descriptor)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "all.pb").write_bytes(result.SerializeToString())
    data = {"species": {"3001": {"name": "测试精灵", "height_low": 53, "height_high": 75, "weight_low": 3620, "weight_high": 4600}},
            "natures": {"2": {"name": "固执", "positive": 80.0, "negative": 81.0},
                        "30": {"name": "踏实", "positive": 79.0, "negative": 84.0}},
            "medals": {"1001": "大块头"}}
    (directory / "gamedata.json").write_text(json.dumps(data), encoding="utf-8")
    return directory


def pet(common=None, player=False, ident=401):
    return {"battle_inside_pet_info": {"pet_id": ident, "npc_obj_id": 90001, "base_conf_id": 3001,
                                       "is_entered": True, "is_player_enemy": player},
            "battle_common_pet_info": {"base_conf_id": 3001, **(common or {})}}


def enter(common=None, mode=1, battle=70001, ident=401):
    return {"battle_mode": mode, "init_info": {"battle_id": battle,
            "enemy_team": [{"pets": [pet(common, ident=ident)]}]}}


def update(common=None, player=False, seq=1):
    return {"perform_cmd": {"seq_num": seq, "perform_info": [{"sync_data": {"pet_info": [pet(common, player)]}}]}}


def frame(command, seq, body=b"", extra=b""):
    return struct.pack("!HHHHBIII", 0x3366, 11, 11, command, 1, seq, 21 + len(extra), len(body)) + extra + body


def encrypted(decoder, opcode, message, seq=1):
    raw = decoder.encode_fixture(opcode, message)
    plain = b"\0\0" + struct.pack("!H", opcode) + b"\x55\xaa" + struct.pack("!I", seq) + raw
    pad = (-len(plain)) % 16
    if pad < 6:
        pad += 16
    plain += bytes(pad - 6) + b"tsf4g" + bytes([pad])
    iv = bytes(16)
    return frame(0x4013, seq, iv + AES.new(KEY, AES.MODE_CBC, iv).encrypt(plain))


def packet(seq, payload=b"", flags=0x18):
    tcp = struct.pack("!HHIIBBHHH", 8195, 40000, seq, 1, 0x50, flags, 65535, 0, 0) + payload
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 1, 0, 64, 6, 0, FLOW[0], FLOW[2]) + tcp
    return bytes(12) + b"\x08\x00" + ip


class Wire:
    def __init__(self, engine, decoder):
        self.engine, self.decoder, self.seq, self.command = engine, decoder, 1000, 0
        self.push(frame(0x1002, 0, extra=b"\0\0" + KEY))

    def push(self, payload, reordered=False):
        if reordered:
            self.engine.feed(packet(self.seq, payload[:10]), 1, 1)
            self.engine.feed(packet(self.seq + 37, payload[37:]), 1, 1)
            self.engine.feed(packet(self.seq + 10, payload[10:37]), 1, 1)
            self.engine.feed(packet(self.seq, payload[:10]), 1, 1)  # Duplicate.
        else:
            self.engine.feed(packet(self.seq, payload), 1, 1)
        self.seq += len(payload)

    def send(self, opcode, message, reordered=False):
        self.command += 1
        self.push(encrypted(self.decoder, opcode, message, self.command), reordered)


class PetViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = resources(self.root / "resources")
        self.decoder, self.catalog, _ = load_resources(self.assets)
        self.bus = Mock()
        self.feature = PetViewerFeature(FeatureContext(Mock(), self.bus, Mock()), self.assets, self.root / "history.sqlite3")
        self.addCleanup(self.feature.stop)

    def pipeline(self):
        model = BattleState(self.catalog)
        model.begin_capture()
        generation = self.feature._generation
        def message(flow, opcode, payload):
            model.handle(flow, opcode, payload)
            self.feature._accept_snapshot(generation, model.snapshot())
        def event(name, flow):
            model.on_event(name, flow)
            self.feature._accept_snapshot(generation, model.snapshot())
        engine = Engine(self.decoder, message, event)
        return model, engine, Wire(engine, self.decoder)

    def test_encrypted_reordered_tcp_reads_original_nature_and_presence(self):
        model, engine, wire = self.pipeline()
        wire.send(4886, enter(), reordered=True)
        self.assertEqual(model.snapshot()["selected"]["nature"], "未知")
        self.assertIsNone(model.snapshot()["selected"]["voice"])
        wire.send(4900, update({"nature": 2, "voice": 0, "changed_nature_pos_attr_type": 1,
                                "changed_nature_neg_attr_type": 6, "nature_attr_change_way": 1}))
        result = self.feature.state()["selected"]
        self.assertEqual(result["nature"], "固执")
        self.assertEqual(result["nature_effective"], "踏实")
        self.assertEqual(result["nature_hint"], "物攻↑ 魔攻↓")
        self.assertEqual(result["voice"], 50)
        self.assertEqual(engine.decoded_count, 2)
        self.assertEqual(self.feature.history()["total"], 1)

    def test_pvp_and_unknown_modes_never_decode_or_save_attributes(self):
        for mode in (0, 5, 6, 999):
            with self.subTest(mode=mode):
                model, _, wire = self.pipeline()
                with patch.object(self.decoder, "decode", wraps=self.decoder.decode) as decode:
                    wire.send(4886, enter({"nature": 2}, mode=mode))
                    wire.send(4900, update({"nature": 2}))
                    decode.assert_not_called()
                self.assertEqual(model.snapshot()["phase"], "blocked")
                self.assertIsNone(self.feature.state()["selected"])
        self.assertEqual(self.feature.history()["total"], 0)

    def test_late_player_marker_revokes_only_its_encounter(self):
        _, _, wire = self.pipeline()
        wire.send(4886, enter({"nature": 2}, battle=70001))
        wire.send(4886, enter({"nature": 2}, battle=70002))
        self.assertEqual(self.feature.history()["total"], 2)
        with patch.object(self.decoder, "decode", wraps=self.decoder.decode) as decode:
            wire.send(4900, update({"nature": 2}, player=True))
            decode.assert_not_called()
        self.assertEqual(self.feature.state()["phase"], "blocked")
        self.assertEqual(self.feature.history()["total"], 1)

    def test_revoked_history_stays_hidden_during_write_lock_and_retries(self):
        model, _, wire = self.pipeline()
        wire.send(4886, enter({"nature": 2}, battle=70001))
        wire.send(4886, enter({"nature": 30}, battle=70002))
        self.assertEqual(self.feature.history()["total"], 2)
        blocker = sqlite3.connect(self.feature._history.path)
        try:
            blocker.execute("BEGIN IMMEDIATE")
            wire.send(4900, update({"nature": 30}, player=True))
            store = self.feature._history
            self.assertEqual(store.pending_deletions, {"70002"})
            self.assertEqual(self.feature.history()["total"], 1)
            self.assertEqual(len(store.entries()), 1)
            self.assertEqual(store.entries()[0]["nature"], "固执")
            original_error = self.feature.state()["history_error"]
            self.assertTrue(original_error)
            # Even an unchanged blocked snapshot retries, without exposing rows.
            with patch.object(store, "retry_pending", wraps=store.retry_pending) as retry:
                self.feature._accept_snapshot(self.feature._generation, model.snapshot())
                retry.assert_called_once()
            # A later legitimate encounter must not clear a pending-revocation warning.
            wire.send(4886, enter({"nature": 2}, battle=70003))
            self.assertEqual(self.feature.state()["history_error"], original_error)
            self.assertEqual(self.feature.history()["total"], 1)
        finally:
            blocker.rollback()
            blocker.close()
        # A normal history read retries and commits the deferred removal.
        self.assertEqual(self.feature.history()["total"], 1)
        self.assertFalse(store.pending_deletions)
        self.assertEqual(self.feature.state()["history_error"], "")
        with sqlite3.connect(store.path) as connection:
            self.assertEqual(connection.execute("SELECT battle_id FROM encounters").fetchall(), [("70001",)])
        # Old snapshots cannot resurrect a previously revoked battle.
        stale = BattleState(self.catalog)
        stale.handle(FLOW, 4886, enter({"nature": 30}, battle=70002))
        store.record(dict(stale.snapshot(), source="实时"))
        self.assertEqual(store.page()["total"], 1)

    def test_stop_rejects_stale_callbacks_and_preserves_uint64_identifiers(self):
        model = BattleState(self.catalog)
        model.handle(FLOW, 4886, enter({"nature": 2}, battle=2**63 + 11, ident=2**63 + 31))
        old_generation = self.feature._generation
        self.feature._accept_snapshot(old_generation, model.snapshot())
        state = self.feature.state()
        self.assertEqual(state["selected"]["id"], str(2**63 + 31))
        self.assertEqual(state["battle_id"], str(2**63 + 11))
        self.feature.stop()
        calls = self.bus.publish_event.call_count
        self.assertFalse(self.feature._accept_snapshot(old_generation, model.snapshot(), force=True))
        self.assertEqual(self.bus.publish_event.call_count, calls)
        self.assertIsNone(self.feature.state()["selected"])

    def test_live_thread_stop_does_not_restore_late_result(self):
        started = threading.Event()
        completed = threading.Event()
        decoder = self.decoder
        class Capture:
            def run(self, engine, stop, selection):
                wire = Wire(engine, decoder)
                wire.send(4886, enter({"nature": 2}))
                started.set()
                stop.wait(5)
                wire.send(4900, update({"nature": 30}))
                completed.set()
        self.feature._capture_factory = Capture
        self.feature.start({"adapter": ""})
        self.assertTrue(started.wait(2))
        self.feature.stop()
        self.assertTrue(completed.wait(1))
        self.assertFalse(self.feature.is_running())
        self.assertEqual(self.feature.state()["phase"], "stopped")
        self.assertIsNone(self.feature.state()["selected"])
        self.assertEqual(self.feature.history()["items"][0]["nature"], "固执")
        self.feature.ctx.arduino.assert_not_called()

    def test_demo_is_explicit_and_does_not_write_history(self):
        frames = [frame(0x1002, 0, extra=b"\0\0" + KEY), encrypted(self.decoder, 4886, enter({"nature": 2}), 1)]
        seq, rows = 1000, []
        for index, payload in enumerate(frames):
            rows.append((index / 100, 1, packet(seq, payload)))
            seq += len(payload)
        with patch("backend.features.pet_viewer.read_capture", return_value=iter(rows)), patch.object(self.feature, "_capture_factory") as capture:
            self.feature.demo()
            thread = self.feature._thread
            if thread:
                thread.join(2)
            capture.assert_not_called()
        result = self.feature.state()
        self.assertFalse(result["running"])
        self.assertEqual(result["source"], "示例回放")
        self.assertEqual(result["selected"]["nature"], "固执")
        self.assertEqual(self.feature.history()["total"], 0)
        self.assertFalse(self.feature._history.path.exists())

    def test_missing_and_corrupt_resources_report_status_without_crashing(self):
        feature = PetViewerFeature(FeatureContext(Mock(), Mock(), Mock()), self.root / "missing", self.root / "other.sqlite3")
        self.assertFalse(feature.state()["resources"]["ready"])
        with self.assertRaises(ValueError):
            feature.start({})
        self.assertEqual(feature.state()["phase"], "error")
        (self.assets / "all.pb").write_bytes(b"not a descriptor")
        self.assertFalse(self.feature.state()["resources"]["ready"])
        with self.assertRaises(ResourceError):
            load_resources(self.assets)

    def test_integral_float_attributes_are_valid_but_invalid_values_are_rejected(self):
        self.assertTrue(load_resources(self.assets)[2]["ready"])
        path = self.assets / "gamedata.json"
        original = json.loads(path.read_text())
        for value in (True, float("nan"), float("inf"), 80.25, 0):
            with self.subTest(value=value):
                original["natures"]["2"]["positive"] = value
                path.write_text(json.dumps(original), encoding="utf-8")
                with self.assertRaises(ResourceError):
                    load_resources(self.assets)

    def test_missing_capture_driver_does_not_prevent_state_or_history(self):
        self.feature._capture_factory = Mock(side_effect=CaptureError("未安装 Npcap"))
        self.assertTrue(self.feature.state()["resources"]["ready"])
        self.assertFalse(self.feature.adapters()["available"])
        with self.assertRaisesRegex(ValueError, "Npcap"):
            self.feature.start({})
        self.assertFalse(self.feature.is_running())
        self.assertEqual(self.feature.history(), {"items": [], "total": 0})

    def test_thread_start_failure_rolls_back_and_stop_remains_safe(self):
        with patch("backend.features.pet_viewer.threading.Thread.start", side_effect=RuntimeError("cannot start")):
            with self.assertRaisesRegex(ValueError, "线程"):
                self.feature.demo()
        self.assertFalse(self.feature.is_running())
        self.assertIsNone(self.feature._thread)
        self.assertIsNone(self.feature._engine)
        self.assertIsNone(self.feature.state()["selected"])
        self.feature.stop()
        self.assertEqual(self.feature.state()["phase"], "stopped")


if __name__ == "__main__":
    unittest.main()
