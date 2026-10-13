#!/usr/bin/env python3
"""Bearing-registration harness for tap-to-walk: game-map screenshot -> rotation + scale against our own map.

Step 1 of the investigation: pure geometry helpers plus one registration method (log-polar phase
correlation on the FFT magnitude, rotation and scale in one step). Annotate/run/report subcommands are
added once a device-captured dataset exists (see docs/features/tap-to-walk.md, "Bearing registration
investigation").

Setup (venv is gitignored):
    python3 -m venv scripts/registration-bench/.venv
    scripts/registration-bench/.venv/bin/pip install opencv-python-headless numpy

Self-check:
    scripts/registration-bench/.venv/bin/python scripts/test_registration_bench.py
"""

import math
from pathlib import Path

import cv2
import numpy as np

# MapLibre GL world size: 512 px tiles, Web Mercator equator circumference / 512 px.
EARTH_EQUATOR_M_PER_PX_AT_Z0 = 78271.517


def similarity_from_points(src, dst):
    """Least-squares 2x3 similarity transform mapping src points onto dst points."""
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    n = len(src)
    a = np.zeros((2 * n, 4))
    b = dst.reshape(-1)
    a[0::2] = np.column_stack([src[:, 0], -src[:, 1], np.ones(n), np.zeros(n)])
    a[1::2] = np.column_stack([src[:, 1], src[:, 0], np.zeros(n), np.ones(n)])
    p, *_ = np.linalg.lstsq(a, b, rcond=None)
    return np.array([[p[0], -p[1], p[2]], [p[1], p[0], p[3]]])


def truth_from_annotations(points):
    """3x3 ground-truth homography (ref -> game) from annotated rows [rx, ry, gx, gy]; least squares."""
    pts = np.asarray(points, dtype=np.float64)
    h, _ = cv2.findHomography(pts[:, :2], pts[:, 2:4], 0)
    return h


def _apply(m, pts):
    """Map Nx2 points through a 2x3 affine or 3x3 homography (with perspective divide)."""
    m = np.asarray(m, dtype=np.float64)
    homog = np.hstack([pts, np.ones((len(pts), 1))])
    out = homog @ m.T
    if m.shape == (3, 3):
        return out[:, :2] / out[:, 2:3]
    return out


def landing_error_m(est, truth, width, height, m_per_px):
    """Max distance (m) between where est and truth put 8 probe pixels: 4 corners + 4 edge midpoints.

    est and truth may each be a 2x3 similarity or a 3x3 homography (pitched game camera).
    """
    probes = np.array(
        [
            [0, 0], [width - 1, 0], [0, height - 1], [width - 1, height - 1],
            [width / 2, 0], [width / 2, height - 1], [0, height / 2], [width - 1, height / 2],
        ],
        dtype=np.float64,
    )
    pe = _apply(est, probes)
    pt = _apply(truth, probes)
    return float(np.max(np.linalg.norm(pe - pt, axis=1)) * m_per_px)


def chamfer_score(edges_a, edges_b):
    """Symmetric mean chamfer distance between two boolean edge maps, in pixels of the short side."""
    if not edges_a.any() or not edges_b.any():
        return float("inf")
    dist_a = cv2.distanceTransform((~edges_a).astype(np.uint8), cv2.DIST_L2, 3)
    dist_b = cv2.distanceTransform((~edges_b).astype(np.uint8), cv2.DIST_L2, 3)
    d_ab = dist_b[edges_a].mean()
    d_ba = dist_a[edges_b].mean()
    short_side = min(edges_a.shape)
    return float((d_ab + d_ba) / 2 / short_side)


def m_per_px_reference(lat_deg, zoom, density):
    """Ground metres per device pixel for our rendered map at a latitude, zoom and screen density."""
    return EARTH_EQUATOR_M_PER_PX_AT_Z0 * math.cos(math.radians(lat_deg)) / (2**zoom) / density


def _spectrum(img):
    h, w = img.shape
    window = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    mag = np.abs(np.fft.fftshift(np.fft.fft2(img.astype(np.float32) * window)))
    return np.log1p(mag).astype(np.float32)


def _ncc(a, b):
    a = a.astype(np.float32).ravel()
    b = b.astype(np.float32).ravel()
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum())) or 1.0
    return float((a * b).sum() / denom)


