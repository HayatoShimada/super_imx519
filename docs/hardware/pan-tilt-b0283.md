# Arducam Upgraded Pan-Tilt Platform（SKU: B0283）

確認日: 2026-10-07

根拠の表記: **公式** = メーカーの文書やソースコードに記載 / **推定** = 計算や推論による値 / **未確認** = 裏付けが取れていない

## 主な出典

- 取説: [B0283_Manual.pdf](B0283_Manual.pdf)（このリポジトリに保存。[配布元](https://www.welectron.com/mediafiles/productimg/arducam/Amazon/B0283_Manual.pdf)）
- [製品ページ（uctronics）](https://www.uctronics.com/arducam-upgraded-camera-pan-tilt-platform-for-raspberry-pi-nvidia-jetson-nano-xavier%20nx.html)
- [デモコード ArduCAM/PCA9685](https://github.com/ArduCAM/PCA9685)
- [PCA9685 データシート（NXP Rev.4）](https://cdn-shop.adafruit.com/datasheets/PCA9685.pdf)
- [販売店ページ（welectron、サーボ型番）](https://www.welectron.com/Arducam-B0283-Upgraded-Camera-Pan-Tilt-Platform-for-Raspberry-Pi)

## 要点（設計に効くもの）

- **取説の手順は今のリポジトリでは動かない**。2024-03-29 の PR #9 で、ルートの `makefile` と `src/RunServoDemo.c` が削除された（issue #10）。現行の手順は次のとおり

  ```bash
  git clone https://github.com/ArduCAM/PCA9685.git
  cd PCA9685/example/rpi && make && sudo ./run_servo
  ```

- **デモは移動した後も PWM を出し続ける**。サーボが位置を保持しようとして微振動するおそれがあるので、撮影前に full-off で止める（[止め方](#pwm-を完全に止める方法)）
- **サブピクセル単位の微動には刻みが粗い**。1 tick は約 0.44° で、IMX519 では約 27px ずれる（[分解能の試算](#分解能の試算)）。超解像に使えるかは [DESIGN.md の検証計画](../../DESIGN.md#パンチルト微動の検証計画) で確かめる

## 仕様（取説より・公式）

| 項目 | 値 |
| --- | --- |
| 制御ボード | PCA9685、12bit PWM、I2C、3.3V / 5V、38 × 28 mm |
| サーボ | デジタル ×2、3.6〜4.8V、< 350mA、トルク 0.6 kg·cm @3.6V / 0.8 kg·cm @4.8V、3.7 g、20.0 × 8.75 × 22.0 mm |
| 動作速度 | 0.13 s/60° @3.6V、0.09 s/60° @4.8V |
| デッドバンド | 3 µs |
| 可動範囲 | パン 180° / チルト 180° |

- サーボの型番は **GH-S37D**（デジタル、プラスチックギア、コアレスモーター）（公式・販売店）
- サーボ単体の販売ページには「Signal Range 1000–2000 µs、Operating Angle 90°」とあり、Arducam の「180°」と食い違う（[rcdrone](https://rcdrone.top/products/pes-gh-s37d-3-7g-digital-micro-servo-plastic-gear-coreless-motor-3-6-4-8v-for-rc-airplane-glider-car)）。どちらで計算しても約 11.1 µs/° になる（推定）

### 取説の注意書き

- 組み立てのときは、サーボホーンを元の位置のまま取り付ける。そうすれば再キャリブレーションが要らない
- 配線はサーボ線の色に合わせる。付属のジャンパー線の色は区別用で、意味は無い

## デモコード（ArduCAM/PCA9685）の中身

| 項目 | 内容 | 根拠 |
| --- | --- | --- |
| I2C | `/dev/i2c-1`、アドレス `0x40` | 公式（`example/rpi/main.c`, `PCA9685.h`） |
| PWM 周波数 | `setPWMFreq(60)` を呼ぶ。関数の中で `freq *= 0.8449` と補正するので、プリスケールは 119。25 MHz が正確なら約 50.9 Hz | 公式（ソース）＋推定 |
| 角度とパルス幅 | `pulse = (deg+45)/(90*1000)` 秒。0° = 0.5 ms、90° = 1.5 ms、180° = 2.5 ms | 公式（ソース） |
| 角度と tick | 60Hz を前提に 1 tick ≈ 4.069 µs と計算し、切り捨て。0° = 122、90° = 368、180° = 614、1° あたり約 2.73 tick | 推定 |
| チャンネル（C 版） | ch0 = `SERVO_UP_CH`（↑↓、15〜145°）、ch1 = `SERVO_DOWN_CH`（←→、0〜180°） | 公式（ソース） |
| チャンネル（Jetson 用 Python 版） | C 版と割り当てが逆。実際にどちらがパンかは配線しだい | 未確認 |
| 1 回の移動量 | C 版はキー 1 回で 1°、Python 版は 5° | 公式（ソース） |
| 起動時の位置 | 両軸とも 90° | 公式（ソース） |
| 終了時 | full-off にせず、PWM を出し続ける | 公式（ソース） |

- 補正係数 0.8449 は、発振器が約 18% 速い個体を想定しているように見える。公称の 25 MHz どおりなら、実際のパルスは 0° ≈ 586 µs、180° ≈ 2.95 ms になってしまう（推定）。**実際の周波数は実測が必要**
- Arducam 独自の Python ライブラリは無い。Jetson 用の例は `adafruit-circuitpython-servokit` を使っている。その既定は 50Hz・750〜2250 µs で、C 版とは角度の対応が違う

## 配線

- 文字で書かれたピン表は無く、取説には図があるだけ（未確認）
- 旧ソースのピン定義と Pi の標準 I2C1 から、SDA = GPIO2（物理ピン 3）、SCL = GPIO3（物理ピン 5）と推定
- VCC を 5V と 3.3V のどちらにつなぐか、外部電源の入力があるかは未確認。サーボ電源も VCC から取っている可能性が高い（推定）
- Pi 側の I2C 設定と給電については [raspberry-pi-4.md](raspberry-pi-4.md) を参照

## PWM を完全に止める方法

- データシート（公式）: LEDn_OFF_H の bit 4 を 1 にすると、そのチャンネルは常に OFF になる（ON 側より優先される）。全チャンネルを止めるなら `ALL_LED_OFF_H`（0xFD）の bit 4
- smbus2 の場合: `bus.write_byte_data(0x40, 0x09 + 4*n, 0x10)`（n = チャンネル番号）
- Adafruit ServoKit の場合: `kit.servo[n].angle = None`。レジスタに (0, 0x1000) が書かれ、full-off になる
- `PCA9685.deinit()` は MODE1 に 0x00 を書くだけで、出力は止まらない（推定）
- デジタルサーボは、信号が止まると位置を保持するものと脱力するものがあり、どちらになるかは文書化されていない（[Pololu](https://www.pololu.com/blog/17/servo-control-interface-in-detail)）。**GH-S37D がどちらかは未確認**。脱力する場合、カメラの重さをギアの摩擦だけで支えられるかも確かめる

## PCA9685（データシート・公式）

- 12bit（4096 段階）。周波数は 24〜1526 Hz（typical）。プリスケールは SLEEP 中にしか書き込めない
- プリスケールの計算式: `prescale = round(osc / (4096 × rate)) − 1`
- 内部発振器は 25 MHz（typical）。許容誤差はデータシートに無い。Adafruit は「約 23〜27 MHz」と書いている
- 外部クロック（EXTCLK）は最大 50 MHz

## 分解能の試算

（推定）IMX519 は f = 4.28 mm、画素 1.22 µm なので、1 画素 = 0.0163°、半画素 = 0.0082°。サーボは 2000 µs で 180°、つまり 11.1 µs/° として計算した。

| 周波数 | 1 tick | 角度 | IMX519 でのズレ |
| --- | --- | --- | --- |
| 50 Hz | 4.88 µs | 0.44° | 約 27 px |
| 200 Hz | 1.22 µs | 0.11° | 約 6.7 px |
| 333 Hz | 0.73 µs | 0.066° | 約 4.0 px |
| （サーボのデッドバンド 3 µs） | — | 0.27° | 約 17 px |

- 周波数を上げると指令は細かくなるが、実際に動ける最小量の下限はサーボのデッドバンドで決まる
- GH-S37D が 200〜333 Hz を受け付けるかは未確認。333 Hz なら周期 3 ms に最大パルス 2.5 ms が収まる
- サブピクセルのズレは「指令どおり」には作れず、誤差として偶然に生まれる。そのため画像の位置合わせが必須になる
- ズレ量が大きいこと自体は超解像の妨げにならない。効くのはズレの小数部の分布
- プラスチックギアなので、バックラッシュが 0.27° より大きい可能性がある（推定）
- このバックラッシュとデッドバンドの使い方は、目的によって逆になる
  - **構図を再現したいとき**: 目標位置には常に同じ方向から近づけ、誤差を減らす
  - **超解像用のズレを作るとき**: ランダムに動かしてから同じ指令値に戻し、誤差をズレとして使う（[DESIGN.md](../../DESIGN.md#微動の作り方-ランダムに動かしてから元の位置に戻す主方式)）

## 実機で確かめること

- [ ] VCC のつなぎ先（5V / 3.3V）と外部電源の入力の有無
- [ ] `i2cdetect -y 1` で 0x40 が見えるか
- [ ] パンとチルトがどのチャンネルにつながっているか
- [ ] PWM の実周波数（オシロで測る。無ければ画像で角度を測って、ServoKit の `reference_clock_speed` を較正する）
- [ ] GH-S37D が信号を切っても位置を保持するか
- [ ] 200〜333 Hz の PWM で動くか
- [ ] 同じ角度へ戻したときの位置の再現性と、静止時のゆらぎ
