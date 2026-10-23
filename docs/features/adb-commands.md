# adb Commands

A broadcast receiver that lets a computer (or any shell with the adb `DUMP` permission) run app commands via `adb shell am broadcast`. Commands: teleport, and show/hide the floating joystick and widget.

Key files: `app/.../AdbCommandReceiver.kt`, `app/.../AdbCommand.kt` (parser), `app/src/main/AndroidManifest.xml` (`<receiver>`), `core/common/.../AppConstants.kt` (`AdbCommandConstants`).

## Behaviour

- Receiver: `AdbCommandReceiver`, exported, protected by `android.permission.DUMP`. Only the adb shell and the system hold that permission, so other apps cannot send these broadcasts.
- Teleport action: `com.locationjoystick.app.action.TELEPORT`, extras `lat` and `lon` (decimal degrees).
- Teleport calls `MapController.teleportTo()` while spoofing is running, the same path as the map and the Control API. No confirmation sheet.
- When spoofing is idle, the command starts spoofing at the target instead (`MapController.startSpoofingAt()`), because an idle service only records a position update and never starts the mock provider. The target is also saved as the last location.
- Hide Teleport is ignored, matching the Control API.
- Cooldown is not enforced. Teleport runs even inside the cooldown window.
- Invalid input (missing, non-numeric, or out of range) is rejected and logged. The reply shows the reason in the `am` output.
- The reply (`result=-1, data="ok"`) only means the command was accepted. To confirm the position changed, check `adb shell dumpsys location` for a `gps provider [mock]` entry.
- Android 12+ may block starting the foreground service from the background. Open the app (or start spoofing from it) once before scripting long runs.

## Command

```
adb shell am broadcast -a com.locationjoystick.app.action.TELEPORT -n com.locationjoystick.app/.AdbCommandReceiver --es lat 25.0330 --es lon 121.5654
```

Prefer `--es` (String): it works on every Android version and keeps full precision. Android 10's `am` rejects `--ed` (Double), and `--ef` (Float) loses precision (about 0.2 m). `--ei` (Int) is also accepted but only useful for whole degrees. Pass `-n` so the broadcast reaches the receiver even when the app is not running.

## Show / hide the floating overlays

```
adb shell am broadcast -a com.locationjoystick.app.action.OVERLAY -n com.locationjoystick.app/.AdbCommandReceiver --ez visible false
```

`--ez visible true` brings them back. The joystick and the widget cover part of the game map (the joystick sits on the left edge), which hides the mushrooms under it when the screen is read by a program. The overlay services listen for hide/show on a receiver that is not exported, so only this app can send to it; `AdbCommandReceiver` relays the command. `--es visible false` (or `0`, `no`, `hide`) works too.

## Adding a command

1. Add the action and extra names to `AdbCommandConstants`.
2. Add a subtype to `AdbCommand` and a branch in `parseAdbCommand`.
3. Handle it in `AdbCommandReceiver.onReceive` by calling the matching `MapController` method.
4. Add an intent-filter action in the manifest `<receiver>`.
5. Add tests to `AdbCommandTest`.

## Security

Protected by the `DUMP` permission, which ordinary apps cannot be granted. Anyone who can run adb on the device (USB debugging on, computer authorized) can send these commands. Unlike the Control API, this needs no key and works without the Control API toggle.
