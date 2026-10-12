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


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok {t.__name__}")
    print(f"{len(tests)} passed")
