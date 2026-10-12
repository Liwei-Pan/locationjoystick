# Bluetooth Reconnect Tap

**Status:** Implemented (off by default). Reliability proof is still open (see "Open work").

## Goal

Reconnect a Bluetooth companion device by automating the on-screen tap in the other app, with the lowest practical chance of detection. The tap is the only automated action; the Bluetooth connection itself is never driven through the Bluetooth API.

Closes only when proven 100% reliable over repeated disconnect and reconnect cycles on real devices (see the follow-up task in "Open work" below).

## Hard rule

Nothing is injected into, hooked into, patched in, or read from the target app's process or memory. Any approach that needs that is out of scope and is recorded as not possible below.

The only data used from the target app is the pixels on screen, captured the same way the compass feature already captures them (`takeScreenshot`, see [Compass Orientation](tap-to-walk.md)).

## Comparison of tap delivery paths

Columns: what the target app can observe, what the path needs, Play policy fit, verdict.

| Path | What the target app can observe | Required permissions or setup | Play policy fit | Verdict |
|---|---|---|---|---|
| **A. Accessibility gesture dispatch** (`AccessibilityService.dispatchGesture`) | Enabled-service list (already non-empty on real devices, see "Observed on test device"). Touch events carry `MotionEvent.FLAG_IS_ACCESSIBILITY_EVENT` on API 34 and later. Event device id, source and tool type are those of the injected gesture stream. Timing is whatever we choose. | Accessibility service already enabled for the compass feature. Needs `android:canPerformGestures="true"` in the service XML. | Accessibility disclosure already shipped for screenshots. Gesture use needs the disclosure updated to name the tap, shipped before the capability is reachable. Main residual review risk. | **Chosen** |
| **B. Shell or privileged input** (`input tap` via wireless ADB, Shizuku, root) | Developer options and ADB state are visible. A second helper app (Shizuku) is installable and enumerable. Events come from the shell or a privileged process. | Developer mode or a second app, plus a setup flow the app does not have. | Adds a setup burden and a dependency outside the app; not offline-first friendly. | Rejected |
| **C. Node click** (`AccessibilityNodeInfo.performAction(ACTION_CLICK)`) | Needs the target app's view tree, which the hard rule forbids reading. | Needs `canRetrieveWindowContent`, which the service does not set. Game surfaces expose few or no nodes anyway. | Reads another app's content; weakest policy fit. | Rejected |
| **D. Other platform paths** (hidden `InputManager.injectInputEvent`, `UiAutomation`, overlay pass-through) | Injection needs the signature-level `INJECT_EVENTS` permission, which a Play app cannot hold. `UiAutomation` runs only from a shell instrumentation process and conflicts with an enabled accessibility service. A `SYSTEM_ALERT_WINDOW` overlay cannot synthesize touches for another window; `FLAG_NOT_TOUCHABLE` only forwards real user touches. | Not obtainable for a normal app. | Not applicable. | Not possible |

Bluetooth API reconnect is out of scope by the task definition.

## Chosen path

**Accessibility gesture dispatch** via the existing `CompassAccessibilityService`.

Why:

- The service is already enabled, disclosed and screenshot-capable (`feature/widget/impl/.../CompassAccessibilityService.kt`, `app/src/main/res/xml/compass_accessibility_service.xml`). The tap adds no new permission prompt, no new process, no new dependency, and no new entry in the enabled-services list a target app could enumerate.
- The app is offline-first with no extra installs (see `AGENTS.md`, Project table).
- It is the only path that reaches the target app without injection, shell access or node reads.

Implemented changes:

- `android:canPerformGestures="true"` in `compass_accessibility_service.xml`.
- Disclosure copy (`compass_disclosure_*`, `accessibility_service_description`) names the periodic screenshot and the tap, and a separate `reconnect_tap_disclosure_accepted` flag forces re-acceptance.
- No manual trigger. While `reconnect_tap_enabled` (Settings > Menus > Reconnect accessory, default off) and both disclosure flags (`getReconnectTapDisclosureAccepted()`, `getCompassDisclosureAccepted()`) are true, `CompassAccessibilityService` runs a check every `ReconnectTapConstants.CHECK_INTERVAL_MS` (5 min, first check one interval after the loop starts). Turning any flag off cancels the loop at once.
- The run logic is `runReconnectTap` in `ReconnectTapRunner.kt` (fake-driven unit tests); the detector is `ReconnectControlDetector`. The settings and consent flags are device-local and excluded from export.

## What the target app can observe on the chosen path

