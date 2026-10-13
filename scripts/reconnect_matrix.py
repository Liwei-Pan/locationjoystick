#!/usr/bin/env python3
"""Reliability-proof harness for the Bluetooth reconnect tap (docs/features/bluetooth-reconnect-tap.md).

Subcommands (all stdlib, adb on PATH; raw results go to scripts/reconnect-matrix/, gitignored):
    run --serial S --mac-suffix D3:24 --device-slug pixel7 --block a|b|c|d|e --cycles 20
        Operator disconnects the companion and presses Enter; the harness waits for the app's
        check (one per 5-minute loop), then confirms the link with dumpsys. One row per cycle.
    already-on --serial S --mac-suffix D3:24 --device-slug pixel7 --checks 12
        Companion connected; every check must read ON, tap nothing and return NOT_OFF.
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


def watch_app_log(serial, checks_wanted, timeout_s):
    """Stream the app's tagged log from now on until N check lines arrive or the timeout passes."""
    subprocess.run(["adb", "-s", serial, "logcat", "-c"], check=False)
    proc = subprocess.Popen(
        ["adb", "-s", serial, "logcat", "-v", "brief", "-s", f"{TAG}:D"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    q = queue.Queue()
    threading.Thread(target=lambda: [q.put(x) for x in proc.stdout], daemon=True).start()
    lines, checks = [], 0
    deadline = time.monotonic() + timeout_s
    try:
        while checks < checks_wanted and time.monotonic() < deadline:
            try:
                line = q.get(timeout=1)
            except queue.Empty:
                continue
            if TAG in line:
                lines.append(line.rstrip())
                if CHECK_RE.search(line):
                    checks += 1
    finally:
        proc.terminate()
    return lines


def append_row(row):
    OUT.mkdir(parents=True, exist_ok=True)
    with ROWS.open("a") as f:
        f.write(json.dumps(row) + "\n")


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
