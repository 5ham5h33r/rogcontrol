"""Run with python3 -m unittest discover -s tests (requires a GTK display)."""

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rogcontrol import config
from rogcontrol.ui import (Adw, Gtk, ICON_DIR, apply_appearance,
                           appearance_index, bundled_icon, icon_image)
from rogcontrol.pages.system import SystemPage
from rogcontrol.update_ui import UpdateController
from rogcontrol.widgets.curve_editor import CurveEditor


class AppearancePage(Adw.PreferencesPage):
    _build_appearance = SystemPage._build_appearance
    _on_appearance_changed = SystemPage._on_appearance_changed
    reload = SystemPage.reload

    def __init__(self, settings):
        super().__init__()
        self.window = SimpleNamespace(config=settings)
        self._loading = False
        self.osmode_value = Gtk.Label(label="balanced")
        self._render_sync = Mock()
        self._build_appearance()


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def tearDown(self):
        apply_appearance({})

    def test_icons_ignore_desktop_theme(self):
        # A private theme avoids changing the user's desktop settings.
        theme = Gtk.IconTheme.new()
        for name in ("Adwaita", "Breeze", "missing-icon-pack"):
            theme.set_theme_name(name)
            for path in ICON_DIR.glob("*.svg"):
                with self.subTest(theme=name, icon=path.name):
                    paintable = theme.lookup_by_gicon(
                        bundled_icon(path.stem), 16, 1,
                        Gtk.TextDirection.LTR, Gtk.IconLookupFlags(0))
                    self.assertEqual(paintable.get_file().get_path(), str(path))
                    self.assertTrue(paintable.is_symbolic())
                    self.assertEqual(icon_image(path.stem).get_pixel_size(), 16)

    def test_modes_and_graph_palette(self):
        graph = CurveEditor()
        for mode, dark in (("light", False), ("dark", True)):
            with self.subTest(mode=mode), patch.object(graph, "queue_draw") as redraw:
                apply_appearance({"appearance": mode})
                self.assertEqual(Adw.StyleManager.get_default().get_dark(), dark)
                self.assertEqual(graph._palette()["bg"][0] < 0.5, dark)
                if mode == "dark":
                    redraw.assert_called()
        apply_appearance({"appearance": "system"})
        self.assertEqual(Adw.StyleManager.get_default().get_color_scheme(),
                         Adw.ColorScheme.DEFAULT)

    def test_picker_persists_and_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "config.json")
            with patch.object(config, "CONFIG_PATH", path):
                settings = config.load_config()
                page = AppearancePage(settings)
                page.appearance_row.set_selected(2)
                restored = config.load_config()
                self.assertEqual(restored["appearance"], "dark")
                self.assertTrue(Adw.StyleManager.get_default().get_dark())
                self.assertEqual(AppearancePage(restored).appearance_row.get_selected(), 2)
                page.appearance_row.set_selected(1)
                self.assertEqual(config.load_config()["appearance"], "light")
                self.assertFalse(Adw.StyleManager.get_default().get_dark())

    def test_reload_applies_without_saving(self):
        page = AppearancePage({"appearance": "light"})
        page.window.config["appearance"] = "dark"
        with patch.object(config, "save_config") as save:
            page.reload()
            save.assert_not_called()
        self.assertEqual(page.appearance_row.get_selected(), 2)
        self.assertTrue(Adw.StyleManager.get_default().get_dark())
        self.assertFalse(page._loading)

    def test_unknown_preferences_follow_system(self):
        for value in (None, "unknown", [], {}):
            self.assertEqual(appearance_index({"appearance": value}), 0)
        self.assertEqual(appearance_index({}), 0)

    def test_rendered_colors_override_forced_dark_desktop_css(self):
        import cairo
        from gi.repository import Gdk, GLib

        display = Gdk.Display.get_default()
        desktop = Gtk.CssProvider()
        desktop.load_from_data(b"""
            window.background { background: #101010; color: white; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            display, desktop, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        window = Adw.Window()
        window.realize()
        try:
            for mode, light in (("light", True), ("dark", False), ("system", False)):
                with self.subTest(mode=mode):
                    apply_appearance({"appearance": mode})
                    while GLib.MainContext.default().pending():
                        GLib.MainContext.default().iteration(False)
                    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 40, 40)
                    Gtk.render_background(window.get_style_context(),
                                          cairo.Context(surface), 0, 0, 40, 40)
                    surface.flush()
                    # Read an actual rendered center pixel, not only the
                    # StyleManager flag that passed despite this regression.
                    offset = 20 * surface.get_stride() + 20 * 4
                    b, g, r, alpha = bytes(surface.get_data())[offset:offset + 4]
                    if mode == "system":
                        self.assertEqual(alpha, 255)
                    else:
                        self.assertGreater(alpha, 225)
                        self.assertLess(alpha, 250)
                    if mode == "dark":
                        self.assertEqual((r, g, b), (0, 0, 0))
                    self.assertEqual(min(r, g, b) > 200, light)
                    fg = window.get_style_context().get_color()
                    self.assertEqual(fg.red < 0.3, light)
        finally:
            window.destroy()
            Gtk.StyleContext.remove_provider_for_display(display, desktop)


class UpdatePageHarness:
    _on_update_dialog_response = UpdateController._on_update_dialog_response
    _on_update_staged = UpdateController._on_update_staged
    _on_download_progress = UpdateController._on_download_progress
    _finish_update = UpdateController._finish_update
    _poll_update_install = UpdateController._poll_update_install

    def __init__(self):
        self._update_busy = False
        self._update_install_timer = None
        self._update_cancelled = threading.Event()
        self.window = Mock()
        self.page = self
        self.update_check_button = Mock()
        self._set_update_status = Mock()


class UpdateUiTests(unittest.TestCase):
    def test_download_cannot_overlap_and_timeout_allows_retry(self):
        page = UpdatePageHarness()
        page._on_update_dialog_response(None, "update", "2", "https://example.test/a.zip")
        self.assertTrue(page._update_busy)
        page.update_check_button.set_sensitive.assert_called_with(False)
        page._on_update_dialog_response(None, "update", "2", "https://example.test/a.zip")
        page.window.apply_isolated.assert_called_once()
        page._on_update_staged("2", None, TimeoutError("Timed out"))
        self.assertFalse(page._update_busy)
        self.assertTrue(page._update_cancelled.is_set())
        page.update_check_button.set_sensitive.assert_called_with(True)
        page._set_update_status.reset_mock()
        page._on_download_progress("2", page._update_cancelled, 10, 100)
        page._set_update_status.assert_not_called()

    def test_installer_completion_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status"
            for status, expected in (("0", "installed"), ("7", "failed")):
                with self.subTest(status=status):
                    page = UpdatePageHarness()
                    page._update_busy = True
                    path.write_text(status)
                    self.assertFalse(page._poll_update_install("2", str(path), 0))
                    self.assertFalse(page._update_busy)
                    self.assertIn(expected, page._set_update_status.call_args.args[0])

    def test_closed_installer_allows_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status"
            path.write_text("running:12345")
            page = UpdatePageHarness()
            page._update_busy = True
            with patch("rogcontrol.update_ui.os.kill", side_effect=ProcessLookupError):
                self.assertFalse(page._poll_update_install("2", str(path), 0))
            self.assertFalse(page._update_busy)


if __name__ == "__main__":
    unittest.main()
