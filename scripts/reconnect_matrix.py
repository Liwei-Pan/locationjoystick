#!/usr/bin/env python3
"""Reliability-proof harness for the Bluetooth reconnect tap (docs/features/bluetooth-reconnect-tap.md).

Subcommands (stdlib plus adb on PATH; `auto` also needs numpy and Pillow; raw results go to
scripts/reconnect-matrix/, gitignored):
    run --serial S --mac-suffix D3:24 --device-slug pixel7 --block a|b|c|d|e --cycles 20
        Operator disconnects the companion and presses Enter; the harness waits for the app's
        check (one per 5-minute loop), then confirms the link with dumpsys. One row per cycle.
    already-on --serial S --mac-suffix D3:24 --device-slug pixel7 --checks 12
        Companion connected; every check must read ON, tap nothing and return NOT_OFF.
    auto --serial S --mac-suffix D3:24 --device-slug pixel7 --block a|b|d|e --cycles 100
        No operator per cycle: cycles the phone's Bluetooth adapter to drop the companion link,
        waits for the app's check, and saves a before and after screenshot per cycle named with
        its host-side class (ON/OFF/NONE) for manual review in scripts/reconnect-matrix/shots/.
        Block c needs an operator (screen off, foreground the game), so it stays in `run`.
        At 300 s per loop a 100-cycle block takes up to about 8 hours.
    corpus --serial S --device-slug pixel7 --state on|off --theme day|night --brightness min|max
        Captures one labelled screencap into scripts/reconnect-matrix/corpus/.
    summary
        Prints per-device/per-block pass counts as a markdown table.

Self-check:
    python3 scripts/test_reconnect_matrix.py
"""

import argparse
import json
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "reconnect-matrix"
ROWS = OUT / "cycles.jsonl"
TAG = "CompassAccessibilitySvc"
LOOP_INTERVAL_S = 300  # AppConstants.ReconnectTapConstants.CHECK_INTERVAL_MS
CYCLE_TIMEOUT_S = 390  # one loop interval + up to 3 taps with settles

ACL_RE = re.compile(r"aclStateChangeCallback: State:(Connected|Disconnected)")
COUNT_RE = re.compile(r"Connected devices:\s*(\d+)")
READ_RE = re.compile(r"Reconnect read: (ON|OFF|NONE)")
TAP_RE = re.compile(r"Reconnect tap: ")
CHECK_RE = re.compile(r"Reconnect check: (NOT_OFF|RECONNECTED|FAILED)")
TERMINAL_RE = re.compile(r"Reconnect check: (RECONNECTED|FAILED)")
TOGGLE_SETTLE_S = 5  # the app needs at least 3 s to load after each connect or disconnect
SHOTS = OUT / "shots"


def parse_acl_state(dumpsys_text, mac_suffix):
    """Last ACL state for the companion (address is masked, so match the visible tail, e.g. 'D3:24]')."""
    state = None
    for line in dumpsys_text.splitlines():
        if f"{mac_suffix}]" in line:
            m = ACL_RE.search(line)
            if m:
                state = m.group(1)
    return state


def parse_connected_count(dumpsys_text):
    matches = COUNT_RE.findall(dumpsys_text)
    return int(matches[-1]) if matches else None


def classify_logs(lines):
    """Summarise one run's app log lines: final check result, tap count, reads in order."""
    outcome = None
    taps = 0
    reads = []
    for line in lines:
        if (m := CHECK_RE.search(line)):
            outcome = m.group(1)
        if TAP_RE.search(line):
            taps += 1
        if (m := READ_RE.search(line)):
            reads.append(m.group(1))
    return {"outcome": outcome, "taps": taps, "reads": reads}


def cycle_passes(outcome, connected):
    """Plan rule 7: the app reports RECONNECTED and dumpsys confirms the companion is Connected."""
    return outcome == "RECONNECTED" and connected is True


