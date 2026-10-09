# Raspberry Pi 4 Model B（エッジ）

確認日: 2026-10-07

根拠の表記: **公式** = Raspberry Pi やライブラリの文書・ソースに記載 / **推定** = 計算や推論による / **未確認** = 裏付けが取れていない

## I2C

### パンチルト用（i2c-1）を有効にする

- `sudo raspi-config` → `3 Interface Options` → `I5 I2C`（[公式](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/configuration/interfaces.adoc)）
- 内部では `dtparam=i2c_arm=on` を書き込み、`i2c-dev` を読み込んでいる（[raspi-config](https://github.com/RPi-Distro/raspi-config/blob/master/raspi-config) の `do_i2c`）
- `i2c_arm` の既定は off。`i2c_arm_baudrate` の既定は 100000（[overlays README](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/arch/arm/boot/dts/overlays/README)）
- 確認方法: `i2cdetect -y 1` で、PCA9685 のアドレス 0x40 が見えるか

### カメラ側の I2C とは衝突しない

- Pi 4 のカメラ用 I2C は `i2c_csi_dsi` で、GPIO 44/45 の i2c-0 をマルチプレクサ経由で使い、`/dev/i2c-10` として見える（公式: overlays README、[bcm270x-rpi.dtsi](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/arch/arm/boot/dts/broadcom/bcm270x-rpi.dtsi)）
- パンチルトの i2c-1（GPIO2/3）とは別のコントローラなので、衝突しない
- **`i2c_vc` は有効にしない**。README に「Pi カメラと干渉する」とある

### config.txt に書くこと（まとめ）

```ini
# /boot/firmware/config.txt
camera_auto_detect=0
dtparam=i2c_arm=on

[all]
dtoverlay=imx519
```

IMX519 側の詳細は [imx519.md](imx519.md) を参照。

## 電源

- Pi 4 の公式値: 推奨電源 3.0 A。USB 機器の合計上限 1.2 A、本体の消費 600 mA、カメラモジュール 250 mA（[power-supplies.adoc](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/power-supplies.adoc)）
- 5V ピンから取れる電流の公式値は未確認
- 計算上は 3 A − 0.6 A − 0.25 A ≈ 2.1 A の余裕があり、サーボ 2 個 × 350 mA は収まる（推定）。ただしサーボが動くときの電圧降下は起こり得る
- Adafruit: 「マイクロサーボでも動くときは数百 mA 流れる」。コンデンサは n × 100 µF を推奨（[Powering Servos](https://learn.adafruit.com/adafruit-16-channel-pwm-servo-hat-for-raspberry-pi/powering-servos)）
- 安定させたい場合は、サーボ用の外部 5V 電源を GND 共通でつなぐ。ただし B0283 の基板に外部電源の入力があるかは未確認（[pan-tilt-b0283.md](pan-tilt-b0283.md)）

## Python 環境

- Bookworm 以降の Raspberry Pi OS では、pip を使うのに **venv が必須**（PEP 668。[Adafruit](https://learn.adafruit.com/python-virtual-environment-usage-on-raspberry-pi)）
- Picamera2 は apt で入れる（`python3-picamera2`）。そのため venv は `--system-site-packages` 付きで作るのが一般的（推定）
- PCA9685 を操作する方法

| 方法 | 入手 | 特徴 |
| --- | --- | --- |
| smbus2 | apt（`python3-smbus2`、bookworm / trixie にある）または pip | レジスタを直接操作する。依存が軽い |
| `adafruit-circuitpython-servokit` / `-pca9685` | pip（venv 内） | 既定でアドレス 0x40、50 Hz、25 MHz。`reference_clock_speed` で補正できる（[ServoKit](https://github.com/adafruit/Adafruit_CircuitPython_ServoKit)、[PCA9685](https://github.com/adafruit/Adafruit_CircuitPython_PCA9685)） |
| カーネルドライバ | `dtoverlay=i2c-pwm-pca9685a` | `/sys/class/pwm` から操作する（overlays README） |

## 実機で確かめること

- [ ] OS のバージョン（Bookworm / Trixie）
- [ ] サーボが同時に動いたときに、Pi が電圧低下の警告を出さないか（`vcgencmd get_throttled`）
