# wayvd

`wayvd` is a Bash command-line companion for [Waydroid](https://waydro.id/).
It provides repeatable phone and foldable display profiles, local folder
sharing, local Android Debug Bridge (ADB) commands, screenshots, recordings,
and AVD-style Android button actions.

It is intended for a Linux desktop running Waydroid. The configured display
profiles below were chosen to fit a 1920x1080 desktop while retaining the
shape of a Google Pixel 10 Pro Fold.

## What it does

- Starts Waydroid in portrait, unfolded-fold, and landscape profiles.
- Returns Waydroid to its native full-screen configuration.
- Saves and reopens the most recently selected custom display size.
- Shares any host directory with Android storage using a local bind mount.
- Connects `adb` to Waydroid through Waydroid's private host-only bridge.
- Installs APKs, launches packages, clears app data, captures screenshots,
  records the screen, and streams logcat.
- Sends Android Back, Home, Recents, Power, volume, and related hardware-key
  events using readable action names.

## Requirements

- A Linux desktop session with Waydroid installed and initialized.
- Bash, `realpath`, `timeout`, `mountpoint`, and `sudo`.
- Android SDK Platform Tools (`adb`) installed in either:
  - `$HOME/Android/Sdk/platform-tools`, or
  - a directory already included in `PATH`.

The `mount` and `unmount` commands require sudo because Linux bind mounts are
system-level operations. Other commands run as the logged-in user.

## Installation

For a development checkout, keep the repository anywhere convenient and add
its directory to `PATH`:

```bash
export PATH="$HOME/.local/bin/wayvd:$PATH"
```

This exposes both `wayvd` and `wayvd-ui` directly from the checkout, so local
changes take effect immediately. Add the export to your shell profile to make
it persistent, then verify the command:

```bash
wayvd --help
```

## Graphical interface

`wayvd-ui.py` is an optional GTK4/libadwaita frontend for the command-line
utility. It delegates every action to `wayvd`; the CLI remains the source of
truth for profiles, folder mounts, ADB, and Android controls.

The GUI is executable directly from the checkout:

```bash
wayvd-ui
```

Install its desktop entry:

```bash
install -Dm644 io.github.haroncxx.wayvd.desktop \
  ~/.local/share/applications/io.github.haroncxx.wayvd.desktop
sudo install -Dm755 wayvd-mount-helper /usr/local/libexec/wayvd-mount-helper
sudo install -Dm644 io.github.haroncxx.wayvd.policy \
  /usr/share/polkit-1/actions/io.github.haroncxx.wayvd.policy
```

It requires the Python GTK4 and libadwaita bindings, provided as
`python3-gi`, `gir1.2-gtk-4.0`, and `gir1.2-adw-1` on Debian/Ubuntu systems.
Launch it from the app menu or with:

```bash
wayvd-ui
```

Folder mount and unmount operations in the UI use PolicyKit. GNOME displays
its standard system authentication dialog when elevation is required; the UI
never reads or stores a password. The privileged helper is limited to bind
mounts inside the invoking user's Waydroid shared-media directory.

## Starting Waydroid

```bash
wayvd start [PROFILE]
```

Changing profiles stops the current Waydroid session before starting the next
one, because Waydroid reads display overrides during session startup.

| Profile | Resolution | Description |
|---|---:|---|
| `portrait` | `432x969` | Pixel 10 Pro Fold cover display in portrait |
| `fold` | `920x954` | Pixel 10 Pro Fold inner display in portrait |
| `landscape` | `969x432` | Pixel 10 Pro Fold cover display in landscape |
| `fold-landscape` | `954x920` | Pixel 10 Pro Fold inner display in landscape |
| `default` | Native | Clears display overrides and uses Waydroid's native configuration |
| `last` | Saved | Reopens the most recently selected non-default resolution |
| `size WIDTHxHEIGHT` | Custom | Starts with an explicit display resolution |

Examples:

```bash
wayvd start
wayvd start fold
wayvd start landscape
wayvd start default
wayvd start size 600x900
wayvd start last
```

Stop Waydroid cleanly:

```bash
wayvd stop
```

Inspect its state and configured display override:

```bash
wayvd status
wayvd profiles
```

## Sharing host folders

Share a host directory with Android's internal shared storage:

```bash
wayvd mount HOST_PATH [ANDROID_NAME]
```

The optional `ANDROID_NAME` becomes the directory name shown by Android's
Files app under **Internal storage**. When omitted, `wayvd` uses the basename
of `HOST_PATH`.

```bash
wayvd mount ~/Downloads
wayvd mount ~/Projects/Android SharedProjects
```

Those examples appear in Android as:

```text
/storage/emulated/0/Downloads
/storage/emulated/0/SharedProjects
```

The mount is immediate and bidirectional: Android and the host access the
same files. It is not a copy or synchronization service.

Check or remove a mount by Android-visible name:

```bash
wayvd mount-status Downloads
wayvd unmount Downloads

wayvd mount-status SharedProjects
wayvd unmount SharedProjects
```

Avoid mounting your entire home directory unless you deliberately want Android
applications with shared-storage access to see its contents. A dedicated
directory, such as `~/WaydroidShare`, is safer:

```bash
mkdir -p ~/WaydroidShare
wayvd mount ~/WaydroidShare
```

## Local ADB

Connect the Android SDK's `adb` to Waydroid:

```bash
wayvd adb
adb devices
```

Waydroid uses a private virtual bridge between the host and its container.
This is ADB over a local virtual network, not Android Wireless debugging:

- it works offline;
- it does not require Wi-Fi, Ethernet, or a router;
- it does not expose an ADB service on the physical LAN;
- it is not physical USB passthrough, because Waydroid is a container rather
  than a USB gadget device.

The first connection can display Android's **Allow USB debugging?** RSA
authorization prompt. Unlock Waydroid and approve it. If the prompt does not
appear, revoke USB debugging authorizations inside Android Developer options,
then run `adb kill-server` followed by `wayvd adb`.

## Application and debugging commands

All commands below target Waydroid's local ADB device specifically, even when
other Android devices or emulators are connected.

```bash
# Install an APK.
wayvd install app/build/outputs/apk/debug/app-debug.apk

# Launch an installed package.
wayvd launch com.example.app

# Reset an app to its first-run state.
wayvd clear com.example.app

# Capture the current display.
wayvd screenshot
wayvd screenshot ~/Pictures/example.png

# Record until Ctrl-C is pressed or Android's recording limit is reached.
wayvd record ~/Videos/demo.mp4

# Stream Android logs. Arguments are passed directly to logcat.
wayvd logcat
wayvd logcat '*:E'
```

Without an explicit file path, screenshots are saved to:

```text
~/Pictures/waydroid.png
```

## AVD-style hardware controls

Send readable Android button actions:

```bash
wayvd key back
wayvd key home
wayvd key recents
wayvd key volume-up
wayvd key volume-down
wayvd key mute
wayvd key power
wayvd key wake
wayvd key sleep
wayvd key menu
```

These affect Waydroid, not the host operating system. For example,
`wayvd key volume-up` changes Android media volume rather than your laptop's
desktop volume. They can be assigned as GNOME custom keyboard shortcuts. In
the GUI, hold **Volume Up** or **Volume Down** to repeat the action; Android
enforces its own minimum and maximum volume bounds.

## Help

```bash
wayvd --help
```

Use that output as the authoritative local reference for the installed
version's commands and arguments.