1. **Enabled-service enumeration** (`Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES`, `AccessibilityManager.getEnabledAccessibilityServiceList`). The app's service is already listed when the compass feature is enabled. Marginal detectability from this path is zero.
2. **Event flags.** On API 34 and later, gesture-originated events carry `MotionEvent.FLAG_IS_ACCESSIBILITY_EVENT`. This is documented platform behavior, not yet confirmed by a probe on this project's devices (see "Pending measurements").
3. **Event attributes.** Device id, source, tool type, pressure and size of the injected stream. Expected to differ from a finger; the probe in "Pending measurements" records the actual values.
4. **Timing regularity.** Controlled by the tap policy and human-like parameters below.

## Locate and classify the control

- **Region.** Search the same top-right region the compass uses (`AppConstants.CompassTrackingConstants.SEARCH_X_MIN_PCT` and `SEARCH_Y_MAX_PCT`), reused rather than duplicated. The HUD shifted up in the latest build of the target app, so the region is re-measured on test devices and the measured fractions recorded in the doc. **Pending measurement.**
- **Locate by shape and color, not by text.** Find the control as a colored blob within icon-size bounds, the same approach as `findBestIconBlob` in the compass service. This is language-independent.
- **Size.** Bounds are fractions of the screen's short side, so they hold across screen sizes.
- **Two states.** Classification uses the blob's dominant color (HSV hue, saturation, value ranges): exactly "off" and "on". The measured HSV ranges for each state, per device and per theme (light, dark), brightness (min, max) and night mode, are recorded here. **Pending measurement.**
- **Third value.** Classification returns "unknown" when the blob is not found or its color is outside both measured ranges. "Unknown" never taps.

## Tap policy

- Tap only when the control reads "off", confirmed by two consecutive screenshots 400 ms apart. Never tap on "on" or "unknown".
- After a tap, wait 4 s, then re-screenshot and re-classify.
- At most 3 taps per run, with a 5 s gap between failed attempts. Abort and report after the third failure.

## Human-like timing and jitter

Values live in `AppConstants.ReconnectTapConstants`, drawn fresh for every tap from `kotlin.random.Random`:

- Pre-tap delay after a confirmed "off": uniform 700 to 2200 ms.
- Tap position: Gaussian around the blob center, sigma 1.1% of screen width (about 15% of the ball), each axis clamped to 2.5% of screen width so the tap stays inside the ball.
- Gesture duration: uniform 45 to 130 ms.

The implement task may tune these only against evidence from the reliability proof.

## Observed on test device

Recorded on the one attached device during this investigation:

- Pixel, Android API 36 (`ro.build.version.sdk` = 36), serial 32221FDH2001SU.
- Enabled accessibility services already include a third-party automation app's service. This means the enumeration row above is already non-empty on a real device, so adding the app's service does not make the device stand out in a new way.

## Measured on screenshots

Source: two 864x1920 screenshots of the target app on a night map, one per state. They are the fixtures of `ReconnectControlDetectorTest` (`feature/widget/impl/src/test/resources/reconnect/`). Detector: `ReconnectControlDetector` (pure over ARGB pixels).

- **Position.** Ball center at about 91.5% of width and 12.5% of height. Diameter about 7.2% of width. It is inside the compass search window (right 45%, top 35%).
- **ON.** Saturated red upper half, white lower half, pure green center dot (about 0, 252, 7). Signal arcs beside the ball.
- **OFF.** Dimmed ball: flat rose upper half (about 150, 97, 122), flat light-blue ring and lower half (about 86, 156, 212), dark-blue center. No green dot.
- **Detector rule.** ON = icon-sized green blob with red above it. OFF = icon-sized light-blue blob with rose pixels inside it. Anything else returns null, and null never taps.
- **Not yet covered.** Day theme, other brightness levels, other screen sizes, a "connecting" look, and screens without the control (only one non-HUD fixture so far).

## Pending measurements

These need the target app's HUD in both states, a companion device, and more than one device or theme. They were not available in the investigation run and are marked pending rather than estimated.

- Control bounding box and OFF/ON colors on more devices, in the day theme, and at other brightness levels.
- Probe of `MotionEvent` flags, source, device id, tool type, pressure and size for a real finger tap, `adb shell input tap`, and `dispatchGesture` taps, on API 34 and later.

## Open risks

- **Play review.** Gesture use under a service that declares `isAccessibilityTool="false"` is a review risk. Mitigation: off by default, separate explicit acceptance, disclosure names the periodic screenshot and tap, never taps on unknown.
- **Target-app changes.** A HUD move or color change breaks classification. The "unknown" value prevents false taps, but reconnect then fails until the ranges are re-measured.

## Open work

- `prove-bluetooth-reconnect-tap-100-reliable-on-real-devices`: repeated disconnect and reconnect matrix on real devices.
