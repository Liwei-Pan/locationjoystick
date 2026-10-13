#!/usr/bin/env python3
"""Self-check for registration_bench.py. Run directly: scripts/registration-bench/.venv/bin/python scripts/test_registration_bench.py"""

import importlib.util
import math
from pathlib import Path

import cv2
import numpy as np

spec = importlib.util.spec_from_file_location(
    "registration_bench", Path(__file__).parent / "registration_bench.py"
)
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)


def synthetic_map(seed, size=512):
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size), np.uint8)
    for _ in range(25):
        pts = rng.integers(0, size, size=(rng.integers(2, 5), 2)).astype(np.int32)
        cv2.polylines(img, [pts], False, 255, int(rng.integers(1, 4)))
    return img


def test_similarity_from_points_recovers_known_transform():
    true = cv2.getRotationMatrix2D((100, 50), 25.0, 1.3)
    src = np.array([[0, 0], [400, 0], [0, 300], [400, 300], [200, 150]], dtype=np.float64)
    dst = src @ true[:, :2].T + true[:, 2]
    est = rb.similarity_from_points(src, dst)
    assert np.allclose(est, true, atol=1e-6)


def test_landing_error_zero_for_identical_and_linear_in_bearing_error():
    m = cv2.getRotationMatrix2D((540, 960), 0.0, 1.0)
    assert rb.landing_error_m(m, m, 1080, 2400, 0.23) == 0.0
    # 1 degree of rotation about the centre moves the far corner by ~ half-diagonal * sin(1 deg).
    rot = cv2.getRotationMatrix2D((540, 1200), 1.0, 1.0)
    err_m = rb.landing_error_m(rot, np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float64), 1080, 2400, 1.0)
    half_diag = math.hypot(540, 1200)
    assert abs(err_m - half_diag * math.sin(math.radians(1.0))) < 0.5


def test_logpolar_recovers_rotation_and_scale():
    ref = synthetic_map(seed=1)
    true = cv2.getRotationMatrix2D((256, 256), 30.0, 1.15)
    game = cv2.warpAffine(ref, true, (512, 512))
    est = rb.register_logpolar(ref, game)
    # cv2.getRotationMatrix2D uses m[1,0] = -s*sin(angle), so negate to get the cv2 angle back.
    est_angle = -math.degrees(math.atan2(est[1, 0], est[0, 0]))
    est_scale = math.hypot(est[0, 0], est[1, 0])
    assert abs(est_angle - 30.0) < 0.5, est_angle
    assert abs(est_scale / 1.15 - 1.0) < 0.01, est_scale


def test_chamfer_accepts_true_alignment_and_rejects_unrelated_map():
    ref = synthetic_map(seed=2)
    true = cv2.getRotationMatrix2D((256, 256), 12.0, 1.05)
    game = cv2.warpAffine(ref, true, (512, 512))
    unrelated = synthetic_map(seed=3)
    # Placeholder separation only: the real tau is calibrated on the device dataset in the report step.
    tau = 0.005
    aligned = rb.chamfer_score(cv2.warpAffine(ref, true, (512, 512)) > 0, game > 0)
    wrong = rb.chamfer_score(unrelated > 0, game > 0)
    assert aligned <= tau < wrong, (aligned, wrong)


def textured_map(seed, size=512):
    """Blurred noise plus strokes: enough local structure for AKAZE to find stable keypoints."""
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, size=(size, size), dtype=np.uint8)
    img = cv2.GaussianBlur(noise, (0, 0), 2.0)
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    return cv2.addWeighted(img, 0.7, synthetic_map(seed, size), 0.3, 0)


def test_homography_recovers_pitched_view_and_scores_unrelated_lower():
    ref = textured_map(seed=4)
    size = 512
    src = np.float32([[0, 0], [size, 0], [size, size], [0, size]])
    # Pitched camera: the top edge of the view is narrower than the bottom edge.
    dst = np.float32([[size * 0.2, 0], [size * 0.8, 0], [size, size], [0, size]])
    true = cv2.getPerspectiveTransform(src, dst)
    game = cv2.warpPerspective(ref, true, (size, size))
    est, inlier_ratio = rb.register_homography(ref, game)
    assert est is not None
    err = rb.landing_error_m(est, true, size, size, 1.0)
    assert err < 2.0, err
    _, wrong_ratio = rb.register_homography(textured_map(seed=5), game)
    assert inlier_ratio > wrong_ratio, (inlier_ratio, wrong_ratio)


