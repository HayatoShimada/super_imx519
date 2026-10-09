"""IMX519 の撮影セッション（露出ブラケット × 連写）を合成して、1 枚撮りと比べる。

撮影は imx519_edge。セッションのフォルダには、フレームごとの .dng / .jpg / .json と
session.json がある前提。ファイル名は v1 が p{位置}_ev{EV}_{NN}、
v0（schema_version なし）が ev{EV}_{NN}。

処理:
1. 露出ごとに、フレームを位置合わせして平均する（ノイズ低減）
2. 平均した露出違いを、基準露出（EV 0）に位置合わせして Mertens で融合する（HDR）
3. 1 枚撮りとの比較（ノイズの推定値、中央の切り抜きを並べた画像）を出す

DNG（RAW を rawpy で現像）と JPEG（Pi の ISP 出力）の両方で同じ処理をして比べられる。

usage:
    uv run python scripts/stack_session.py ~/data/super_imx519/sessions/<session> \\
        --out ~/data/super_imx519/results/stack-<session>
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from super_imx519.pipeline import stacking


def load(path: Path, source: str, half: bool) -> np.ndarray:
    """リニア（DNG）または表示用（JPEG）の float32 BGR を返す。"""
    if source == "dng":
        return stacking.read_dng(path, half_size=half)
    image = stacking.read_image(path)
    if half:
        image = cv2.resize(image, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    return image


def to_display(image: np.ndarray, source: str) -> np.ndarray:
    return stacking.linear_to_srgb(image) if source == "dng" else image


def crop_center(image: np.ndarray, size: int) -> np.ndarray:
    h, w = image.shape[:2]
    y, x = (h - size) // 2, (w - size) // 2
    return image[y : y + size, x : x + size]


def label(image: np.ndarray, text: str) -> np.ndarray:
    out = image.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(out, text, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return out


def process(session_dir: Path, out: Path, source: str, half: bool, crop: int) -> dict:
    session = json.loads((session_dir / "session.json").read_text())
    evs = session.get("ev") or session["sequence"]["ev"]  # v0 / v1
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"source": source, "half_size": half, "ev": {}}

    # DNG はリニアのまま足し合わせ、保存と HDR の入力にするときだけガンマをかける
    stacked_display, single_display = {}, {}
    for ev in evs:
        paths = sorted(session_dir.glob(f"*ev{ev:+.1f}_*.{source}"))
        t0 = time.time()
        frames = [load(p, source, half) for p in paths]
        t_load = time.time() - t0
        t0 = time.time()
        result = stacking.stack(frames, linear=source == "dng")
        t_stack = time.time() - t0

        single = to_display(frames[result.ref_index], source)
        stacked = to_display(result.image, source)
        single_display[ev], stacked_display[ev] = single, stacked
        cv2.imwrite(str(out / f"single_ev{ev:+.1f}.png"), stacking.to_uint16(single))
        cv2.imwrite(str(out / f"stacked_ev{ev:+.1f}.png"), stacking.to_uint16(stacked))

        n_single, n_stacked = stacking.noise_sigma(single), stacking.noise_sigma(stacked)
        n_used = sum(result.used)
        report["ev"][f"{ev:+.1f}"] = {
            "frames": len(frames),
            "used": n_used,
            "dropped": [p.name for p, u in zip(paths, result.used, strict=True) if not u],
            "noise_single": round(n_single, 3),
            "noise_stacked": round(n_stacked, 3),
            "noise_ratio": round(n_stacked / n_single, 3),
            "ideal_ratio": round(1 / np.sqrt(n_used), 3),
            "shifts_px": [(round(x, 3), round(y, 3)) for x, y in result.shifts()],
            "ecc": [round(c, 5) for c in result.ecc],
            "seconds_load": round(t_load, 1),
            "seconds_stack": round(t_stack, 1),
        }
        print(
            f"[{source}] EV {ev:+.1f}: {n_used}/{len(frames)} 枚, "
            f"ノイズ {n_single:.2f} → {n_stacked:.2f} "
            f"(×{n_stacked / n_single:.2f}, 理想 ×{1 / np.sqrt(n_used):.2f}), "
            f"読込 {t_load:.0f}s 合成 {t_stack:.0f}s"
        )

    # HDR: 露出違いを EV 0 に合わせてから融合する
    if len(evs) > 1:
        ref_ev = min(evs, key=abs)
        ref_gray = stacking._gray(stacked_display[ref_ev].astype(np.float32))
        aligned, report["hdr_align"] = [], {}
        for ev in evs:
            img = stacked_display[ev].astype(np.float32)
            if ev != ref_ev:
                h, cc = stacking.estimate_warp(ref_gray, stacking._gray(img))
                img = stacking.warp_to_ref(img, h)
                report["hdr_align"][f"{ev:+.1f}"] = {
                    "shift_px": (round(float(h[0, 2]), 3), round(float(h[1, 2]), 3)),
                    "ecc": round(cc, 5),
                }
            aligned.append(img)
        hdr = stacking.merge_mertens(aligned)
        hdr_single = stacking.merge_mertens([single_display[ev].astype(np.float32) for ev in evs])
        cv2.imwrite(str(out / "hdr_stacked.png"), stacking.to_uint16(hdr))
        cv2.imwrite(
            str(out / "hdr_stacked.jpg"), stacking.to_uint8(hdr), [cv2.IMWRITE_JPEG_QUALITY, 95]
        )
        cv2.imwrite(str(out / "hdr_single.png"), stacking.to_uint16(hdr_single))
        report["noise_hdr_single"] = round(stacking.noise_sigma(hdr_single), 3)
        report["noise_hdr_stacked"] = round(stacking.noise_sigma(hdr), 3)

    # 比較画像: 中央の切り抜きを横に並べる（EV 0 の 1 枚 / EV 0 の平均 / HDR）
    ref_ev = min(evs, key=abs)
    tiles = [
        label(
            stacking.to_uint8(crop_center(single_display[ref_ev], crop)), f"single EV{ref_ev:+.0f}"
        ),
        label(
            stacking.to_uint8(crop_center(stacked_display[ref_ev], crop)),
            f"stacked EV{ref_ev:+.0f}",
        ),
    ]
    if len(evs) > 1:
        tiles.append(label(stacking.to_uint8(crop_center(hdr, crop)), "HDR (stacked)"))
    cv2.imwrite(str(out / "compare_crop.png"), np.hstack(tiles))
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--source", choices=["dng", "jpg", "both"], default="both")
    ap.add_argument("--half", action="store_true", help="半分の解像度で試す（速い）")
    ap.add_argument("--crop", type=int, default=800, help="比較画像の切り抜きの一辺（px）")
    args = ap.parse_args()
    for source in ["dng", "jpg"] if args.source == "both" else [args.source]:
        process(args.session, args.out / source, source, args.half, args.crop)


if __name__ == "__main__":
    main()
