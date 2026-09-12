"""Create, delete, import, and export profile dialogs."""

import json
import os
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk
from . import config as config_mod


class ProfileActions:
    def __init__(self, window):
        self.window = window

    def _on_new_profile(self, _action, _param):
        current = self.window.current_profile_name()
        dialog = Adw.AlertDialog(
            heading="New profile",
            body=f"It starts as a copy of “{current}”, so the machine keeps "
                 f"running exactly as it is now." if current else
                 "The new profile starts from the stock settings.")
        entry = Gtk.Entry(placeholder_text="Profile name")
        # Enter creates, which is the whole interaction for a dialog that is
        # one text field.
        entry.set_activates_default(True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Create")
        dialog.set_response_appearance("create",
                                       Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")
        # Refused names are refused before the button is pressed rather than
        # after: an empty or duplicate name is the only way this can fail, and
        # a greyed-out Create says so without the user losing what they typed.
        dialog.set_response_enabled("create", False)
        entry.connect("changed", self._on_new_profile_typed, dialog)
        dialog.connect("response", self._on_new_profile_response, entry)
        dialog.present(self.window)

    def _on_new_profile_typed(self, entry, dialog):
        error = config_mod.profile_name_error(self.window.config, entry.get_text())
        dialog.set_response_enabled("create", error is None)
        # Red only once there is something to be wrong: an empty field is the
        # starting state, not a mistake.
        if error is not None and entry.get_text().strip():
            entry.add_css_class("error")
            entry.set_tooltip_text(error)
        else:
            entry.remove_css_class("error")
            entry.set_tooltip_text(None)

    def _on_new_profile_response(self, _dialog, response, entry):
        if response != "create":
            return
        try:
            name = config_mod.create_profile(self.window.config, entry.get_text())
        except ValueError as e:
            self.window.toast(str(e))
            return
        config_mod.save_config(self.window.config)
        self.window._refresh_profile_list(select=name)
        self.window.reload_pages()
        # No hardware apply: the new profile is a copy of the one already
        # running, so there is nothing to push, and pushing it would cost
        # ~20 seconds of fan writes to arrive back where the machine already is.
        self.window.toast(f"Profile “{name}” created — a copy of what is running.")

    def _on_delete_profile(self, _action, _param):
        name = self.window.current_profile_name()
        if not name:
            self.window.toast("There is no profile to delete.")
            return
        if len((self.window.config.get("profiles") or {})) <= 1:
            self.window.toast("This is the only profile left — there has to be one.")
            return
        # Named here rather than discovered afterwards: losing an auto-switch
        # target is a consequence the user should agree to, not find out about
        # the next time they unplug.
        also = [source for source, key in config_mod.AUTO_SWITCH_KEYS.items()
                if self.window.config.get(key) == name]
        body = "This cannot be undone."
        if also:
            body += (" It is also the profile used on "
                     + " and ".join(also)
                     + " power, so that auto-switch will be turned off.")
        dialog = Adw.AlertDialog(heading=f"Delete “{name}”?", body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete",
                                       Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_delete_response, name)
        dialog.present(self.window)

    def _on_delete_response(self, _dialog, response, name):
        if response != "delete":
            return
        was_current = name == self.window.config.get("current_profile")
        try:
            current = config_mod.delete_profile(self.window.config, name)
        except ValueError as e:
            self.window.toast(str(e))
            return
        config_mod.save_config(self.window.config)
        self.window._refresh_profile_list(select=current)
        self.window.reload_pages()
        self.window.toast(f"Deleted “{name}”.")
        if was_current:
            # The machine is still running the settings of a profile that no
            # longer exists, and current_profile now names a different one.
            # Leaving those two disagreeing is what the enforcer would spend
            # the next minute correcting anyway.
            self.window.apply_profile_async(current)

    def _on_export_profile(self, _action, _param):
        # Everything, not the one profile on screen -- this is the backup,
        # so leaving anything out would make it a worse one than just
        # copying ~/.config/rogcontrol.json by hand.
        dialog = Gtk.FileDialog()
        dialog.set_title("Export Backup")
        dialog.set_initial_name("rogcontrol-backup.json")
        dialog.set_filters(self._json_filters())
        # Gtk.FileDialog, not Gtk.FileChooserDialog: the latter is deprecated
        # in GTK 4.10 and its .run() needs a nested main loop, which is the
        # thing this rewrite is built to avoid.
        dialog.save(self.window, None, self._on_export_chosen)

    def _on_export_chosen(self, dialog, result):
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return  # dismissed
        path = file.get_path() if file is not None else None
        if not path:
            return
        payload = config_mod.export_backup(self.window.config)
        try:
            with open(path, "w") as f:
                json.dump(payload, f, indent=2)
        except (OSError, TypeError, ValueError) as e:
            self.window.toast(f"Export failed: {e}")
            return
        self.window.toast(f"Backed up everything to {os.path.basename(path)}.")

    def _on_import_profiles(self, _action, _param):
        dialog = Gtk.FileDialog()
        dialog.set_title("Import")
        dialog.set_filters(self._json_filters())
        dialog.open(self.window, None, self._on_import_chosen)

    def _on_import_chosen(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return  # dismissed
        path = file.get_path() if file is not None else None
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            self.window.toast(f"Could not read that file: {e}")
            return
        # A full backup replaces everything and cannot be undone, so it
        # gets a confirmation the same way Delete does. An old-style file
        # that shares one or a few profiles has no backup marker and merges
        # in immediately, exactly as it always has -- that path is already
        # safe by construction (see import_profiles).
        if config_mod.is_backup_file(data):
            self._confirm_restore_backup(data)
            return
        try:
            # Validates the whole file before it touches the config: a file
            # that is half profiles and half junk must change nothing at all.
            names = config_mod.import_profiles(self.window.config, data)
        except ValueError as e:
            self.window.toast(f"Could not import: {e}")
            return
        config_mod.save_config(self.window.config)
        self.window._refresh_profile_list()
        self.window.reload_pages()
        # Imported, not applied: the file describes power limits and fan
        # curves for a machine that may not be this one, so it arrives as
        # something to look at and select, never as something now running.
        if len(names) == 1:
            self.window.toast(f"Imported “{names[0]}” — select it to apply.")
        else:
            self.window.toast(f"Imported {len(names)} profiles — "
                       f"select one to apply.")

    def _confirm_restore_backup(self, data):
        profiles = data.get("profiles")
        count = len(profiles) if isinstance(profiles, dict) else 0
        body = (f"This replaces every profile and setting you have now "
                f"with the {count} profile"
                f"{'s' if count != 1 else ''} and settings in this backup. "
                f"This cannot be undone.")
        dialog = Adw.AlertDialog(heading="Restore this backup?", body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("restore", "Restore")
        dialog.set_response_appearance("restore",
                                       Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_restore_response, data)
        dialog.present(self.window)

    def _on_restore_response(self, _dialog, response, data):
        if response != "restore":
            return
        try:
            # Raises before cfg.clear() runs, so a corrupt or truncated
            # backup leaves the current config untouched rather than
            # replacing it with half a file.
            config_mod.restore_backup(self.window.config, data)
        except ValueError as e:
            self.window.toast(f"Could not restore: {e}")
            return
        config_mod.save_config(self.window.config)
        self.window._refresh_profile_list()
        self.window.reload_pages()
        self.window.toast("Backup restored.")

    @staticmethod
    def _json_filters():
        """Profile files first, everything else still reachable -- an export
        the user renamed is still a perfectly good import."""
        filters = Gio.ListStore.new(Gtk.FileFilter)
        profile_filter = Gtk.FileFilter()
        profile_filter.set_name("Profile files")
        profile_filter.add_pattern("*.json")
        filters.append(profile_filter)
        everything = Gtk.FileFilter()
        everything.set_name("All files")
        everything.add_pattern("*")
        filters.append(everything)
        return filters

