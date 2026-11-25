"""Manual diagnostics must never reset between keys or touch hardware on --list."""

import contextlib
import io
import unittest
from unittest.mock import patch

from scripts import diagnose_arduino


class ArduinoDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.error = contextlib.redirect_stderr(io.StringIO())
        self.output.__enter__()
        self.error.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.addCleanup(self.error.__exit__, None, None, None)
        patcher = patch.object(diagnose_arduino, "SerialBridge")
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        self.factory.find_arduino.return_value = "COM_TEST"
        self.factory.list_ports.return_value = ["COM_TEST - Arduino"]
        self.bridge = self.factory.return_value
        self.bridge.capabilities.return_value = {"protocol": 2, "max_keys": 9}
        sleeper = patch.object(diagnose_arduino.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_list_and_help_never_connect(self):
        self.assertEqual(diagnose_arduino.main(["--list"]), 0)
        self.factory.assert_not_called()
        with self.assertRaises(SystemExit) as result:
            diagnose_arduino.main(["--help"])
        self.assertEqual(result.exception.code, 0)
        self.factory.assert_not_called()

    def test_music_and_duration_sweep_share_one_connection(self):
        self.assertEqual(diagnose_arduino.main(["--music", "--hold-ms", "50", "100"]), 0)
        self.factory.assert_called_once_with("COM_TEST")
        self.bridge.connect_and_wait.assert_called_once_with()
        self.assertEqual(self.bridge.press_key.call_count, 18)
        self.assertEqual(self.bridge.press_key.call_args_list[0].args, ("B", 50))
        self.assertEqual(self.bridge.press_key.call_args_list[-1].args, ("U", 100))
        self.bridge.panic.assert_called_once_with()
        self.bridge.disconnect.assert_called_once_with()

    def test_send_failure_or_interrupt_always_releases_connection(self):
        for outcome, expected in [(False, 1), (KeyboardInterrupt(), 130)]:
            with self.subTest(outcome=outcome):
                self.bridge.reset_mock()
                self.bridge.press_key.side_effect = [outcome]
                self.assertEqual(diagnose_arduino.main(["--port", "COM_EXPLICIT"]), expected)
                self.bridge.panic.assert_called_once_with()
                self.bridge.disconnect.assert_called_once_with()

    def test_zero_hold_and_invalid_keys_fail_before_connect(self):
        for arguments in [["--hold-ms", "0"], ["--keys", "Y:50"], ["--keys", "中"]]:
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as result:
                diagnose_arduino.main(arguments)
            self.assertEqual(result.exception.code, 2)
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
