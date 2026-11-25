# Adapted from Evenstar-tools/roco-pve-viewer @ 287d335 (MIT).
# Copyright (c) 2026 Evenstar-tools. See LICENSE.upstream.
"""Local history of displayed wild-PVE attributes; never stores packet data."""
from __future__ import annotations
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3


VIEW_FIELDS = ("name", "voice", "voice_hint", "voice_tip", "weight", "weight_hint", "weight_tip",
               "nature", "nature_hint", "nature_tip", "nature_up", "nature_down", "medal",
               "nature_id", "nature_rule", "nature_modified", "nature_effective", "nature_pos_raw", "nature_neg_raw", "nature_change_way",
               "shiny", "fantastic", "shiny_hint", "base_id", "weight_raw", "weight_low", "weight_high",
               "height", "height_hint", "height_tip", "height_raw", "height_low", "height_high", "shape_rule",
               "blood_id", "bloodline", "bloodline_label", "bloodline_tip", "bloodline_source", "bloodline_rule")


class HistoryError(Exception):
    pass


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path)
        self.cleared_keys = set()
        self.revoked_battles = set()
        self.pending_deletions = set()

    def connect(self, timeout=1):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=timeout)
        try:
            connection.row_factory = sqlite3.Row
            # The in-memory veto applies immediately, even if another writer
            # currently prevents removing a newly identified player encounter.
            connection.create_function("viewer_history_visible", 1,
                                       lambda battle_id: battle_id not in self.revoked_battles)
            connection.execute("""CREATE TABLE IF NOT EXISTS encounters (
                battle_id TEXT NOT NULL, pet_id TEXT NOT NULL, seen_at TEXT NOT NULL,
                details TEXT NOT NULL, PRIMARY KEY (battle_id, pet_id))""")
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    @property
    def pending_error(self):
        return "已隐藏被阻断战斗，历史清理待存储恢复后重试" if self.pending_deletions else ""

    def retry_pending(self):
        if not self.pending_deletions:
            return False
        if not self.path.exists():
            self.pending_deletions.clear()
            return False
        pending = set(self.pending_deletions)
        try:
            # Polling/duplicate packets should never block capture for a second
            # each time an unrelated SQLite writer holds its transaction open.
            with closing(self.connect(timeout=0.05)) as connection, connection:
                changed = False
                for battle_id in pending:
                    cursor = connection.execute("DELETE FROM encounters WHERE battle_id = ?", (battle_id,))
                    changed = bool(cursor.rowcount) or changed
            # Only acknowledge after COMMIT has succeeded.
            self.pending_deletions.difference_update(pending)
            return changed
        except (OSError, sqlite3.Error) as exc:
            raise HistoryError(self.pending_error) from exc

    def record(self, snapshot):
        """None: ineligible; False: unchanged; True: new or updated rows."""
        if snapshot.get("source") == "实时" and snapshot.get("phase") == "blocked":
            battle_id = snapshot.get("blocked_battle_id")
            if battle_id:
                self.revoked_battles.add(str(battle_id))
                self.pending_deletions.add(str(battle_id))
            return self.retry_pending()
        had_pending = bool(self.pending_deletions)
        removed = self.retry_pending()
        if (snapshot.get("source") != "实时" or snapshot.get("phase") not in ("active", "ended")
                or not snapshot.get("battle_id") or not snapshot.get("pets")):
            return removed if had_pending else None
        if str(snapshot["battle_id"]) in self.revoked_battles:
            return removed
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        changed = False
        try:
            with closing(self.connect()) as connection, connection:
                for pet in snapshot["pets"]:
                    if not pet.get("id"):
                        continue
                    key = (str(snapshot["battle_id"]), str(pet["id"]))
                    if key in self.cleared_keys:
                        continue
                    details = json.dumps({key: pet.get(key) for key in VIEW_FIELDS}, ensure_ascii=False)
                    cursor = connection.execute("""INSERT INTO encounters VALUES (?, ?, ?, ?)
                        ON CONFLICT (battle_id, pet_id) DO UPDATE SET details = excluded.details
                        WHERE encounters.details != excluded.details""",
                        (*key, stamp, details))
                    changed = bool(cursor.rowcount) or changed
            return changed
        except (OSError, sqlite3.Error) as exc:
            raise HistoryError("历史记录未保存，请检查本机存储空间和文件权限；实时读取仍可继续。") from exc

    def entries(self):
        if not self.path.exists():
            return []
        try:
            self.retry_pending()
        except HistoryError:
            pass  # The read filter still hides every revoked encounter.
        try:
            with closing(self.connect()) as connection:
                rows = connection.execute("SELECT rowid, seen_at, details FROM encounters "
                                          "WHERE viewer_history_visible(battle_id) ORDER BY rowid DESC")
                return [{"key": row["rowid"], "seen_at": row["seen_at"], **json.loads(row["details"])} for row in rows]
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            raise HistoryError("历史记录暂时无法打开，请检查本机存储空间和文件权限。") from exc

    def page(self, limit=50, offset=0):
        if not self.path.exists():
            return {"items": [], "total": 0}
        try:
            self.retry_pending()
        except HistoryError:
            pass
        try:
            with closing(self.connect()) as connection:
                total = connection.execute("SELECT COUNT(*) FROM encounters WHERE viewer_history_visible(battle_id)").fetchone()[0]
                rows = connection.execute(
                    "SELECT rowid, seen_at, details FROM encounters WHERE viewer_history_visible(battle_id) "
                    "ORDER BY rowid DESC LIMIT ? OFFSET ?",
                    (limit, offset))
                items = [{"key": row["rowid"], "seen_at": row["seen_at"], **json.loads(row["details"])} for row in rows]
                return {"items": items, "total": total}
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            raise HistoryError("历史记录暂时无法打开，请检查本机存储空间和文件权限。") from exc

    def clear(self):
        if not self.path.exists():
            return
        try:
            with closing(self.connect()) as connection, connection:
                keys = {(row[0], row[1]) for row in connection.execute("SELECT battle_id, pet_id FROM encounters")}
                connection.execute("DELETE FROM encounters")
            # Later packets from a just-cleared encounter must not bring it back.
            self.cleared_keys.update(keys)
            self.pending_deletions.clear()
        except (OSError, sqlite3.Error) as exc:
            raise HistoryError("历史记录未能清空，请稍后重试。") from exc
