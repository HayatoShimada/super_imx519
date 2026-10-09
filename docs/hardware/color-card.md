# カラーキャリブレーションカード（Sxhlseller 24 色）

確認日: 2026-10-07

## 要点

- **Calibrite ColorChecker Classic の互換品**（ユーザー確認、2026-10-07）。購入時の比較対象は Amazon.co.jp の「calibrite COLORCHECKER CLASSIC 国内正規品」
  - 4 × 6 の 24 パッチで、並び順は Classic と同じ前提とする。届いた実物で目視確認する
- **パッチの色が本物と一致する保証は無い**。販売元（Sxhlseller）は、グラフィックボードや腕時計など、ジャンルの違う商品を大量に出品している汎用ブランドで、色彩測定の専門メーカーではない（例: [Amazon](https://www.amazon.com/dp/B0CHZF67VV)、[gosupps](https://www.gosupps.com/brands/sxhlseller.html)）。独自の基準値（Lab / 分光データ）も見つからなかった
- 手元の情報は 18.5 × 14.3 × 3 cm・134 g（梱包サイズの可能性が高い）。本物の Classic は約 27.9 × 21.0 cm で、パッチは約 5.1 cm 角、マット塗装（[Wikipedia](https://en.wikipedia.org/wiki/ColorChecker)）。互換品は一回り小さいと見込まれる（推定）
  - 1 m の距離では 1 mm ≈ 3.5 px なので、パッチが 3 cm 角でも約 100 px 角に写る。測定には十分

## パッチの並び（ColorChecker Classic）

| 行 | 1 | 2 | 3 | 4 | 5 | 6 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | dark skin | light skin | blue sky | foliage | blue flower | bluish green |
| 2 | orange | purplish blue | moderate red | purple | yellow green | orange yellow |
| 3 | blue | green | red | yellow | magenta | cyan |
| 4 | white 9.5 | neutral 8 | neutral 6.5 | neutral 5 | neutral 3.5 | black 2 |

4 行目がグレースケール（無彩色）。WB と露出の基準に使う。

## このプロジェクトでの使い方

| 用途 | 使えるか |
| --- | --- |
| ショット間・日ごとの色の一貫性（同じカードを毎回写し込み、その写り方を揃える） | 使える |
| 4 行目のグレーでの WB・露出合わせ | 使える。ただしグレーが無彩色か、実物で確かめる |
| Classic の公開基準値を目標にした CCM（色補正行列）の算出 | **近似として使える**。互換品の色ずれが、そのまま補正の誤差になる |
| 色の正しさの絶対評価（ΔE を「正解」と比べる） | 使えない。正規品が必要 |

### 互換品の色ずれを見積もる方法（案）

- 照明と WB を整えて撮り、公開基準値で CCM を作る。そのときの残差 ΔE を見る
  - 特定のパッチだけ大きくずれるなら、そのパッチの印刷が本物と違うと疑い、CCM の計算から外す
- 正規品の Classic を一度だけ借りるか買い、同じ条件で並べて撮れば、互換品の各パッチのずれを実測できる。実測したずれを互換品用の基準値として保存すれば、以後は互換品だけで運用できる

## 基準データ（正規の ColorChecker Classic 用）

- **[BabelColor](https://babelcolor.com/colorchecker-2.htm)**
  - X-Rite 公式の L\*a\*b\*（D50）を、2014 年 11 月以前と以後の 2 版で提供している（`ColorChecker24_Before_Nov2014.txt` / `ColorChecker24_After_Nov2014.txt`）
  - 30 枚平均の分光データ（CGATS / CxF3）、19 色空間の RGB 値、測定条件（45°/0°）、ロット間のばらつき統計もある
  - 2014 年 11 月以降は、白パッチが L\*=96.5 → 95.2、b\*=1.2 → 2.9 に変わった
  - 互換品がどちらの版を模したかは分からない。そのため、2 版で CCM の残差を比べ、小さいほうを採る（案）
- **[colour-science](https://colour.readthedocs.io/)**（Python）: 同じ基準値を収録している
- **OpenCV contrib**
  - `mcc` モジュール（`cv2.mcc.CCheckerDetector`）で、画像から ColorChecker 24（MCC24）を自動検出できる
  - `ccm` モジュール（`cv2.ccm.ColorCorrectionModel`）に Macbeth / ColorChecker の基準値が入っていて、CCM を計算できる
  - どちらも contrib 版（`opencv-contrib-python-headless` など）が必要。`rocm_opencv_server` は `opencv-python-headless>=4.10`（`pyproject.toml`）なので、このままでは使えない

### 互換品に公式値を当てるときの注意

- 互換品の顔料・印刷が本物と同じだという保証は無い。分光特性（メタメリズム）もばらつきも違いうる
- X-Rite の製品同士（ColorChecker 24 と SG）でも、平均 ΔE\*ab ≈ 7（CIEDE2000 で 3.7）の差が報告されている（[Kasson](https://blog.kasson.com/the-last-word/cc24-vs-ccsg-spectra-and-cielab-values)）

## 実機で確かめること

- [ ] パッチの並びが上の表と同じか
- [ ] 実寸（カード全体とパッチの大きさ）
- [ ] 表面がマットか（照明の映り込み）
- [ ] 4 行目のグレーが無彩色か（WB を合わせた後に R=G=B に近いか）
- [ ] 公開基準値（2014 年 11 月以前・以後）で CCM を作ったときの、パッチごとの残差 ΔE
- [ ] 四隅の十字マークなど、自動検出の手がかりがあるか
