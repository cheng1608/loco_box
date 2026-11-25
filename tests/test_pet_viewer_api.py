"""HTTP contracts for the viewer without a game, driver, or external resources."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI

from backend.api import pet_viewer, routes
from backend.features import FeatureContext
from backend.features.pet_viewer import PetViewerFeature
from backend.pet_viewer.capture import CaptureError
from backend.pet_viewer.model import BattleState
from backend.pet_viewer.resources import load_resources
from test_pet_viewer import FLOW, enter, resources


class PetViewerApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        assets = resources(root / "resources")
        config = Mock()
        config.get.return_value = {}
        self.feature = PetViewerFeature(FeatureContext(Mock(), Mock(), config), assets, root / "history.sqlite3")
        self.addCleanup(self.feature.stop)
        patched = patch.object(pet_viewer.state, "features", {"pet_viewer": self.feature})
        patched.start()
        self.addCleanup(patched.stop)
        patched_config = patch.object(pet_viewer.state, "config", config)
        patched_config.start()
        self.addCleanup(patched_config.stop)
        self.app = FastAPI()
        self.app.include_router(pet_viewer.router)
        self.app.include_router(routes.router)

    async def request(self, method, path, body=None):
        content = json.dumps(body).encode("utf-8") if body is not None else b""
        route, _, query = path.partition("?")
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "scheme": "http", "path": route, "raw_path": route.encode(), "query_string": query.encode(),
                 "root_path": "", "headers": [(b"content-type", b"application/json")],
                 "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 80)}
        events = []
        async def receive():
            return {"type": "http.request", "body": content, "more_body": False}
        async def send(event):
            events.append(event)
        await self.app(scope, receive, send)
        status = next(e["status"] for e in events if e["type"] == "http.response.start")
        result = b"".join(e.get("body", b"") for e in events if e["type"] == "http.response.body")
        return status, json.loads(result)

    async def test_state_and_missing_driver_are_actionable(self):
        self.feature._capture_factory = Mock(side_effect=CaptureError("未安装 Npcap"))
        status, state = await self.request("GET", "/api/pet-viewer/state")
        self.assertEqual(status, 200)
        self.assertTrue(state["resources"]["ready"])
        self.assertEqual(state["pets"], [])
        self.assertIn("session_id", state)
        status, adapters = await self.request("GET", "/api/pet-viewer/adapters")
        self.assertEqual(status, 200)
        self.assertFalse(adapters["available"])
        status, error = await self.request("POST", "/api/features/pet_viewer/start")
        self.assertEqual(status, 400)
        self.assertIn("Npcap", error["detail"])
        status, _ = await self.request("POST", "/api/features/pet_viewer/stop")
        self.assertEqual(status, 200)

    async def test_selection_preserves_large_identifiers_and_pagination_is_bounded(self):
        _, catalog, _ = load_resources(self.feature.resource_dir)
        model = BattleState(catalog)
        ident = 2**63 + 1
        model.handle(FLOW, 4886, enter({"nature": 2}, ident=ident))
        self.feature._model = model
        self.feature._accept_snapshot(self.feature._generation, model.snapshot())
        status, selected = await self.request("POST", "/api/pet-viewer/select", {"pet_id": str(ident)})
        self.assertEqual(status, 200)
        self.assertEqual(selected["selected"]["id"], str(ident))
        status, _ = await self.request("POST", "/api/pet-viewer/select", {"pet_id": "404"})
        self.assertEqual(status, 400)
        status, history = await self.request("GET", "/api/pet-viewer/history?limit=1&offset=0")
        self.assertEqual(status, 200)
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["items"][0]["nature"], "固执")
        status, _ = await self.request("GET", "/api/pet-viewer/history?limit=100000")
        self.assertEqual(status, 422)

    async def test_missing_resources_leave_api_available(self):
        self.feature.resource_dir = Path(self.temp.name) / "missing"
        status, state = await self.request("GET", "/api/pet-viewer/state")
        self.assertEqual(status, 200)
        self.assertFalse(state["resources"]["ready"])
        status, error = await self.request("POST", "/api/pet-viewer/demo")
        self.assertEqual(status, 400)
        self.assertIn("资源", error["detail"])
