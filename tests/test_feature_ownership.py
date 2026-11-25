"""Shared device ownership and stale feature callback regressions."""

import unittest
from unittest.mock import Mock, patch

from backend.core.arduino import DeviceBusyError
from backend.features import FeatureContext
from backend.features.box_monitor import BoxMonitorFeature
from backend.features.throw import ThrowFeature


class OwnershipTests(unittest.TestCase):
    def context(self):
        controller = Mock()
        controller.acquire.return_value = True
        controller.is_connected.return_value = True
        return FeatureContext(controller, Mock(), Mock())

    def test_throw_rejects_busy_device_without_starting_worker(self):
        context = self.context()
        context.arduino.acquire.return_value = False
        feature = ThrowFeature(context)
        with self.assertRaises(DeviceBusyError):
            feature.start({})
        self.assertFalse(feature.is_running())
        context.arduino.send.assert_not_called()
        context.arduino.release.assert_not_called()

    def test_throw_releases_device_after_connection_failure(self):
        context = self.context()
        context.arduino.is_connected.return_value = False
        context.arduino.connect.return_value = False
        feature = ThrowFeature(context)
        feature.start({})
        feature._thread.join(timeout=1)
        self.assertFalse(feature._thread.is_alive())
        context.arduino.connect.assert_called_once_with(owner="throw")
        context.arduino.release.assert_called_once_with("throw")

    def test_box_connection_uses_shared_port_selection(self):
        context = self.context()
        context.arduino.is_connected.return_value = False
        feature = BoxMonitorFeature(context)
        feature._active = True
        feature._connect_arduino(feature._generation)
        context.arduino.connect.assert_called_once_with(owner="box_monitor")

    def test_stopped_box_worker_cannot_reconnect(self):
        context = self.context()
        context.arduino.is_connected.return_value = False
        feature = BoxMonitorFeature(context)
        feature._active = True
        generation = feature._generation
        feature.stop()
        feature._connect_arduino(generation)
        context.arduino.connect.assert_not_called()

    def test_stopped_box_timer_cannot_inject_into_music(self):
        context = self.context()
        feature = BoxMonitorFeature(context)
        feature._active = True
        old_generation = feature._generation
        feature.stop()
        feature._send_key(old_generation)
        context.arduino.press_key.assert_not_called()
        context.arduino.release.assert_called_once_with("box_monitor")

    def test_old_monitor_callbacks_cannot_affect_restarted_monitor(self):
        context = self.context()
        feature = BoxMonitorFeature(context)
        config = {"template_region": {"left": 0}, "region_b": {"left": 1}}
        with patch("loco_box.image_ops.load_bgr", return_value=object()), \
                patch("loco_box.matcher.WhiteTextMatcher") as matcher, \
                patch("loco_box.monitor.MonitorThread") as monitor:
            matcher.return_value.is_valid = True
            feature.start(config)
            old = monitor.call_args.kwargs
            generation = feature._generation
            feature.start(config)
            count = feature._box_count
            old["on_box_appear"]()
            old["on_error"]("late failure")
            feature._send_key(generation)
            self.assertTrue(feature.is_running())
            self.assertEqual(feature._box_count, count)
            context.arduino.press_key.assert_not_called()
            feature.stop()


class DeviceRouteTests(unittest.TestCase):
    def test_manual_key_and_mouse_return_conflict_for_music_owner(self):
        from fastapi import HTTPException
        from backend.api import routes

        controller = Mock()
        controller.current_owner.return_value = "music"
        controller.press_key.return_value = False
        controller.send.return_value = False
        with patch.object(routes.state, "arduino", controller):
            for action, payload in ((routes.send_key, routes.KeyPayload(key="B")),
                                    (routes.send_mouse, routes.MousePayload())):
                with self.assertRaises(HTTPException) as error:
                    action(payload)
                self.assertEqual(error.exception.status_code, 409)

    def test_feature_busy_is_http_conflict(self):
        from fastapi import HTTPException
        from backend.api import routes

        feature = Mock()
        feature.default_config.return_value = {}
        feature.start.side_effect = DeviceBusyError("occupied")
        with patch.object(routes.state, "features", {"throw": feature}), \
                patch.object(routes.state.config, "get", return_value={}):
            with self.assertRaises(HTTPException) as error:
                routes.start_feature("throw")
            self.assertEqual(error.exception.status_code, 409)

    def test_disconnect_stops_workers_before_closing_device(self):
        from backend.api import routes

        order = []
        feature = Mock()
        controller = Mock()
        feature.stop.side_effect = lambda: order.append("stop")
        controller.disconnect.side_effect = lambda **kwargs: order.append("disconnect")
        with patch.object(routes.state, "features", {"music": feature}), \
                patch.object(routes.state, "arduino", controller), \
                patch.object(routes.state, "bus", Mock()):
            routes.disconnect_arduino()
        self.assertEqual(order, ["stop", "disconnect"])
        controller.disconnect.assert_called_once_with(force=True)

    def test_disconnect_keeps_independent_pet_listener_running(self):
        from backend.api import routes

        music = Mock(requires_arduino=True)
        viewer = Mock(requires_arduino=False)
        controller = Mock()
        with patch.object(routes.state, "features", {"music": music, "pet_viewer": viewer}), \
                patch.object(routes.state, "arduino", controller), \
                patch.object(routes.state, "bus", Mock()):
            routes.disconnect_arduino()
        music.stop.assert_called_once()
        viewer.stop.assert_not_called()
        controller.disconnect.assert_called_once_with(force=True)

    def test_pet_listener_does_not_block_region_selection(self):
        from backend.api import routes

        viewer = Mock(blocks_region_selection=False)
        viewer.is_running.return_value = True
        with patch.object(routes.state, "features", {"pet_viewer": viewer}), \
                patch("loco_box.region_selector.select_region",
                      side_effect=lambda selected, cancelled: cancelled()):
            self.assertEqual(routes.select_region_endpoint(), {"ok": False, "cancelled": True})

    def test_input_feature_still_blocks_region_selection(self):
        from fastapi import HTTPException
        from backend.api import routes

        feature = Mock(blocks_region_selection=True)
        feature.is_running.return_value = True
        with patch.object(routes.state, "features", {"throw": feature}), \
                patch("loco_box.region_selector.select_region") as select:
            with self.assertRaises(HTTPException) as error:
                routes.select_region_endpoint()
        self.assertEqual(error.exception.status_code, 409)
        select.assert_not_called()


if __name__ == "__main__":
    unittest.main()
