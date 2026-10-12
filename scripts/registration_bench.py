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
