"""撮影セッションから完成画像を作る（スタジオが 1 セッションずつ呼ぶ）。

1. 露出ごとに DNG を現像（rawpy、リニア）し、位置合わせして平均する（ノイズ低減）
2. 平均した露出違いを、EV 0 に位置合わせして Mertens で融合する（HDR）
3. 長辺 2048px 以内の sRGB の JPEG（品質 95）を final.jpg に、
   画面用に小さくしたものを preview.jpg に書く

CMS は商品写真を長辺 2048px・JPEG 品質 85 に変換するので、2048 以内で渡す
（再サンプリングを 1 回にする）。
進捗は progress(done, total, label) で知らせる。重みは実測（16MP の DNG）のおおよその秒数。
"""

import json
import time
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from . import stacking

FINAL_SIDE = 2048
PREVIEW_SIDE = 1280
W_LOAD, W_STACK, W_MERGE, W_WRITE = 0.4, 8.0, 6.0, 1.0  # 1 枚の現像 / 1 露出の合成 / HDR / 書き出し

Progress = Callable[[float, float, str], None]


def session_evs(session: dict) -> list[float]:
    """v0（ev が直下）と v1（sequence.ev）の両方を読む。"""
    return session.get("ev") or session["sequence"]["ev"]


def merge_exposures(displays: dict[float, np.ndarray]) -> tuple[np.ndarray, dict]:
    """表示用（sRGB）の露出違いを、EV 0 に一番近いものに位置合わせして Mertens で融合する。"""
    evs = sorted(displays)
    if len(evs) == 1:
        return displays[evs[0]], {}
    ref_ev = min(evs, key=abs)
    ref_gray = stacking._gray(displays[ref_ev].astype(np.float32))
    aligned, report = [], {}
    for ev in evs:
        img = displays[ev].astype(np.float32)
        if ev != ref_ev:
            h, cc = stacking.estimate_warp(ref_gray, stacking._gray(img))
            img = stacking.warp_to_ref(img, h)
            report[f"{ev:+.1f}"] = {
                "shift_px": (round(float(h[0, 2]), 3), round(float(h[1, 2]), 3)),
                "ecc": round(cc, 5),
            }
        aligned.append(img)
    return stacking.merge_mertens(aligned), report


def fit(image: np.ndarray, side: int) -> np.ndarray:
    h, w = image.shape[:2]
    scale = side / max(h, w)
    if scale >= 1:
        return image
    return cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def write_jpeg(path: Path, image: np.ndarray, quality: int) -> None:
    """一時ファイルに書いてから置き換える（書きかけを完成と見なさないため）。"""
    tmp = path.with_suffix(".tmp.jpg")
    if not cv2.imwrite(str(tmp), stacking.to_uint8(image), [cv2.IMWRITE_JPEG_QUALITY, quality]):
        raise RuntimeError(f"{path.name} を書けません")
    tmp.replace(path)


def process_session(session_dir: Path, out_dir: Path, progress: Progress | None = None) -> dict:
    session = json.loads((session_dir / "session.json").read_text())
    evs = session_evs(session)
    paths = {ev: sorted(session_dir.glob(f"*ev{ev:+.1f}_*.dng")) for ev in evs}
    if not all(paths.values()):
        raise RuntimeError(
            "DNG が足りません: " + ", ".join(f"EV{ev:+.0f}" for ev in evs if not paths[ev])
        )
    total = sum(len(p) for p in paths.values()) * W_LOAD + len(evs) * W_STACK + W_MERGE + W_WRITE
    done = 0.0

    def tick(weight: float, label: str) -> None:
        nonlocal done
        done += weight
        if progress:
            progress(min(done, total), total, label)

    if progress:
        progress(0, total, "始めます")
    started = time.time()
    displays, report = {}, {"session_id": session_dir.name, "ev": {}}
    for ev in evs:
        frames = []
        for i, path in enumerate(paths[ev], 1):
            frames.append(stacking.read_dng(path))
            tick(W_LOAD, f"現像 EV{ev:+.0f}（{i}/{len(paths[ev])}）")
        result = stacking.stack(frames, linear=True)
        displays[ev] = stacking.linear_to_srgb(result.image)
        report["ev"][f"{ev:+.1f}"] = {
            "frames": len(frames),
            "used": int(sum(result.used)),
            "noise_single": round(
                stacking.noise_sigma(stacking.linear_to_srgb(frames[result.ref_index])), 3
            ),
            "noise_stacked": round(stacking.noise_sigma(displays[ev]), 3),
        }
        del frames
        tick(W_STACK, f"位置合わせと平均 EV{ev:+.0f}")

    hdr, report["hdr_align"] = merge_exposures(displays)
    tick(W_MERGE, "HDR の合成")

    out_dir.mkdir(parents=True, exist_ok=True)
    final = fit(hdr, FINAL_SIDE)
    write_jpeg(out_dir / "preview.jpg", fit(final, PREVIEW_SIDE), 85)
    report["final_size"] = [final.shape[1], final.shape[0]]
    report["seconds"] = round(time.time() - started, 1)
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    write_jpeg(out_dir / "final.jpg", final, 95)  # 最後に書く（final.jpg があれば完成）
    tick(W_WRITE, "書き出し")
    return report
