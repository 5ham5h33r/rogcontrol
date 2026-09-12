"""Contracts across extracted controllers, commands, and reports."""

import copy
import io
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from rogcontrol import APP_VERSION, cli, config, diagnostics, hardware, updater
from rogcontrol.__main__ import main as entry_main


class CommandTests(unittest.TestCase):
    def test_headless_imports_and_help_do_not_load_gtk(self):
        result = subprocess.run([sys.executable, "-c",
            "import sys; from rogcontrol import cli, diagnostics, updater; "
            "assert 'gi' not in sys.modules; "
            "from rogcontrol.__main__ import main; main(['--help'])"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("keyboard", result.stdout)

    def test_new_command_dispatch(self):
        for args, function, expected in (
            (["profile", "next"], "cycle_profile", ()),
            (["keyboard", "next"], "cycle_keyboard", ()),
            (["keyboard", "brightness", "up"], "adjust_brightness", ("up",)),
            (["keyboard", "speed", "down"], "adjust_speed", ("down",)),
        ):
            with self.subTest(args=args), patch.object(cli, function, return_value=None) as action:
                self.assertEqual(entry_main(args), 0)
                action.assert_called_once_with(*expected)

    def test_legacy_shortcut_dispatch(self):
        root = Path(cli.__file__).parent
        for filename, args, expected in (
            ("rogcontrol-cycle-profile.py", [], ["profile", "next"]),
            ("rogcontrol-cycle-kbdlight.py", [], ["keyboard", "next"]),
            ("rogcontrol-adjust-kbdbrightness.py", ["up"], ["keyboard", "brightness", "up"]),
            ("rogcontrol-adjust-kbdspeed.py", ["down"], ["keyboard", "speed", "down"]),
        ):
            with self.subTest(filename=filename), patch.object(sys, "argv", [filename, *args]), \
                    patch.object(cli, "main", return_value=0) as dispatch:
                with self.assertRaises(SystemExit) as outcome:
                    runpy.run_path(str(root / filename), run_name="__main__")
                self.assertEqual(outcome.exception.code, 0)
                dispatch.assert_called_once_with(expected)

    def test_report_alias(self):
        with patch.object(diagnostics, "write_hardware_report", return_value="/tmp/report.txt") as report, \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(entry_main(["--hardware-report"]), 0)
            report.assert_called_once_with()
            self.assertIn("/tmp/report.txt", output.getvalue())

    def test_invalid_direction_never_writes(self):
        with patch.object(hardware, "run_helper_logged") as helper, \
                patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit):
                entry_main(["keyboard", "brightness", "invalid"])
            helper.assert_not_called()

    def test_brightness_preserves_other_settings_and_only_saves_success(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, "CONFIG_PATH", str(Path(directory) / "config.json")), \
                patch.object(cli, "notify"):
            cfg = config.load_config()
            cfg["kbd_brightness"] = 1
            cfg["appearance"] = "dark"
            config.save_config(cfg)
            with patch.object(hardware, "run_helper_logged", return_value=(True, "")) as helper:
                cli.main(["keyboard", "brightness", "up"])
                helper.assert_called_once_with(*cli.kbdcolor.kbd_brightness_args(2), source="adjust-kbdbrightness")
            saved = config.load_config()
            self.assertEqual(saved["kbd_brightness"], 2)
            self.assertEqual(saved["profiles"], cfg["profiles"])
            self.assertEqual(saved["appearance"], "dark")
            with patch.object(hardware, "run_helper_logged", return_value=(False, "refused")):
                cli.main(["keyboard", "brightness", "down"])
            self.assertEqual(config.load_config()["kbd_brightness"], 2)

    def test_profile_switch_orders_power_mode_before_hardware(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, "CONFIG_PATH", str(Path(directory) / "config.json")), \
                patch.object(cli, "notify"):
            cfg = config.load_config()
            config.save_config(cfg)
            calls = []
            with patch.object(hardware, "set_power_mode_for_profile", side_effect=lambda *a: calls.append("power")), \
                    patch.object(hardware, "set_profile_kbd_color", side_effect=lambda *a: calls.append("keyboard")), \
                    patch.object(cli, "apply_profile", side_effect=lambda *a: calls.append("apply")):
                cli.main(["profile", "next"])
            self.assertEqual(calls, ["power", "keyboard", "apply"])
            self.assertNotEqual(config.load_config()["current_profile"], cfg["current_profile"])

    def test_keyboard_mode_and_speed_preserve_other_rgb_fields(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, "CONFIG_PATH", str(Path(directory) / "config.json")), \
                patch.object(cli, "notify"), \
                patch.object(hardware, "run_helper_logged", return_value=(True, "")):
            cfg = config.load_config()
            cfg["kbd_rgb"] = {"mode": "Static", "speed": 1, "r": 42, "g": 80, "b": 120}
            config.save_config(cfg)
            with patch.object(cli, "available_modes", return_value=["Static", "Breathing"]):
                cli.main(["keyboard", "next"])
            self.assertEqual(config.load_config()["kbd_rgb"]["mode"], "Breathing")
            cli.main(["keyboard", "speed", "up"])
            rgb = config.load_config()["kbd_rgb"]
            self.assertEqual(rgb["mode"], "Breathing")
            self.assertEqual(rgb["speed"], 2)
            self.assertEqual((rgb["r"], rgb["g"], rgb["b"]), (42, 80, 120))


class DiagnosticsTests(unittest.TestCase):
    def test_report_with_fake_sysfs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os_release = root / "etc/os-release"
            os_release.parent.mkdir()
            os_release.write_text('PRETTY_NAME="Test Linux"\n')
            node = root / "sys/devices/platform/asus-nb-wmi/ppt_pl1_spl"
            node.parent.mkdir(parents=True)
            node.write_text("45\n")
            with patch.object(hardware, "detect_capabilities", return_value={"cpu_vendor": "Intel"}), \
                    patch.object(hardware, "read_asusd_state", return_value={}), \
                    patch.object(hardware, "read_supergfxd_state", return_value={}):
                report = diagnostics.hardware_report_text(root=directory)
            self.assertIn("distribution: Test Linux", report)
            self.assertIn("ppt_pl1_spl = '45'", report)
            self.assertIn(APP_VERSION, report)

    def test_test_version_compares_on_numeric_version(self):
        self.assertEqual(updater._version_tuple("v1.0.1.2-test.1"), (1, 0, 1, 2))
        self.assertLess(updater._version_tuple("1.0.1.2-test.1"), updater._version_tuple("1.0.1.3"))


class WindowIntegrationTests(unittest.TestCase):
    def test_all_pages_and_profile_controller(self):
        from gi.repository import Gio
        from rogcontrol.app import MainWindow
        from rogcontrol.ui import Adw, Gtk
        Adw.init()
        app = Adw.Application(application_id="org.rogcontrol.RefactorTest",
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
        app.register(None)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, "CONFIG_PATH", str(Path(directory) / "config.json")), \
                patch.object(MainWindow, "apply_async"), \
                patch.object(MainWindow, "apply_isolated"), \
                patch.object(hardware, "run_helper", side_effect=AssertionError("Unexpected hardware write")), \
                patch.object(hardware, "gpu_clock_limit_max", return_value=3000):
            window = MainWindow(app, config.load_config(), {})
            window.realize()
            try:
                self.assertEqual(len(window.pages), 7)
                for name in ("new-profile", "delete-profile", "import-profiles", "export-profile"):
                    self.assertIsNotNone(window.lookup_action(name))
                entry = Gtk.Entry(text="Refactor test")
                before = copy.deepcopy(window.current_profile())
                window.profile_actions._on_new_profile_response(None, "create", entry)
                self.assertEqual(window.config["profiles"]["Refactor test"], before)
                self.assertEqual(config.load_config()["current_profile"], "Refactor test")
                with patch.object(window, "apply_profile_async") as apply:
                    window.profile_actions._on_delete_response(None, "delete", "Refactor test")
                    apply.assert_called_once()
                self.assertNotIn("Refactor test", window.config["profiles"])
                system = window.pages["system"]
                system.check_for_update()
                self.assertTrue(system.updates._update_busy)
                callback = window.apply_isolated.call_args.args[1]
                callback({"available": False}, None)
                self.assertFalse(system.updates._update_busy)
                self.assertTrue(system.update_check_button.get_sensitive())
                for page in window.pages:
                    window.select_page(page)
            finally:
                window.destroy()
                window._worker_pool.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
