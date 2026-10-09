# カメラ制御（Picamera2 / rpicam-still）

確認日: 2026-10-07

## 主な出典

- [Picamera2 マニュアル（PDF、Release 6）](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)
- [rpicam の共通オプション](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/camera/rpicam_options_common.adoc)
- [Raspberry Pi 公式: Camera software](https://www.raspberrypi.com/documentation/computers/camera_software.html)
- [Arducam: Picamera2 ガイド](https://docs.arducam.com/Raspberry-Pi-Camera/Native-camera/PiCamera2-User-Guide/) / [libcamera ガイド](https://docs.arducam.com/Raspberry-Pi-Camera/Native-camera/Libcamera-User-Guide/)

IMX519 の AF と手動レンズ位置は **Arducam 版 libcamera が前提**（[imx519.md](../hardware/imx519.md)）。

## 制御の対応表

| 目的 | Picamera2（`set_controls` に渡す値） | rpicam-still |
| --- | --- | --- |
| 露光時間 | `ExposureTime: µs` | `--shutter <µs>` |
| アナログゲイン | `AnalogueGain: x` | `--gain x`（別名 `--analoggain`） |
| AE を止める | `ExposureTime` と `AnalogueGain` を両方指定する。`AeEnable` や、新しい libcamera での `ExposureTimeMode` / `AnalogueGainMode` の扱いは版によって違う（未確認。`camera_controls` で確かめる） | `--shutter` と `--gain` を両方指定する |
| AWB を止める | `AwbEnable: False` か `ColourGains: (r, b)`（範囲 0.0〜32.0。指定すると AWB は無効になる） | `--awbgains r,b`（0 以外を指定すると AWB 無効） |
| 手動フォーカス | `AfMode: controls.AfModeEnum.Manual`、`LensPosition: dioptre` | `--autofocus-mode manual --lens-position <値>` |
| AF を 1 回だけ走らせる | `AfMode: Auto` ＋ `AfTrigger` | `--autofocus-on-capture` |
| フレーム時間 | `FrameDurationLimits: (min_us, max_us)` | （`--framerate` などで間接的に指定） |
| DNG 保存 | `capture_file("x.dng", name="raw")` / `request.save_dng("x.dng")` / `helpers.save_dng(...)` | `-r` / `--raw`（出力と同じ名前で `.dng` も保存） |
| すぐ撮る | — | `--immediate` |

- 値の範囲はセンサーモードによって変わる。`picam2.camera_controls["ExposureTime"]` などで（最小、最大、既定）を確かめる
- カメラ起動後に設定したコントロールは、数フレーム遅れて反映される。撮影したフレームのメタデータで、実際に反映された値を確認してから使う
- LensPosition の単位はディオプター（1/距離[m]）で、0.0 が無限遠。IMX519 の Arducam 版では 0〜15 を直線で VCM に割り当てているだけなので、実際の距離との対応は実測で較正する

## 長秒露光

- rpicam: 「フレームレートで決まる上限を超える露光を指定すると、上限の値が使われる」。上限そのものを超える値は undefined behaviour（公式）
- 公式の例（AE と AWB を止めることを推奨している）

  ```bash
  rpicam-still -o long_exposure.jpg --shutter 100000000 --gain 1 --awbgains 1,1 --immediate
  ```

- Picamera2 では、`FrameDurationLimits` を露光時間以上に広げる必要がある（推定）

  ```python
  picam2.set_controls({"ExposureTime": t, "AnalogueGain": 1.0, "FrameDurationLimits": (t, t)})
  ```

- IMX519 の最長露光は公称 200 秒。理論上はフル解像度で約 249 秒、2328×1748 で約 128 秒（推定）

## 実機で確かめること

- [ ] Arducam 版 libcamera を入れた状態で、Picamera2 から `LensPosition` が効くか
- [ ] `ExposureTime` / `AnalogueGain` / `LensPosition` の実際の範囲（`camera_controls` で確認）
- [ ] 露光時間を変えた連続撮影（ブラケット）で、各フレームに設定が反映されるまでの遅れ
- [ ] DNG のメタデータ（色行列、ブラックレベル）が現像に使えるか
