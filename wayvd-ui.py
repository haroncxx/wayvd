#!/usr/bin/env python3
"""GTK frontend for the wayvd command-line utility."""

import os
import signal
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk, Gdk


WAYVD = os.environ.get("WAYVD_COMMAND", "wayvd")
MOUNT_HELPER = "/usr/local/libexec/wayvd-mount-helper"
PROFILES = ["portrait", "fold", "landscape", "fold-landscape", "default", "last", "size"]


def button(label, callback, css_class=None):
    item = Gtk.Button(label=label)
    if css_class:
        item.add_css_class(css_class)
    item.connect("clicked", callback)
    return item


class LogWindow(Adw.Window):
    """A small window that streams `wayvd logcat` without blocking the UI."""

    def __init__(self, parent):
        super().__init__(transient_for=parent, title="Waydroid Logcat")
        self.set_default_size(760, 480)
        self.process = None

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.pack_end(button("Stop", self.stop))
        toolbar.add_top_bar(header)

        self.output = Gtk.TextView(editable=False, monospace=True)
        self.output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow(vexpand=True, child=self.output)
        toolbar.set_content(scroll)
        self.set_content(toolbar)
        self.connect("close-request", self.close_log)
        self.present()
        self.start()

    def start(self):
        try:
            self.process = subprocess.Popen(
                [WAYVD, "logcat"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as error:
            self.append(f"Could not start {WAYVD}: {error}\n")
            return
        threading.Thread(target=self.read_output, daemon=True).start()

    def read_output(self):
        for line in self.process.stdout:
            GLib.idle_add(self.append, line)

    def append(self, text):
        buffer = self.output.get_buffer()
        buffer.insert(buffer.get_end_iter(), text)
        return False

    def stop(self, *_args):
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def close_log(self, *_args):
        self.stop()
        return False


class HelpWindow(Adw.Window):
    """A concise in-app reference for the available UI controls."""

    def __init__(self, parent):
        super().__init__(transient_for=parent, title="wayvd-ui Help")
        self.set_default_size(560, 420)
        text = """Session
Choose a display profile, then select Start. Stop ends the active session.

Shared folders
Choose a host folder and optional Android folder name, then select Mount.
Mount and Unmount use GNOME's system authentication dialog.

Development
Connect local ADB, install APKs, launch or clear a package, capture the
display, record the screen, or open the logcat viewer.

Android controls
Esc             Back
Home            Home
Ctrl+M          Menu
Ctrl+P          Power
Ctrl+F5         Volume down
Ctrl+F6         Volume up

Shortcuts work only while this window is focused and are disabled in text
fields. Hold either volume button to repeat the Android volume action."""
        output = Gtk.TextView(editable=False, monospace=True)
        output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        output.get_buffer().set_text(text)
        self.set_content(Gtk.ScrolledWindow(child=output))


class WayvdWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="wayvd")
        self.set_default_size(660, 720)
        self.recording = None
        self.volume_repeaters = {}

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.pack_end(button("Help", self.show_help))
        toolbar.add_top_bar(header)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page.set_margin_top(18)
        page.set_margin_bottom(18)
        page.set_margin_start(18)
        page.set_margin_end(18)
        toolbar.set_content(Gtk.ScrolledWindow(child=page))
        self.set_content(toolbar)

        page.append(self.session_group())
        page.append(self.folders_group())
        page.append(self.development_group())
        page.append(self.controls_group())

        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.add_css_class("dim-label")
        page.append(self.status)

        # These familiar Android Emulator shortcuts are scoped to this window.
        # Returning True only for a recognized shortcut prevents its normal
        # widget action; all other input continues through GTK unchanged.
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self.handle_shortcut)
        self.add_controller(key_controller)

    def group(self, title, description=None):
        group = Adw.PreferencesGroup(title=title, description=description)
        group.set_hexpand(True)
        return group

    def session_group(self):
        group = self.group("Session", "Start Waydroid with a display profile.")
        row = Adw.ActionRow(title="Display profile")
        self.profile = Gtk.DropDown.new_from_strings(PROFILES)
        row.add_suffix(self.profile)
        group.add(row)

        custom = Adw.EntryRow(title="Custom size")
        custom.set_text("600x900")
        self.custom_size = custom
        group.add(custom)

        actions = Adw.ActionRow(title="Waydroid")
        actions.add_suffix(button("Start", self.start_profile, "suggested-action"))
        actions.add_suffix(button("Stop", self.stop_session, "destructive-action"))
        actions.add_suffix(button("Status", self.status_command))
        group.add(actions)
        return group

    def folders_group(self):
        group = self.group("Shared folders", "Bind-mount a host folder into Android storage.")
        folder = Adw.EntryRow(title="Host folder")
        folder.set_text(str(Path.home() / "Downloads"))
        self.folder_path = folder
        folder.add_suffix(button("Choose", self.choose_folder))
        group.add(folder)

        name = Adw.EntryRow(title="Android folder name")
        self.folder_name = name
        group.add(name)

        actions = Adw.ActionRow(title="Folder actions")
        actions.add_suffix(button("Mount", self.mount_folder, "suggested-action"))
        actions.add_suffix(button("Unmount", self.unmount_folder))
        actions.add_suffix(button("Status", self.mount_status))
        group.add(actions)
        return group

    def development_group(self):
        group = self.group("Development", "Commands use Waydroid's local private ADB bridge.")
        apk = Adw.EntryRow(title="APK file")
        self.apk_path = apk
        apk.add_suffix(button("Choose", self.choose_apk))
        group.add(apk)

        package = Adw.EntryRow(title="Package name")
        self.package_name = package
        group.add(package)

        actions = Adw.ActionRow(title="ADB and package actions")
        actions.add_suffix(button("Connect ADB", lambda *_: self.run(["adb"])))
        actions.add_suffix(button("Install APK", self.install_apk))
        actions.add_suffix(button("Launch", self.launch_package))
        actions.add_suffix(button("Clear data", self.confirm_clear))
        group.add(actions)

        capture = Adw.ActionRow(title="Capture")
        capture.add_suffix(button("Screenshot", self.screenshot))
        capture.add_suffix(button("Record", self.toggle_recording))
        capture.add_suffix(button("Logcat", lambda *_: LogWindow(self)))
        group.add(capture)
        return group

    def controls_group(self):
        group = self.group(
            "Android controls",
            "Esc Back, Home Home, Ctrl+M Menu, Ctrl+P Power, Ctrl+F5/F6 Volume.",
        )
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        for index, action in enumerate(
            ["back", "home", "recents", "power", "volume-down", "volume-up", "mute"]
        ):
            item = Gtk.Button(label=action.replace("-", " ").title())
            item.set_name(action)
            if action.startswith("volume-"):
                self.add_volume_repeat(item, action)
            else:
                item.connect("clicked", self.send_key)
            grid.attach(item, index % 4, index // 4, 1, 1)
        row = Adw.ActionRow(title="AVD-style buttons")
        row.add_suffix(grid)
        group.add(row)
        return group

    def set_status(self, text):
        self.status.set_text(text)
        return False

    def show_help(self, *_args):
        HelpWindow(self).present()

    def handle_shortcut(self, _controller, keyval, _keycode, state):
        # Preserve expected editing keys while an entry has focus.
        if isinstance(self.get_focus(), Gtk.Editable):
            return False
        modifiers = state & Gtk.accelerator_get_default_mod_mask()
        action = None
        if modifiers == 0:
            action = {
                Gdk.KEY_Escape: "back",
                Gdk.KEY_Home: "home",
            }.get(keyval)
        elif modifiers == Gdk.ModifierType.CONTROL_MASK:
            action = {
                Gdk.KEY_m: "menu",
                Gdk.KEY_M: "menu",
                Gdk.KEY_p: "power",
                Gdk.KEY_P: "power",
                Gdk.KEY_F5: "volume-down",
                Gdk.KEY_F6: "volume-up",
            }.get(keyval)
        if not action:
            return False
        self.run(["key", action])
        return True

    def run(self, arguments, success=None):
        """Run short commands off the GTK thread and display stdout or errors."""
        self.set_status(f"Running: {WAYVD} {' '.join(arguments)}")

        def worker():
            try:
                result = subprocess.run(
                    [WAYVD, *arguments], capture_output=True, text=True, check=False
                )
                output = (result.stdout or result.stderr).strip()
                message = output or "Completed."
                if result.returncode:
                    message = f"Command failed: {message}"
                elif success:
                    success()
            except OSError as error:
                message = f"Could not run {WAYVD}: {error}"
            GLib.idle_add(self.set_status, message)

        threading.Thread(target=worker, daemon=True).start()

    def run_privileged(self, arguments):
        """Use PolicyKit so GNOME shows its native authentication dialog."""
        self.set_status("Waiting for system authentication.")

        def worker():
            try:
                result = subprocess.run(
                    ["pkexec", MOUNT_HELPER, *arguments],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                output = (result.stdout or result.stderr).strip()
                message = output or "Completed."
                if result.returncode:
                    message = f"Command failed: {message}"
            except OSError as error:
                message = f"Could not start PolicyKit authentication: {error}"
            GLib.idle_add(self.set_status, message)

        threading.Thread(target=worker, daemon=True).start()

    def start_profile(self, *_args):
        profile = PROFILES[self.profile.get_selected()]
        arguments = ["start"]
        if profile == "size":
            size = self.custom_size.get_text().strip()
            if not size:
                self.set_status("Enter a custom size such as 600x900.")
                return
            arguments.extend(["size", size])
        else:
            arguments.append(profile)
        try:
            subprocess.Popen([WAYVD, *arguments])
            self.set_status(f"Started profile: {profile}.")
        except OSError as error:
            self.set_status(f"Could not start {WAYVD}: {error}")

    def stop_session(self, *_args):
        self.run(["stop"])

    def status_command(self, *_args):
        self.run(["status"])

    def choose_folder(self, *_args):
        Gtk.FileDialog(title="Choose folder").select_folder(self, None, self.folder_selected)

    def folder_selected(self, dialog, result):
        try:
            selected = dialog.select_folder_finish(result)
            self.folder_path.set_text(selected.get_path())
            if not self.folder_name.get_text():
                self.folder_name.set_text(selected.get_basename())
        except GLib.Error:
            pass

    def mount_folder(self, *_args):
        path = self.folder_path.get_text().strip()
        name = self.folder_name.get_text().strip()
        if not path:
            self.set_status("Choose a host folder first.")
            return
        if not name:
            name = Path(path).name
        self.run_privileged(["mount", path, name])

    def unmount_folder(self, *_args):
        name = self.folder_name.get_text().strip()
        if not name:
            self.set_status("Enter the Android folder name to unmount.")
            return
        self.run_privileged(["unmount", name])

    def mount_status(self, *_args):
        name = self.folder_name.get_text().strip()
        if not name:
            self.set_status("Enter the Android folder name to inspect.")
            return
        self.run(["mount-status", name])

    def choose_apk(self, *_args):
        Gtk.FileDialog(title="Choose APK").open(self, None, self.apk_selected)

    def apk_selected(self, dialog, result):
        try:
            self.apk_path.set_text(dialog.open_finish(result).get_path())
        except GLib.Error:
            pass

    def install_apk(self, *_args):
        path = self.apk_path.get_text().strip()
        if not path:
            self.set_status("Choose an APK first.")
            return
        self.run(["install", path])

    def launch_package(self, *_args):
        package = self.package_name.get_text().strip()
        if not package:
            self.set_status("Enter an Android package name first.")
            return
        self.run(["launch", package])

    def confirm_clear(self, *_args):
        package = self.package_name.get_text().strip()
        if not package:
            self.set_status("Enter an Android package name first.")
            return
        dialog = Adw.AlertDialog.new("Clear app data?", f"Reset all data for {package}?")
        dialog.add_responses("cancel", "Cancel", "clear", "Clear data")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.choose(self, None, lambda item, result: self.clear_chosen(item, result, package))

    def clear_chosen(self, dialog, result, package):
        if dialog.choose_finish(result) == "clear":
            self.run(["clear", package])

    def screenshot(self, *_args):
        target = str(Path.home() / "Pictures" / "waydroid.png")
        self.run(["screenshot", target])

    def toggle_recording(self, source):
        if self.recording and self.recording.poll() is None:
            self.recording.send_signal(signal.SIGINT)
            self.recording = None
            source.set_label("Record")
            self.set_status("Finishing recording and copying it to ~/Videos/waydroid.mp4.")
            return
        target = str(Path.home() / "Videos" / "waydroid.mp4")
        try:
            self.recording = subprocess.Popen([WAYVD, "record", target])
            source.set_label("Stop recording")
            self.set_status("Recording to ~/Videos/waydroid.mp4. Press Stop recording to finish.")
        except OSError as error:
            self.set_status(f"Could not start recording: {error}")

    def send_key(self, source):
        self.run(["key", source.get_name()])

    def add_volume_repeat(self, item, action):
        """Tap once or hold to repeat Android's bounded volume action."""
        gesture = Gtk.GestureClick()
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesture.connect("pressed", self.volume_press, item, action)
        gesture.connect("released", self.volume_release, item)
        item.add_controller(gesture)

    def volume_press(self, _gesture, _presses, _x, _y, item, action):
        # A tap changes volume once. A hold waits briefly before repetition so
        # normal single clicks retain predictable AVD-style behavior.
        self.run(["key", action])
        self.volume_repeaters[item] = GLib.timeout_add(
            350, self.begin_volume_repeat, item, action
        )

    def volume_release(self, _gesture, _presses, _x, _y, item):
        repeat_id = self.volume_repeaters.pop(item, None)
        if repeat_id:
            GLib.source_remove(repeat_id)

    def begin_volume_repeat(self, item, action):
        if item not in self.volume_repeaters:
            return False
        self.repeat_volume_key(action)
        self.volume_repeaters[item] = GLib.timeout_add(
            175, self.repeat_volume_key, action
        )
        return False

    def repeat_volume_key(self, action):
        # Android clamps volume at its own min/max; repeated events are safe.
        subprocess.Popen(
            [WAYVD, "key", action],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True


class WayvdApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.haroncxx.wayvd")

    def do_activate(self):
        window = self.props.active_window
        if not window:
            window = WayvdWindow(self)
        window.present()


if __name__ == "__main__":
    WayvdApplication().run()