def register_logpolar(ref_gray, game_gray):
    """Rotation + scale of game relative to ref, as a 2x3 matrix mapping ref pixels to game pixels.

    Log-polar phase correlation on the FFT magnitude (Reddy-Chatterji). The magnitude spectrum of a real
    image is centrosymmetric, so the angle is ambiguous by 180 degrees; both candidates are scored by
    normalised cross-correlation of the warped images and the better one is returned.
    """
    h, w = ref_gray.shape
    center = (w / 2.0, h / 2.0)
    max_radius = min(h, w) / 2.0
    lp_ref = cv2.warpPolar(_spectrum(ref_gray), (w, h), center, max_radius, cv2.WARP_POLAR_LOG)
    lp_game = cv2.warpPolar(_spectrum(game_gray), (w, h), center, max_radius, cv2.WARP_POLAR_LOG)
    (dx, dy), _ = cv2.phaseCorrelate(lp_ref, lp_game)

    log_step = math.log(max_radius) / w
    scale = math.exp(-dx * log_step)
    angle = -dy * 360.0 / h

    best, best_score = None, -np.inf
    for cand in (angle, angle + 180.0):
        m = cv2.getRotationMatrix2D(center, cand, scale)
        warped = cv2.warpAffine(ref_gray, m, (w, h))
        score = _ncc(warped, game_gray)
        if score > best_score:
            best, best_score = m, score
    return best


def register_homography(ref_gray, game_gray, ratio=0.8, reproj_px=3.0):
    """Perspective (pitched camera) registration: 3x3 homography mapping ref pixels to game pixels.

    ORB features on both images, Hamming matching with Lowe's ratio test, then RANSAC findHomography.
    Returns (H, inlier_ratio) or (None, 0.0) when there are too few matches. inlier_ratio is the
    verification score: RANSAC inliers over ratio-test matches.
    """
    orb = cv2.ORB_create(nfeatures=2000)
    kp_ref, des_ref = orb.detectAndCompute(ref_gray, None)
    kp_game, des_game = orb.detectAndCompute(game_gray, None)
    if des_ref is None or des_game is None or len(kp_ref) < 4 or len(kp_game) < 4:
        return None, 0.0
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    knn = matcher.knnMatch(des_ref, des_game, k=2)
    good = [p[0] for p in knn if len(p) == 2 and p[0].distance < ratio * p[1].distance]
    if len(good) < 4:
        return None, 0.0
    src = np.float32([kp_ref[m.queryIdx].pt for m in good])
    dst = np.float32([kp_game[m.trainIdx].pt for m in good])
    h, inliers = cv2.findHomography(src, dst, cv2.RANSAC, reproj_px)
    if h is None:
        return None, 0.0
    return h, float(inliers.sum()) / len(good)


def _to_gray(img_bgr):
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)


def register_orb_similarity(ref_gray, game_gray):
    """ORB + RANSAC similarity (rotation, scale, translation). Returns (2x3 or None, inlier_ratio)."""
    orb = cv2.ORB_create(nfeatures=2000)
    kp_ref, des_ref = orb.detectAndCompute(ref_gray, None)
    kp_game, des_game = orb.detectAndCompute(game_gray, None)
    if des_ref is None or des_game is None or len(kp_ref) < 3 or len(kp_game) < 3:
        return None, 0.0
    knn = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(des_ref, des_game, k=2)
    good = [p[0] for p in knn if len(p) == 2 and p[0].distance < 0.8 * p[1].distance]
    if len(good) < 3:
        return None, 0.0
    src = np.float32([kp_ref[m.queryIdx].pt for m in good])
    dst = np.float32([kp_game[m.trainIdx].pt for m in good])
    m, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    if m is None:
        return None, 0.0
    return m, float(inliers.sum()) / len(good)


def _adb_screencap(serial, out_path):
    import subprocess

    data = subprocess.run(
        ["adb", "-s", serial, "exec-out", "screencap", "-p"], check=True, capture_output=True
    ).stdout
    Path(out_path).write_bytes(data)


def _adb_swipe(serial, x1, y1, x2, y2, ms=400):
    import subprocess

    subprocess.run(
        ["adb", "-s", serial, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms)],
        check=True,
    )


GAME_ACTIVITY = "com.nianticlabs.pokemongo/com.nianticproject.holoholo.libholoholo.unity.UnityMainActivity"
APP_ACTIVITY = "com.locationjoystick.app/.MainActivity"


def _focus(serial, activity):
    import subprocess

    subprocess.run(["adb", "-s", serial, "shell", "am", "start", "-n", activity], check=True,
                   capture_output=True)


def cmd_capture(args):
    """Capture one game + own-map screenshot per pan step, writing pair dirs under args.out.

    Each app is brought to the foreground before its pan and screencap. The same pan vector is
    applied to both views; the pairs are not geometrically matched, only varied by panning.
    """
    import json
    import time

    out = Path(args.out)
    for i in range(args.pairs):
        pair = out / f"pair_{i:02d}"
        pair.mkdir(parents=True, exist_ok=True)
        for serial, activity, name in [(args.game_serial, GAME_ACTIVITY, "game.png"),
                                       (args.app_serial, APP_ACTIVITY, "reference.png")]:
            _focus(serial, activity)
            time.sleep(2)
            if i:
                _adb_swipe(serial, 540, 1500, 540 + args.dx, 1500 + args.dy)
                time.sleep(1.5)
            _adb_screencap(serial, pair / name)
        (pair / "meta.json").write_text(
            json.dumps({"index": i, "device": args.game_serial,
                        "pan_step": [args.dx, args.dy], "captured_at": time.time()}, indent=2)
        )
        print(f"captured {pair}")


