"""HTTP contract tests against ASGI without a hardware device or httpx dependency."""

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest.mock import Mock, patch

from fastapi import FastAPI

from backend.api import music
from backend.features import FeatureContext
from backend.features.music import MusicFeature
from backend.music.library import MAX_FILE_BYTES, MusicLibrary
from test_music_domain import one_note
from test_music_player import FakeConfig, FakeController


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        path = Path(self.temporary.name)
        self.controller = FakeController()
        self.library = MusicLibrary(path / "music", path / "scores")
        self.feature = MusicFeature(FeatureContext(self.controller, Mock(), FakeConfig()), self.library)
        self.feature.COUNTDOWN_SECS = 30
        self.addCleanup(self.feature.stop)
        self.state_patch = patch.object(music.state, "features", {"music": self.feature})
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.app = FastAPI()
        self.app.include_router(music.router)

    async def request(self, method, path, body=None, content=None, extra_headers=()):
        if body is not None:
            content = json.dumps(body).encode("utf-8")
            headers = [(b"content-type", b"application/json")]
        else:
            content = content or b""
            headers = [(b"content-type", b"application/octet-stream")]
        headers += list(extra_headers)
        route, _, query = path.partition("?")
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": method, "scheme": "http", "path": route, "raw_path": route.encode(),
                 "query_string": query.encode(), "root_path": "", "headers": headers,
                 "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 80)}
        sent = []

        async def receive():
            return {"type": "http.request", "body": content, "more_body": False}

        async def send(event):
            sent.append(event)

        await self.app(scope, receive, send)
        status = next(e["status"] for e in sent if e["type"] == "http.response.start")
        data = b"".join(e.get("body", b"") for e in sent if e["type"] == "http.response.body")
        return status, json.loads(data)

    async def test_raw_import_detail_settings_and_duplicate_roundtrip(self):
        status, imported = await self.request("POST", "/api/music/import?filename=" + quote("歌曲.mid"), content=one_note())
        self.assertEqual(status, 200)
        self.assertFalse(imported["duplicate"])
        ident = imported["song"]["id"]
        status, duplicate = await self.request("POST", "/api/music/import?filename=renamed.mid", content=one_note())
        self.assertTrue(duplicate["duplicate"])
        status, listing = await self.request("GET", "/api/music/library")
        self.assertEqual(len(listing["songs"]), 1)
        status, detail = await self.request("GET", "/api/music/songs/" + ident)
        self.assertEqual(status, 200)
        self.assertEqual(set(detail), {"song", "tracks", "settings", "analysis"})
        self.assertEqual(detail["settings"]["conflict_policy"], "adapt")
        self.assertEqual(detail["settings"]["range_policy"], "degree")
        status, changed = await self.request("PUT", "/api/music/songs/" + ident + "/settings", {"speed": 1.5})
        self.assertEqual(status, 200)
        self.assertEqual(changed["settings"]["speed"], 1.5)
        status, _ = await self.request("PUT", "/api/music/songs/" + ident + "/settings", {"selected_tracks": [99]})
        self.assertEqual(status, 200)
        self.assertTrue(changed["analysis"]["can_play"])

    async def test_control_contract_full_state_and_busy_error(self):
        ident = self.library.import_file("song.mid", one_note())["song"]["id"]
        status, selected = await self.request("POST", "/api/music/select", {"song_id": ident})
        self.assertEqual(status, 200)
        self.assertEqual(selected["selected_song_id"], ident)
        self.controller.owner = "throw"
        status, error = await self.request("POST", "/api/music/play", {"song_id": ident})
        self.assertEqual(status, 409)
        self.assertIn("detail", error)
        self.controller.owner = None
        status, playing = await self.request("POST", "/api/music/play", {"song_id": ident})
        self.assertEqual(status, 200)
        self.assertIn(playing["phase"], ("preparing", "countdown"))
        for action in ("pause", "resume", "stop"):
            status, snapshot = await self.request("POST", "/api/music/" + action)
            self.assertEqual(status, 200)
            self.assertIn("position_ms", snapshot)
            self.assertIn("device", snapshot)
        self.assertEqual(snapshot["phase"], "stopped")

    async def test_upload_validation_limit_and_missing_songs(self):
        status, _ = await self.request("POST", "/api/music/import?filename=bad.mid", content=b"bad")
        self.assertEqual(status, 400)
        status, _ = await self.request("POST", "/api/music/import?filename=huge.mid", content=b"x",
                                       extra_headers=[(b"content-length", str(MAX_FILE_BYTES + 1).encode())])
        self.assertEqual(status, 413)
        status, _ = await self.request("GET", "/api/music/songs/unknown")
        self.assertEqual(status, 404)

    async def test_legacy_routes_and_select_by_filename_remain_available(self):
        self.library.import_file("old.txt", b"B 50\nF 50\n")
        status, scores = await self.request("GET", "/api/music/scores")
        self.assertEqual(scores["scores"], ["old.txt"])
        status, text = await self.request("GET", "/api/music/scores/old.txt")
        self.assertEqual(text["content"], "B 50\nF 50\n")
        status, selected = await self.request("POST", "/api/music/select", {"name": "old.txt"})
        self.assertEqual(selected["current"], "old.txt")
        status, parsed = await self.request("POST", "/api/music/parse", {"score": "B 50"})
        self.assertEqual(parsed["count"], 1)

    async def test_delete_selected_and_last_song_updates_persistent_selection(self):
        first = self.library.import_file("a.mid", one_note(64))["song"]["id"]
        second = self.library.import_file("b.mid", one_note(65))["song"]["id"]
        await self.request("POST", "/api/music/select", {"song_id": first})
        status, result = await self.request("DELETE", "/api/music/songs/" + first)
        self.assertEqual(status, 200)
        self.assertEqual([song["id"] for song in result["songs"]], [second])
        self.assertEqual(result["state"]["selected_song_id"], second)
        self.assertEqual(self.feature.ctx.config.get("music")["selected_song_id"], second)
        status, _ = await self.request("GET", "/api/music/songs/" + first)
        self.assertEqual(status, 404)
        status, _ = await self.request("DELETE", "/api/music/songs/" + first)
        self.assertEqual(status, 404)
        status, result = await self.request("DELETE", "/api/music/songs/" + second)
        self.assertEqual(status, 200)
        self.assertEqual(result["songs"], [])
        self.assertEqual(result["state"]["selected_song_id"], "")
        self.assertEqual(result["state"]["current"], "")
        self.assertEqual(self.feature.ctx.config.get("music")["current"], "")

    async def test_delete_playing_song_requires_stop_other_songs_do_not(self):
        first = self.library.import_file("a.mid", one_note(64))["song"]["id"]
        second = self.library.import_file("b.mid", one_note(65))["song"]["id"]
        await self.request("POST", "/api/music/play", {"song_id": first})
        status, result = await self.request("DELETE", "/api/music/songs/" + first)
        self.assertEqual(status, 409)
        self.assertIn("停止", result["detail"])
        self.assertEqual(self.library.song(first)["id"], first)
        status, result = await self.request("DELETE", "/api/music/songs/" + second)
        self.assertEqual(status, 200)
        self.assertTrue(result["state"]["running"])
        await self.request("POST", "/api/music/stop")
        status, result = await self.request("DELETE", "/api/music/songs/" + first)
        self.assertEqual(status, 200)
        self.assertEqual(result["state"]["playing_song_id"], "")
        self.assertFalse(result["state"]["running"])

    async def test_delete_failure_returns_error_and_keeps_library_entry(self):
        ident = self.library.import_file("keep.mid", one_note())["song"]["id"]
        with patch.object(self.library, "delete", side_effect=PermissionError("file busy")):
            status, result = await self.request("DELETE", "/api/music/songs/" + ident)
        self.assertEqual(status, 500)
        self.assertIn("删除失败", result["detail"])
        self.assertEqual(self.library.song(ident)["id"], ident)


if __name__ == "__main__":
    unittest.main()