# Port of ReconnectControlDetector.kt (same constants, same rules, ON checked before OFF).
# Keep in sync with the Kotlin detector; its fixtures are the self-check's fixtures.
SEARCH_X_MIN_PCT = 0.55  # AppConstants.CompassTrackingConstants
SEARCH_Y_MAX_PCT = 0.35
COLOR_TOLERANCE = 14
OFF_BLUE = (86, 156, 212)
OFF_ROSE = (150, 97, 122)
MIN_DOT_FRACTION, MAX_DOT_FRACTION = 0.012, 0.045
MIN_HALF_FRACTION, MAX_HALF_FRACTION = 0.04, 0.10
MIN_ABOVE_SHARE = 0.1


def _blobs(mask):
    """4-connected components of True pixels as (left, top, right, bottom) boxes."""
    import numpy as np

    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    out = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        seen[y, x] = True
        stack = [(int(y), int(x))]
        l = r = int(x)
        t = b = int(y)
        while stack:
            cy, cx = stack.pop()
            l, r, t, b = min(l, cx), max(r, cx), min(t, cy), max(b, cy)
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        out.append((l, t, r, b))
    return out


def _fits(blob, screen_width, min_fraction, max_fraction):
    l, t, r, b = blob
    w, h = r - l + 1, b - t + 1
    return w >= screen_width * min_fraction and w <= screen_width * max_fraction and h * 3 >= w and h <= w * 2


def classify_screenshot(png_bytes):
    """Return "ON", "OFF" or "NONE" for the companion control in a screenshot (never a tap decision)."""
    import io

    import numpy as np
    from PIL import Image

    rgb = np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB"), dtype=np.int32)
    full_h, width = rgb.shape[:2]
    x0 = int(width * SEARCH_X_MIN_PCT)
    y1 = int(full_h * SEARCH_Y_MAX_PCT)
    region = rgb[:y1, x0:]
    r, g, b = region[..., 0], region[..., 1], region[..., 2]

    def near(ref):
        return np.all(np.abs(region - np.array(ref)) <= COLOR_TOLERANCE, axis=-1)

    red = (r > 200) & (g < 60) & (b < 60)
    dot = (g > 200) & (r < 80) & (b < 80)
    for blob in _blobs(dot):
        l, t, rt, bt = blob
        if not _fits(blob, width, MIN_DOT_FRACTION, MAX_DOT_FRACTION):
            continue
        band = red[max(0, t - 2 * (rt - l + 1)):t, l:rt + 1]
        if band.size and band.sum() >= band.size * MIN_ABOVE_SHARE:
            return "ON"

    rose = near(OFF_ROSE)
    for blob in _blobs(near(OFF_BLUE)):
        if not _fits(blob, width, MIN_HALF_FRACTION, MAX_HALF_FRACTION):
            continue
        l, t, rt, bt = blob
        box = rose[t:bt + 1, l:rt + 1]
        if box.sum() * 10 >= box.size:
            return "OFF"
    return "NONE"


def adb(serial, *args, text=True):
    return subprocess.run(["adb", "-s", serial, *args], capture_output=True, text=text, check=False).stdout


def link_state(serial, mac_suffix):
    dump = adb(serial, "shell", "dumpsys", "bluetooth_manager")
    return parse_acl_state(dump, mac_suffix), parse_connected_count(dump)


