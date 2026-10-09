# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 現状

設計段階。サーバー側の合成の試作（`src/super_imx519/pipeline/stacking.py`、`scripts/stack_session.py`）がある。ドキュメントは日本語で書く。

- テストとリント: `uv sync && uv run pytest`、`uv run ruff check . && uv run ruff format .`

- `DESIGN.md`: 設計の判断・構成・撮影技法・検証計画・未決事項。作業の前に必ず読む
- `docs/`: 継続して参照する資料（索引は `docs/README.md`）
  - `docs/hardware/`: 機材ごとの仕様と調査メモ（出典付き）
  - `docs/software/`: カメラ制御の方法、85store-cms の仕様
  - `docs/background/`: 方向性を決めた経緯
- 新しく調べた事実は `docs/` に出典 URL と確認日を付けて追記する。根拠は「公式 / 推定 / 未確認」で区別する。設計の判断は `DESIGN.md` に書く

## プロジェクト概要

壁にハンガーで掛けた洋服を、Arducam IMX519（16MP / AF）で撮る物撮りシステム。実物どおりの質感で、EOS R6 並みの見た目を目指す。出力は自社 EC（85-store、Shopify。テーマは `../85store-theme`）の商品画像。

- **AI 生成系の超解像（Real-ESRGAN など）は使わない**。実物にある情報だけで画質を上げる。手段は RAW、露出ブラケットによる HDR、マルチフレーム超解像、フォーカススタッキング、カラーカードでの色合わせ
- **エッジ**: Raspberry Pi 5（`hacopi@85pi`、ほかの用途と兼用）。IMX519 で撮影し、パンチルト（Arducam B0283、PCA9685 を I2C で制御）で構図と微動を作る。コードは別リポジトリの [imx519_edge](https://github.com/HayatoShimada/imx519_edge)（home-linux は `../imx519_edge`、85pi は `~/imx519_edge` に clone し、`git pull` で更新する）
- **画像処理サーバー**: `home-linux`（Tailscale `100.108.168.101`）。重い処理はこのリポジトリで行う
- **撮影した写真の行き先**: 85store-cms（`../85store-cms`、`https://cms.85-store.com`）の商品の下書き。商品は **CMS の商品 ID** で特定する（handle は途中で変わる）。連携の設計は DESIGN.md の「撮影アプリと 85store-cms の連携」

## 実行環境についての注意

- この作業ディレクトリがあるマシンが `home-linux`（サーバー側）。カメラは `85pi` に繋がっているので、撮影は `ssh hacopi@85pi` 経由で行う。85pi の sudo にはパスワードが要る
- 撮影データはリポジトリの外に置く。セッションは `~/data/super_imx519/sessions/<session_id>/`、処理の結果は `~/data/super_imx519/results/`。DNG は 1 枚約 33 MB で、1 カットは約 1 GB。85pi は空きが約 20 GB しかないので、撮影データを貯めない
- 85pi と home-linux は、どちらも管理者のタグなしの端末なので、85store-cms の REST（`https://cms.85-store.com/api/...`）を管理者として呼べる（CMS は Tailscale の whois で認証する）。**本番の CMS なので、書き込む前に確認する**。CMS のコードを直すときは 85store-cms のリポジトリで PR を出す
- 隣の `../rocm_opencv_server/` は、同じホストで動く OpenCV 画像処理 API。処理は載せず、写真の区分の判定（Clef）だけを借りる。その `uv sync` は全グループを指定しないと torch / CLIP が消えるので、テストは `uv run --no-sync pytest` で走らせる

## 実装時の落とし穴（詳細は docs/ にある）

- **IMX519 の AF と `LensPosition`**: Arducam 版 libcamera が必須。Raspberry Pi 版の tuning ファイルには `rpi.af` が無く、レンズ位置の指定が無視される。センサー HDR も使えない（Pi 5 用の tuning ファイルにも `rpi.hdr` が無いことを確認済み）ので、HDR は露出ブラケットで撮ってソフトで合成する
- **B0283 の取説の手順**（`make` → `./RunServoDemo`）は古い。現行のデモは `ArduCAM/PCA9685` の `example/rpi`
- **PCA9685 は移動後に PWM を出し続ける**。撮影前に full-off（LEDn_OFF_H の bit 4、ServoKit なら `angle = None`）で止める
- **カメラとパンチルトの I2C**: パンチルトは i2c-1（GPIO2/3、アドレス 0x40）。カメラは CSI 側の別バス（Pi 4 は i2c-10、Pi 5 は RP1 の `i2c@80000`）なので衝突しない。`i2c_vc` は有効にしない
- **取説の PDF**: `docs/hardware/B0283_Manual.pdf` は画像主体で、テキスト抽出がほぼできない。Read ツールで見る
