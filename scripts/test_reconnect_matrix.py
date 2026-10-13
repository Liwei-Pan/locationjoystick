#!/usr/bin/env python3
"""Self-check for reconnect_matrix.py. Run directly: python3 scripts/test_reconnect_matrix.py"""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("reconnect_matrix", Path(__file__).parent / "reconnect_matrix.py")
rm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rm)

# Lines copied from a real `adb shell dumpsys bluetooth_manager` (address masked, spelling as printed).
DUMP = """\
  10-12 22:59:07.821 [XX:XX:XX:XX:D3:24] aclStateChangeCallback: State:Connected, tranport:LE, Address type:Public, reason:0, Adapter state:ON
  10-12 23:59:08.146 [XX:XX:XX:XX:D3:24] aclStateChangeCallback: State:Disconnected, transport:LE, Address type:Public, reason:22, Adapter state:ON
  10-13 00:10:01.000 [XX:XX:XX:XX:AB:CD] aclStateChangeCallback: State:Connected, tranport:LE, Address type:Public, reason:0, Adapter state:ON
Connected devices: 1
"""


def test_parse_acl_state_returns_last_state_for_suffix():
    assert rm.parse_acl_state(DUMP, "D3:24") == "Disconnected"
    assert rm.parse_acl_state(DUMP, "AB:CD") == "Connected"
    assert rm.parse_acl_state(DUMP, "00:00") is None


def test_parse_connected_count():
    assert rm.parse_connected_count(DUMP) == 1
    assert rm.parse_connected_count("no devices here") is None


def test_classify_logs_reconnected_run():
    lines = [
        "I CompassAccessibilitySvc: Reconnect read: OFF",
        "I CompassAccessibilitySvc: Reconnect tap: 791,240,120",
        "I CompassAccessibilitySvc: Reconnect read: ON",
        "I CompassAccessibilitySvc: Reconnect check: RECONNECTED",
    ]
    assert rm.classify_logs(lines) == {"outcome": "RECONNECTED", "taps": 1, "reads": ["OFF", "ON"]}


def test_classify_logs_failed_run():
    lines = [
        "I CompassAccessibilitySvc: Reconnect read: OFF",
        "I CompassAccessibilitySvc: Reconnect tap: 791,240,120",
        "I CompassAccessibilitySvc: Reconnect read: OFF",
        "I CompassAccessibilitySvc: Reconnect check: FAILED",
    ]
    info = rm.classify_logs(lines)
    assert info["outcome"] == "FAILED" and info["taps"] == 1


def test_classify_logs_already_on_run_has_no_taps():
    lines = [
        "I CompassAccessibilitySvc: Reconnect read: ON",
        "I CompassAccessibilitySvc: Reconnect check: NOT_OFF",
    ]
    info = rm.classify_logs(lines)
    assert info == {"outcome": "NOT_OFF", "taps": 0, "reads": ["ON"]}


def test_cycle_passes_only_when_reconnected_and_connected():
    assert rm.cycle_passes("RECONNECTED", True)
    assert not rm.cycle_passes("RECONNECTED", False)
    assert not rm.cycle_passes("NOT_OFF", True)
    assert not rm.cycle_passes("FAILED", True)
    assert not rm.cycle_passes(None, True)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok {t.__name__}")
    print(f"{len(tests)} passed")
