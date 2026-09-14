"""The controls users reach for most often.

Quick Access owns the visible rows, but not their behavior. The rows are
reparented from the detailed pages after those pages have built themselves,
so their existing signal handlers, busy states, reload paths and safety
dialogs remain the single implementation of each hardware action.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw  # noqa: E402


class QuickAccessPage(Adw.PreferencesPage):
    """Relocate the frequently used controls into three compact groups."""

    def __init__(self, window, pages):
        super().__init__()
        self.window = window
        self.pages = pages

        self.performance_group = Adw.PreferencesGroup(title="Performance")
        self.add(self.performance_group)
        self.profile_group = Adw.PreferencesGroup(
            title="Automatic profile switching")
        self.add(self.profile_group)
        self.firmware_group = Adw.PreferencesGroup(
            title="Display and firmware")
        self.add(self.firmware_group)
        self._moved_counts = {
            self.performance_group: 0,
            self.profile_group: 0,
            self.firmware_group: 0,
        }

        self._move_performance_controls()
        self._move_profile_controls()
        self._move_firmware_controls()
        self._hide_empty_groups()

    def _move(self, row, destination):
        """Move one existing row without changing its signal handlers."""
        if row is None:
            return False
        row.unparent()
        destination.add(row)
        self._moved_counts[destination] += 1
        return True

    def _move_performance_controls(self):
        cpu = self.pages.get("cpu")
        if self.window.caps.get("cpu_boost") and cpu is not None:
            self._move(cpu.rows.get("boost"), self.performance_group)

        gpu = self.pages.get("gpu")
        if self.window.caps.get("supergfxctl") and gpu is not None:
            for name in ("mode_blocked_row", "mode_row", "mode_answer_row"):
                self._move(getattr(gpu, name, None), self.performance_group)
            group = getattr(gpu, "mode_group", None)
            if group is not None:
                group.set_visible(False)

        system = self.pages.get("system")
        if self.window.caps.get("fan_curve") and system is not None:
            self._move(getattr(system, "fan_boost_row", None),
                       self.performance_group)
            group = getattr(system, "fan_boost_group", None)
            if group is not None:
                group.set_visible(False)

    def _move_profile_controls(self):
        battery = self.pages.get("battery")
        if battery is None:
            return
        for source in ("ac", "battery", "usbc"):
            self._move(battery.combos.get(source), self.profile_group)
        group = getattr(battery, "switching_group", None)
        if group is not None:
            group.set_visible(False)

    def _move_firmware_controls(self):
        system = self.pages.get("system")
        if system is None:
            return

        if self.window.caps.get("boot_sound"):
            self._move(getattr(system, "boot_sound_row", None),
                       self.firmware_group)
        if self.window.caps.get("panel_od"):
            self._move(getattr(system, "panel_od_row", None),
                       self.firmware_group)
        if self.window.caps.get("psr_toggle"):
            self._move(getattr(system, "psr_row", None),
                       self.firmware_group)
            self._move(getattr(system, "psr_pending_row", None),
                       self.firmware_group)

        group = getattr(system, "firmware_group", None)
        if group is not None:
            group.set_visible(False)
        group = getattr(system, "psr_group", None)
        if group is not None:
            group.set_visible(False)

    def _hide_empty_groups(self):
        for group in (self.performance_group, self.profile_group,
                      self.firmware_group):
            group.set_visible(self._moved_counts[group] > 0)
