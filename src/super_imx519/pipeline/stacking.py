"""複数フレームの合成（位置合わせ＋平均と、露出ブラケットの HDR 合成）。

静物を固定カメラで連写したフレームを重ねて、1 枚では出せない画質を得る。

- 位置合わせ: ECC（cv2.findTransformECC）。粗い解像度から順に推定して元の解像度に戻す。
  ECC は明るさ・コントラストの違いに強いので、露出の違うフレーム同士も合わせられる
- 平均: float32 で足し合わせる。ノイズは N 枚で約 1/√N になる
- HDR: Mertens の露出融合（cv2.createMergeMertens）。トーンマップなしで自然な見た目になる

画像は BGR の float32 で扱い、「リニア」（RAW を現像しただけ）か「表示用」（sRGB のガンマ済み）かを
関数ごとに明記する。
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ECC_SCALES = (0.125, 0.25, 0.5, 1.0)
ECC_MIN_SIDE = 128  # 縮小しすぎると収束しない


def read_dng(path: str | Path, half_size: bool = False) -> np.ndarray:
    """DNG を現像して、リニアな sRGB（BGR, float32, 0〜1）で返す。

    WB は撮影時の値（DNG の AsShotNeutral）を使い、明るさの自動補正とガンマはかけない。
    """
    import rawpy  # 重いので RAW を扱うときだけ読む（uv sync --group raw）

    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            no_auto_bright=True,
            output_bps=16,
            gamma=(1, 1),
            output_color=rawpy.ColorSpace.sRGB,
            half_size=half_size,
        )
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR).astype(np.float32) / 65535.0


def read_image(path: str | Path) -> np.ndarray:
    """JPEG / PNG / TIFF を表示用（sRGB ガンマ済み）の BGR float32（0〜1）で返す。"""
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"読めません: {path}")
    scale = 65535.0 if image.dtype == np.uint16 else 255.0
    return image[..., :3].astype(np.float32) / scale


def linear_to_srgb(linear: np.ndarray) -> np.ndarray:
    x = np.clip(linear, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def srgb_to_linear(srgb: np.ndarray) -> np.ndarray:
    x = np.clip(srgb, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, np.power((x + 0.055) / 1.055, 2.4))


def to_uint16(image: np.ndarray) -> np.ndarray:
    return np.round(np.clip(image, 0.0, 1.0) * 65535).astype(np.uint16)


def to_uint8(image: np.ndarray) -> np.ndarray:
    return np.round(np.clip(image, 0.0, 1.0) * 255).astype(np.uint8)


def _gray(display: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(display, cv2.COLOR_BGR2GRAY)


def _scale_homography(h: np.ndarray, factor: float) -> np.ndarray:
    """縮小率 s で求めた変換を、縮小率 s*factor の座標系に直す（S·H·S⁻¹）。"""
    s = np.diag([factor, factor, 1.0]).astype(np.float32)
    return s @ h @ np.linalg.inv(s)


def ecc_scales(shape: tuple[int, ...]) -> tuple[float, ...]:
    """位置合わせを行う縮小率の列（粗い順）。16MP なら 1/8, 1/4, 1/2 の 3 段で、等倍は省く。"""
    short = min(shape[:2])
    top = 1.0 if short < 1024 else 0.5
    return tuple(s for s in ECC_SCALES if s <= top and short * s >= ECC_MIN_SIDE) or (1.0,)


def estimate_warp(
    ref_gray: np.ndarray,
    gray: np.ndarray,
    motion: int = cv2.MOTION_HOMOGRAPHY,
    scales: tuple[float, ...] | None = None,
    iterations: int = 200,
    eps: float = 1e-6,
) -> tuple[np.ndarray, float]:
    """gray を ref_gray に重ねる 3x3 の変換（元の解像度）と、最後の段の ECC 相関を返す。

    返す変換は findTransformECC の流儀（ref の座標 → gray の座標）なので、
    warp_to_ref() で WARP_INVERSE_MAP を付けて使う。
    """
    h = np.eye(3, dtype=np.float32)
    prev = None
    cc = 0.0
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, iterations, eps)
    for scale in scales or ecc_scales(ref_gray.shape):
        if prev is not None:
            h = _scale_homography(h, scale / prev)
        r = cv2.resize(ref_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        g = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        warp = h if motion == cv2.MOTION_HOMOGRAPHY else h[:2].copy()
        cc, warp = cv2.findTransformECC(r, g, warp, motion, criteria, None, 5)
        h = (
            warp
            if motion == cv2.MOTION_HOMOGRAPHY
            else np.vstack([warp, [0, 0, 1]]).astype(np.float32)
        )
        prev = scale
    return _scale_homography(h, 1.0 / prev), float(cc)


def warp_to_ref(image: np.ndarray, h: np.ndarray) -> np.ndarray:
    """estimate_warp() の変換で、image を基準フレームの位置に合わせる（OpenCL が使えれば GPU）。"""
    height, width = image.shape[:2]
    out = cv2.warpPerspective(
        cv2.UMat(image),
        h,
        (width, height),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REFLECT,
    )
    return out.get()


@dataclass
class StackResult:
    image: np.ndarray  # 平均した画像（入力と同じ色空間）
    warps: list[np.ndarray]  # 各フレームの変換（基準フレームは単位行列）
    ecc: list[float]  # 各フレームの ECC 相関（基準フレームは 1.0、合わせられなければ 0.0）
    used: list[bool]  # 平均に使ったか（相関が低いフレームは外す）
    ref_index: int

    def shifts(self) -> list[tuple[float, float]]:
        """各フレームの平行移動成分（px）。位置ずれの大きさの目安。"""
        return [(float(h[0, 2]), float(h[1, 2])) for h in self.warps]


def stack(
    frames: list[np.ndarray],
    linear: bool,
    ref_index: int | None = None,
    min_ecc: float = 0.99,
) -> StackResult:
    """フレームを基準フレームに位置合わせして平均する。

    linear=True ならリニアの画像として扱い、位置合わせだけガンマをかけた明るさで行う
    （暗部の構造も拾えるように）。
    位置合わせ後の ECC 相関が min_ecc 未満のフレーム（撮影中に人や光が動いた、カメラが動いた）は
    平均から外す。静物を固定カメラで撮ったフレームなら相関は 0.999 以上になる。
    """
    if not frames:
        raise ValueError("フレームがありません")
    ref_index = len(frames) // 2 if ref_index is None else ref_index

    def gray(image: np.ndarray) -> np.ndarray:
        return _gray(linear_to_srgb(image).astype(np.float32) if linear else image)

    ref_gray = gray(frames[ref_index])
    total = np.zeros_like(frames[ref_index], dtype=np.float64)
    warps, ecc, used = [], [], []
    for i, frame in enumerate(frames):
        if i == ref_index:
            h, cc = np.eye(3, dtype=np.float32), 1.0
        else:
            try:
                h, cc = estimate_warp(ref_gray, gray(frame))
            except cv2.error:  # 収束しない（別の画のように違う）
                h, cc = np.eye(3, dtype=np.float32), 0.0
        ok = cc >= min_ecc
        if ok:
            total += frame if i == ref_index else warp_to_ref(frame, h)
        warps.append(h)
        ecc.append(cc)
        used.append(ok)
    image = (total / sum(used)).astype(np.float32)
    return StackResult(image, warps, ecc, used, ref_index)


def merge_mertens(displays: list[np.ndarray]) -> np.ndarray:
    """表示用（sRGB ガンマ済み, 0〜1）の露出違いを Mertens で融合する。

    cv2.MergeMertens は浮動小数の入力も一律 1/255 するので、0〜255 に広げて渡す。
    """
    merged = cv2.createMergeMertens().process([np.clip(d, 0, 1) * 255.0 for d in displays])
    return np.clip(merged, 0.0, 1.0)


def noise_sigma(display: np.ndarray) -> float:
    """画像全体のノイズの標準偏差（0〜255 換算）を推定する（Immerkær 1996）。

    模様の多い画像では大きめに出るので、同じ構図の画像同士の比較に使う。
    """
    gray = _gray(display).astype(np.float64) * 255.0
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)
    response = cv2.filter2D(gray, -1, kernel)[1:-1, 1:-1]
    h, w = gray.shape
    return float(np.sqrt(np.pi / 2) * np.abs(response).sum() / (6 * (w - 2) * (h - 2)))