def _angle_scale(m):
    """Rotation (deg) and scale of a 2x3 similarity matrix in cv2.getRotationMatrix2D convention."""
    return -math.degrees(math.atan2(m[1, 0], m[0, 0])), math.hypot(m[0, 0], m[1, 0])


def _methods():
    """(name, fn(ref_gray, game_gray) -> (matrix or None, score, matches)). Score is method-specific."""

    def logpolar(r, g):
        m = register_logpolar(r, g)
        return m, _ncc(cv2.warpAffine(r, m, (r.shape[1], r.shape[0])), g), 0

    def orb_sim(r, g):
        m, ratio = register_orb_similarity(r, g)
        return m, ratio, 0

    def orb_hom(r, g):
        h, ratio = register_homography(r, g)
        return h, ratio, 0

    return [("logpolar", logpolar), ("orb_similarity", orb_sim), ("orb_homography", orb_hom)]


def cmd_run(args):
    """Run every method on each pair. Two kinds of rows: 'real' (game vs own map, no truth) and
    'synthetic' (game vs the same game screenshot warped by a known rotation + scale, truth known)."""
    import json
    import time

    rows = []
    for pair in sorted(Path(args.data).glob("pair_*")):
        game = cv2.imread(str(pair / "game.png"))
        ref = cv2.imread(str(pair / "reference.png"))
        if game is None or ref is None:
            continue
        g, r = _to_gray(game), _to_gray(ref)
        h, w = g.shape
        known = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), args.synth_angle, args.synth_scale)
        g_synth = cv2.warpAffine(g, known, (w, h))
        for kind, a, b in [("real", r, g), ("synthetic", g, g_synth)]:
            for name, fn in _methods():
                t0 = time.perf_counter()
                m, score, matches = fn(a, b)
                ms = (time.perf_counter() - t0) * 1000
                row = {"pair": pair.name, "kind": kind, "method": name, "score": score,
                       "ms": ms, "rejected": m is None}
                if kind == "synthetic" and m is not None and name != "orb_homography":
                    got_angle, got_scale = _angle_scale(np.asarray(m))
                    row["angle_err_deg"] = abs(got_angle - args.synth_angle)
                    row["scale_err_pct"] = abs(got_scale / args.synth_scale - 1.0) * 100
                rows.append(row)
                print(f"{pair.name} {kind:9s} {name:15s} score={score:.3f} ms={ms:.0f} "
                      f"rejected={row['rejected']} {row.get('angle_err_deg', '')}")
    Path(args.data, "results.json").write_text(json.dumps(rows, indent=2))


def cmd_report(args):
    """Markdown summary per (kind, method): reject count, median score, angle/scale error, latency."""
    import json
    import statistics

    rows = json.loads(Path(args.results).read_text())
    print("| kind | method | n | rejected | median score | median angle err (deg) | median scale err (%) | p50 ms | max ms |")
    print("|---|---|---|---|---|---|---|---|---|")
    for kind in ("real", "synthetic"):
        for m in sorted({r["method"] for r in rows if r["kind"] == kind}):
            sub = [r for r in rows if r["kind"] == kind and r["method"] == m]
            ms = sorted(r["ms"] for r in sub)
            ang = [r["angle_err_deg"] for r in sub if "angle_err_deg" in r]
            sca = [r["scale_err_pct"] for r in sub if "scale_err_pct" in r]
            print(f"| {kind} | {m} | {len(sub)} | {sum(r['rejected'] for r in sub)} | "
                  f"{statistics.median(r['score'] for r in sub):.3f} | "
                  f"{statistics.median(ang):.2f} | " if ang else
                  f"| {kind} | {m} | {len(sub)} | {sum(r['rejected'] for r in sub)} | "
                  f"{statistics.median(r['score'] for r in sub):.3f} | n/a | ", end="")
            if ang:
                print(f"{statistics.median(sca):.2f} | {ms[len(ms) // 2]:.0f} | {ms[-1]:.0f} |")
            else:
                print(f"n/a | {ms[len(ms) // 2]:.0f} | {ms[-1]:.0f} |")


def main(argv=None):
    import argparse

    p = argparse.ArgumentParser(description="Bearing-registration bench for tap-to-walk.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("out")
    c.add_argument("--game-serial", default="0A061FDD4000JF")
    c.add_argument("--app-serial", default="0A061FDD4000JF")
    c.add_argument("--pairs", type=int, default=6)
    c.add_argument("--dx", type=int, default=120)
    c.add_argument("--dy", type=int, default=0)
    c.set_defaults(func=cmd_capture)
    r = sub.add_parser("run")
    r.add_argument("data")
    r.add_argument("--synth-angle", type=float, default=25.0)
    r.add_argument("--synth-scale", type=float, default=1.2)
    r.set_defaults(func=cmd_run)
    rep = sub.add_parser("report")
    rep.add_argument("results")
    rep.set_defaults(func=cmd_report)
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
