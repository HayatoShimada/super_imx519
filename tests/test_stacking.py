import cv2
import numpy as np
import pytest

from super_imx519.pipeline import stacking


def _texture(h: int = 256, w: int = 320, seed: int = 0) -> np.ndarray:
    """位置合わせが効くように、いろいろな太さの模様を持つ BGR の表示用画像（0〜1）を作る。"""
    rng = np.random.default_rng(seed)
    base = rng.random((h // 8, w // 8, 3)).astype(np.float32)
    image = cv2.resize(base, (w, h), interpolation=cv2.INTER_CUBIC)
    fine = cv2.GaussianBlur(rng.random((h, w, 3)).astype(np.float32), (0, 0), 1.5)
    return np.clip(0.6 * image + 0.4 * fine, 0, 1)


def _shift(image: np.ndarray, dx: float, dy: float) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    h, w = image.shape[:2]
    return cv2.warpAffine(image, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


def test_estimate_warp_recovers_subpixel_shift():
    ref = _texture()
    moved = _shift(ref, 3.4, -1.7)
    h, cc = stacking.estimate_warp(stacking._gray(ref), stacking._gray(moved))
    # ECC の変換は「基準の座標 → 動いた画像の座標」なので、平行移動成分が (dx, dy) になる
    assert h[0, 2] == pytest.approx(3.4, abs=0.1)
    assert h[1, 2] == pytest.approx(-1.7, abs=0.1)
    assert cc > 0.95


def test_stack_aligns_and_reduces_noise():
    rng = np.random.default_rng(1)
    clean = _texture()
    shifts = [(0, 0), (2.5, 1.0), (-1.5, 2.0), (3.0, -2.5), (-2.0, -1.0), (1.0, 3.0)]
    frames = [
        np.clip(_shift(clean, dx, dy) + rng.normal(0, 0.03, clean.shape), 0, 1).astype(np.float32)
        for dx, dy in shifts
    ]
    result = stacking.stack(frames, linear=False, ref_index=0)

    for (dx, dy), (sx, sy) in zip(shifts, result.shifts(), strict=True):
        assert sx == pytest.approx(dx, abs=0.15)
        assert sy == pytest.approx(dy, abs=0.15)
    # 縁は折り返しで埋まるので、中央で比べる
    c = (slice(16, -16), slice(16, -16))
    single_err = np.std(frames[0][c] - clean[c])
    stacked_err = np.std(result.image[c] - clean[c])
    assert stacked_err < single_err / 2  # 6 枚なら理想は 1/√6 ≈ 0.41


def test_stack_drops_frames_that_do_not_match():
    clean = _texture()
    other = _texture(seed=9)  # 撮影中に画が変わったフレームの代わり
    frames = [clean, _shift(clean, 1.0, 0.5), other, _shift(clean, -0.5, 1.0)]
    result = stacking.stack(frames, linear=False, ref_index=0)
    assert result.used == [True, True, False, True]
    c = (slice(16, -16), slice(16, -16))
    assert np.abs(result.image[c] - clean[c]).mean() < 0.01


def test_noise_sigma_estimates_gaussian_noise():
    rng = np.random.default_rng(2)
    flat = np.full((200, 200, 3), 0.5, dtype=np.float32)
    noisy = flat + rng.normal(0, 4 / 255, flat.shape).astype(np.float32)
    # 3 チャンネルに独立なノイズを足すと、グレーでは約 1/√3 に下がる（重みの二乗和の平方根）
    expected = 4 * np.sqrt(0.299**2 + 0.587**2 + 0.114**2)
    assert stacking.noise_sigma(noisy) == pytest.approx(expected, rel=0.1)


def test_merge_mertens_keeps_range_and_shape():
    base = _texture()
    exposures = [np.clip(base * k, 0, 1) for k in (0.4, 1.0, 2.5)]
    merged = stacking.merge_mertens(exposures)
    assert merged.shape == base.shape
    assert np.isfinite(merged).all()
    assert 0.2 < merged.mean() < 0.8  # 1/255 を二重にかけると 0 付近になる


def test_srgb_roundtrip():
    x = np.linspace(0, 1, 101, dtype=np.float32)
    assert np.allclose(stacking.srgb_to_linear(stacking.linear_to_srgb(x)), x, atol=1e-5)