def test_truth_from_annotations_recovers_known_homography():
    size = 512
    src = np.float32([[0, 0], [size, 0], [size, size], [0, size]])
    dst = np.float32([[size * 0.2, 0], [size * 0.8, 0], [size, size], [0, size]])
    known = cv2.getPerspectiveTransform(src, dst)
    # 8 annotated ref points spread over the frame, mapped through the known homography.
    ref_pts = np.array([[10, 20], [500, 30], [40, 250], [480, 260], [256, 10],
                        [256, 500], [120, 400], [400, 120]], dtype=np.float64)
    game_pts = rb._apply(known, ref_pts)
    truth = rb.truth_from_annotations(np.hstack([ref_pts, game_pts]))
    assert np.allclose(truth / truth[2, 2], known / known[2, 2], atol=1e-6)
    assert rb.landing_error_m(truth, truth, size, size, 0.23) == 0.0
    # A one-pixel annotation shift gives a small, non-zero error.
    shifted = game_pts.copy()
    shifted[0, 0] += 1.0
    off = rb.truth_from_annotations(np.hstack([ref_pts, shifted]))
    err = rb.landing_error_m(off, truth, size, size, 0.23)
    assert 0.0 < err < 1.0, err


def test_register_unpitched_recovers_heading_and_tap_landing_error():
    cam = {"s": 7.0, "sy": 3.0, "a": -0.0008, "px": 540.0, "py": 1400.0}
    ref = cv2.GaussianBlur(synthetic_map(seed=3, size=1100), (0, 0), 2)
    marker, mpp = (550, 550), 0.6
    true = rb.ground_to_game(cam, 47.0) @ rb.ref_to_ground(marker, mpp)
    game = cv2.warpPerspective(ref, true, (1080, 2340))
    est, score = rb.register_unpitched(ref, game, cam, marker, mpp)
    err = rb.tap_landing_error_m(est, rb.ground_to_game(cam, 47.0), rb.TAP_PROBES)
    assert err < 1.0, err
    assert score > 0.3, score
    wrong = rb.tap_landing_error_m(rb.ground_to_game(cam, 0.0), rb.ground_to_game(cam, 47.0), rb.TAP_PROBES)
    assert wrong > 20.0, wrong


def _flows(s, sy, theta_deg, moves):
    r = math.radians(theta_deg)
    a = np.array([[s * math.cos(r), -s * math.sin(r)], [-sy * math.sin(r), -sy * math.cos(r)]])
    return [tuple(-(a @ np.asarray(d, dtype=np.float64))) for d in moves]


def test_heading_from_moves_recovers_known_heading_and_scales():
    d1, d2 = (0.0, 8.0), (8.0, 0.0)
    f1, f2 = _flows(7.0, 3.0, 47.0, [d1, d2])
    est = rb.heading_from_moves(d1, f1, d2, f2)
    assert abs(est["theta_deg"] - 47.0) < 0.01, est
    assert abs(est["s"] / 7.0 - 1) < 0.01 and abs(est["sy"] / 3.0 - 1) < 0.01, est
    cam = {"s": 1.0, "sy": 1.0, "a": 0.0, "px": 540.0, "py": 1400.0}
    assert np.allclose(rb.motion_g_est(est, cam), rb.ground_to_game({**cam, "s": 7.0, "sy": 3.0}, 47.0), atol=1e-3)


def test_heading_from_moves_returns_none_when_low_confidence():
    d1, d2 = (0.0, 8.0), (8.0, 0.0)
    f1, f2 = _flows(7.0, 3.0, 47.0, [d1, d2])
    assert rb.heading_from_moves(d1, f1, (0.0, 4.0), (f1[0] / 2, f1[1] / 2)) is None  # parallel
    assert rb.heading_from_moves((0.0, 2.0), f1, d2, f2) is None  # move under 3 m
    assert rb.heading_from_moves(d1, (1.0, 1.0), d2, f2) is None  # flow under 5 px
    bad = _flows(7.0, 3.0, 47.0, [d1])[0], _flows(7.0, 3.0, 80.0, [d2])[0]  # rows disagree by 33 deg
    assert rb.heading_from_moves(d1, bad[0], d2, bad[1]) is None


def test_content_flow_recovers_known_shift():
    canvas = np.zeros((2340, 1080), np.uint8)
    canvas[500:1400, :] = cv2.resize(textured_map(seed=6), (1080, 900))
    shifted = cv2.warpAffine(canvas, np.float32([[1, 0, -12], [0, 1, 7]]), (1080, 2340))
    fx, fy, resp = rb.content_flow(canvas, shifted)
    assert abs(fx + 12) < 0.5 and abs(fy - 7) < 0.5 and resp > 0.3, (fx, fy, resp)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok {t.__name__}")
    print(f"{len(tests)} passed")
