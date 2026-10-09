# docs

設計と実装のときに継続して参照する資料。設計の判断そのものは [DESIGN.md](../DESIGN.md) に書き、ここには機材の仕様・調査メモ・検討経緯を置く。

## 索引

| ファイル | 内容 |
| --- | --- |
| [hardware/imx519.md](hardware/imx519.md) | Arducam IMX519。センサー・レンズ・露出の仕様、AF、セットアップ、DNG、HDR |
| [hardware/pan-tilt-b0283.md](hardware/pan-tilt-b0283.md) | パンチルト B0283。仕様、デモコードの現状、PWM の止め方、分解能の試算 |
| [hardware/B0283_Manual.pdf](hardware/B0283_Manual.pdf) | B0283 のクイックスタート（メーカー取説） |
| [hardware/neewer-nl-192ai.md](hardware/neewer-nl-192ai.md) | 照明 NEEWER NL-192AI |
| [hardware/color-card.md](hardware/color-card.md) | 24 色カラーカードと、色の基準データ |
| [hardware/raspberry-pi-4.md](hardware/raspberry-pi-4.md) | Raspberry Pi 4 の I2C・電源・Python 環境 |
| [software/camera-control.md](software/camera-control.md) | Picamera2 / rpicam-still の制御方法 |
| [software/85store-cms.md](software/85store-cms.md) | 85store-cms の商品・写真・認証の仕様（撮影した写真の行き先） |
| [background/discussion-2026-10.md](background/discussion-2026-10.md) | 方向性を決めた会話の要約（目標、技法、機材選定の理由） |

## 書き方のルール

- 冒頭に確認日を書き、数値や記述ごとに出典 URL を付ける
- 根拠の確かさを **公式** / **推定**（計算・推論） / **未確認** で区別する
- 末尾の「実機で確かめること」に、実測が必要な項目をチェックリストで残す。実測したら結果を本文に書き、チェックを付ける
- 外部の PDF はリポジトリに置かず、URL で参照する（例外: メーカー取説 `hardware/B0283_Manual.pdf`）