def wait_for_link(serial, mac_suffix, want, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state, _ = link_state(serial, mac_suffix)
        if state == want:
            return True
        time.sleep(2)
    return False


def open_log_stream(serial):
    """Clear the app's log and start streaming it. Lines queue up until collect_until reads them."""
    subprocess.run(["adb", "-s", serial, "logcat", "-c"], check=False)
    proc = subprocess.Popen(
        ["adb", "-s", serial, "logcat", "-v", "brief", "-s", f"{TAG}:D"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    q = queue.Queue()
    threading.Thread(target=lambda: [q.put(x) for x in proc.stdout], daemon=True).start()
    return proc, q


def collect_until(stream, done, timeout_s):
    """Read tagged lines from an open stream until done(line) is true or the timeout passes."""
    _, q = stream
    lines = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            line = q.get(timeout=1)
        except queue.Empty:
            continue
        if TAG in line:
            lines.append(line.rstrip())
            if done(line):
                break
    return lines


def watch_app_log(serial, checks_wanted, timeout_s):
    """Stream the app's tagged log from now on until N check lines arrive or the timeout passes."""
    stream = open_log_stream(serial)
    checks = 0

    def count_check(line):
        nonlocal checks
        if CHECK_RE.search(line):
            checks += 1
        return checks >= checks_wanted

    try:
        return collect_until(stream, count_check, timeout_s)
    finally:
        stream[0].terminate()


def append_row(row):
    OUT.mkdir(parents=True, exist_ok=True)
    with ROWS.open("a") as f:
        f.write(json.dumps(row) + "\n")


def toggle_adapter(serial):
    """Cycle the phone's Bluetooth adapter off and on. False when either wait times out."""
    def bt(*args):
        cmd = ["adb", "-s", serial, "shell", "cmd", "bluetooth_manager", *args]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)

    try:
        bt("disable")
        if bt("wait-for-state:STATE_OFF").returncode != 0:
            return False
        bt("enable")
        return bt("wait-for-state:STATE_ON").returncode == 0
    except subprocess.TimeoutExpired:
        return False


def take_screenshot(serial):
    return subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"], capture_output=True, check=True).stdout


def save_shot(png, device, block, cycle, phase, cls):
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{device}_{block}_{cycle:03d}_{phase}_{cls}.png"
    path.write_bytes(png)
    return str(path.relative_to(ROOT))


def cmd_auto(args):
    for cycle in range(1, args.cycles + 1):
        stream = open_log_stream(args.serial)
        try:
            toggle_ok = toggle_adapter(args.serial)
            acl_dropped = wait_for_link(args.serial, args.mac_suffix, "Disconnected", 60)
            time.sleep(TOGGLE_SETTLE_S)
            before = take_screenshot(args.serial)
            before_class = classify_screenshot(before)
            before_shot = save_shot(before, args.device_slug, args.block, cycle, "before", before_class)
            toggle_ok = toggle_ok and before_class == "OFF"

            started = time.monotonic()
            lines = collect_until(stream, lambda line: bool(TERMINAL_RE.search(line)), CYCLE_TIMEOUT_S + 60)
            seconds = round(time.monotonic() - started, 1)
        finally:
            stream[0].terminate()
        info = classify_logs(lines)
        connected = wait_for_link(args.serial, args.mac_suffix, "Connected", 30)
        time.sleep(TOGGLE_SETTLE_S)
        after = take_screenshot(args.serial)
        after_class = classify_screenshot(after)
        after_shot = save_shot(after, args.device_slug, args.block, cycle, "after", after_class)
        row = {
            "device": args.device_slug, "block": args.block, "cycle": cycle,
            "outcome": info["outcome"], "taps": info["taps"], "reads": info["reads"],
            "seconds": seconds, "connected": connected, "acl_dropped": acl_dropped,
            "toggle_ok": toggle_ok, "before_class": before_class, "before_shot": before_shot,
            "after_class": after_class, "after_shot": after_shot,
            "pass": toggle_ok and cycle_passes(info["outcome"], connected) and after_class == "ON",
            "at": datetime.now(timezone.utc).isoformat(),
        }
        append_row(row)
        print(f"  -> outcome={row['outcome']} toggle_ok={toggle_ok} before={before_class} "
              f"after={after_class} connected={connected} pass={row['pass']}")


def cmd_run(args):
    for cycle in range(1, args.cycles + 1):
        input(f"[{args.block} {cycle}/{args.cycles}] Disconnect the companion, confirm the control reads off, then press Enter: ")
        if not wait_for_link(args.serial, args.mac_suffix, "Disconnected", 60):
            print("  companion ACL never reached Disconnected; row not recorded", file=sys.stderr)
            continue
        if args.block == "c":
            input("  Turn the screen off, then press Enter (harness waits 60 s before waking): ")
            time.sleep(60)
            adb(args.serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
            input("  Bring the game back to the foreground, then press Enter: ")
        started = time.monotonic()
        lines = watch_app_log(args.serial, checks_wanted=1, timeout_s=CYCLE_TIMEOUT_S)
        seconds = round(time.monotonic() - started, 1)
        info = classify_logs(lines)
        connected = wait_for_link(args.serial, args.mac_suffix, "Connected", 30)
        row = {
            "device": args.device_slug, "block": args.block, "cycle": cycle,
            "outcome": info["outcome"], "taps": info["taps"], "reads": info["reads"],
            "seconds": seconds, "connected": connected,
            "pass": cycle_passes(info["outcome"], connected),
            "at": datetime.now(timezone.utc).isoformat(),
        }
        append_row(row)
        print(f"  -> outcome={row['outcome']} taps={row['taps']} connected={connected} pass={row['pass']}")


def cmd_already_on(args):
    state, _ = link_state(args.serial, args.mac_suffix)
    if state != "Connected":
        sys.exit(f"companion is not Connected (ACL state: {state}); connect it first")
    lines = watch_app_log(args.serial, checks_wanted=args.checks, timeout_s=args.checks * LOOP_INTERVAL_S + 120)
    # Split the log at each check result so each check is judged on its own reads and taps.
    segment, checks = [], []
    for line in lines:
        segment.append(line)
        if CHECK_RE.search(line):
            checks.append(classify_logs(segment))
            segment = []
    for i, info in enumerate(checks, 1):
        ok = info["outcome"] == "NOT_OFF" and info["taps"] == 0 and bool(info["reads"]) and all(r == "ON" for r in info["reads"])
        append_row({"device": args.device_slug, "block": "already-on", "cycle": i,
                    "outcome": info["outcome"], "taps": info["taps"], "reads": info["reads"],
                    "pass": ok, "at": datetime.now(timezone.utc).isoformat()})
    print(f"{sum(1 for i in checks if i['taps'] == 0)}/{len(checks)} checks with zero taps; wanted {args.checks}")


def cmd_corpus(args):
    corpus = OUT / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    name = f"{args.state}_{args.theme}_{args.brightness}_{args.device_slug}.png"
    with (corpus / name).open("wb") as f:
        f.write(subprocess.run(["adb", "-s", args.serial, "exec-out", "screencap", "-p"], capture_output=True, check=True).stdout)
    print(f"wrote {corpus / name}")


def cmd_summary(_args):
    if not ROWS.exists():
        sys.exit("no results yet")
    counts = {}
    for line in ROWS.read_text().splitlines():
        row = json.loads(line)
        key = (row["device"], row["block"])
        passed, total = counts.get(key, (0, 0))
        counts[key] = (passed + bool(row["pass"]), total + 1)
    print("| device | block | pass / total |")
    print("|---|---|---|")
    for (device, block), (passed, total) in sorted(counts.items()):
        print(f"| {device} | {block} | {passed} / {total} |")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--serial", required=True)
    r.add_argument("--mac-suffix", required=True)
    r.add_argument("--device-slug", required=True)
    r.add_argument("--block", required=True, choices=list("abcde"))
    r.add_argument("--cycles", type=int, default=20)
    r.set_defaults(fn=cmd_run)

    au = sub.add_parser("auto")
    au.add_argument("--serial", required=True)
    au.add_argument("--mac-suffix", required=True)
    au.add_argument("--device-slug", required=True)
    au.add_argument("--block", required=True, choices=list("abde"))
    au.add_argument("--cycles", type=int, default=100)
    au.set_defaults(fn=cmd_auto)

    a = sub.add_parser("already-on")
    a.add_argument("--serial", required=True)
    a.add_argument("--mac-suffix", required=True)
    a.add_argument("--device-slug", required=True)
    a.add_argument("--checks", type=int, default=12)
    a.set_defaults(fn=cmd_already_on)

    c = sub.add_parser("corpus")
    c.add_argument("--serial", required=True)
    c.add_argument("--device-slug", required=True)
    c.add_argument("--state", required=True, choices=["on", "off"])
    c.add_argument("--theme", required=True, choices=["day", "night"])
    c.add_argument("--brightness", required=True, choices=["min", "max"])
    c.set_defaults(fn=cmd_corpus)

    s = sub.add_parser("summary")
    s.set_defaults(fn=cmd_summary)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
