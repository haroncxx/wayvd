#!/usr/bin/env python3
"""GTK frontend for the wayvd command-line utility."""

import os
import signal
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk


WAYVD = os.environ.get("WAYVD_COMMAND", "wayvd")
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


class WayvdWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="wayvd")
        self.set_default_size(660, 720)
        self.recording = None

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
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
        group = self.group("Android controls", "These buttons affect Waydroid, not the host desktop.")
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        for index, action in enumerate(
            ["back", "home", "recents", "power", "volume-down", "volume-up", "mute"]
        ):
            grid.attach(button(action.replace("-", " ").title(), self.send_key, None), index % 4, index // 4, 1, 1)
            grid.get_child_at(index % 4, index // 4).set_name(action)
        row = Adw.ActionRow(title="AVD-style buttons")
        row.add_suffix(grid)
        group.add(row)
        return group

    def set_status(self, text):
        self.status.set_text(text)
        return False

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
        self.run(["mount", path, *([name] if name else [])])

    def unmount_folder(self, *_args):
        name = self.folder_name.get_text().strip()
        if not name:
            self.set_status("Enter the Android folder name to unmount.")
            return
        self.run(["unmount", name])

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
