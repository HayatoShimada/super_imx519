# 85store-cms（商品の入力画面）との連携に効く仕様

確認日: 2026-10-09

撮影した写真の行き先である 85store-cms（Payload 3。85pi の docker compose で動く。`https://cms.85-store.com`）の、
商品・写真・認証の仕様。出典は 85store-cms のリポジトリ（`~/orca/85store-cms`、コミット `dbacab5`）のファイル。
数値の分布は、同じ日に REST API で取った値。

## 商品（`src/collections/Products.ts`）

- **正は Shopify**。CMS は入力画面で、開いたときと 10 分ごとに Shopify から取り込み、保存すると Shopify に送る（公式: リポジトリの CLAUDE.md）
- 撮影時に入れる候補の欄

  | 欄 | 型 | 値 |
  | --- | --- | --- |
  | `kind`（区分） | select・必須 | `used`（古着）/ `new`（新品）/ `consignment`（委託）。既定 `used` |
  | `brand`（ブランド） | brands への参照 | brands の `name`（一意）と `titleLabel`（商品名での表記） |
  | `name`（品名） | text | 例: Italian Velor 3B Jacket |
  | `autoTitle` | checkbox | 既定 true。ブランドと品名から商品名を作る |
  | `title`（商品名） | text・必須 | `[BRAND] 品名 [USED]`。自動コレクションが商品名で判定している |
  | `productType`（品目） | text | 例: Shirts、Coats & Jackets |
  | `categoryId` / `categoryName` | text | Shopify の標準の分類（`gid://shopify/TaxonomyCategory/aa-1-13-7` など） |
  | `status` | select・必須 | `draft` / `active` / `archived`。既定 `draft` |

- `variants[]` は最低 1 行で、`price` が必須（min 0）。`sku`・`cost`・`initialQuantity` は「作成時だけ送ります」
- `images[]` の各行: `photo`（productPhotos への参照）、`alt`、`autoAltLabel`（隠し欄。写真の区分）、`shopifyUrl`、`shopifyMediaId`
- `addPhotos`（virtual）に productPhotos の ID を入れて保存すると、`images` の末尾に足される（`src/shopify/bulk-photos.ts`）
- 削除はできない（`delete: () => false`）。やめる商品はアーカイブにする

### 商品名の作り方

- `productBeforeChange`（`src/shopify/product-hooks.ts:39-44`）が、`autoTitle` が true で `name` があり、ブランド・品名・区分・末尾のどれかが変わったときに、`titleFrom()` で `title` を作り直す
- `title` は必須の欄なので、検証はこの処理より前に走る。API で作るときは仮の値を入れて送る（保存時に置き換わる）（推定。Payload の処理順 beforeValidate → validate → beforeChange から）

### Shopify への同期の制約

- 保存のたびに `afterChange` から `queueProductSync` で Shopify に送る（`SHOPIFY_SYNC_MODE` が `off` 以外のとき）
- **SKU・原価・初期在庫は、Shopify に商品を作るときにしか送らない**（`src/shopify/sync.ts:191-243` の `productSetInput`。`creating` のときだけ `inventoryItem` と `inventoryQuantities` を入れる）。後から CMS で入れても Shopify には届かない
- **handle は変わる**: 新しい商品と、下書きから公開に変えた商品は、題名から handle を作り直す（`src/shopify/handle.ts`。公開中は変えない）。商品を特定するキーには使えない。CMS の商品 ID（数値）か、Shopify の商品 ID（`shopify.productId`。作成後にだけある）を使う

## 商品写真（`src/collections/ProductPhotos.ts`）

- 新しく撮った写真の一時置き場（85pi の `/data/product-photos`）。商品を同期するときに Shopify へ staged upload し（`src/shopify/upload.ts`）、手元のファイルは消す。R2 には置かない
- アップロード時の変換（sharp）
  - 長辺 2048px 以内に縮める（`fit: inside`、`withoutEnlargement`）
  - JPEG（品質 85、mozjpeg）に変換し、EXIF を消す
- 長辺 2048px 以内の画像なら縮めない。JPEG への変換（品質 85）は必ずかかる（推定。`formatOptions` は常に効く）

## 写真の区分（alt）

- alt が空の写真は、Shopify に送るとき「商品名（正面）」のように区分を付ける。区分が無ければ「商品名（n枚目）」
- 区分の語は 16 個（`src/shopify/mapping.ts:162` の `AUTO_ALT_LABELS`）
  - 向き: 正面、背面、横、全体
  - 着用: 着用、着用・背面、着用・横
  - アップ: タグのアップ、ロゴ・プリントのアップ、生地のアップ、ボタン・ジッパーのアップ、襟元のアップ、袖口・裾のアップ、ポケットのアップ、傷・汚れのアップ
  - その他: ディテール
- rocm_opencv_server の `ALT_LABELS` と同じ（`app/shopify.py:217-236`。英語のキーは `VIEW_LABELS` の front / back / side、`PART_LABELS` の tag / print / fabric / fastener / collar / hem / pocket / damage）。区分は Clef で判定する（`app/clef.py`）。変えるときは両方直す
- **新しく足した写真では `autoAltLabel` が使われない**: `sync.ts:255` は `images[i]?.alt || autoAlt(desired.title, i)` で、区分を渡していない。既存の写真（`sync.ts:252`）は区分を使う

## 認証と API

- ログインは Tailscale の whois（`src/lib/tailscale-auth.ts`）。接続元の端末の持ち主のメールが「メンバー」（users）に登録されていれば入れる。**タグ付きの端末は通らない**
- home-linux と 85pi は、どちらもタグなしで、管理者のアカウントの端末。どちらからも `GET https://cms.85-store.com/api/users/me` が 200 で、`role: admin` が返った（2026-10-09 に実測）
  - つまり、この 2 台からは Payload の REST API（`/api/products`、`/api/brands`、`/api/productPhotos`）を管理者として呼べる。操作は管理者が行ったものとして記録される
- スタッフ（`autogroup:member`）は ACL で `tag:cms` の 443 番にしか入れない（リポジトリの README の ACL の例）
- CMS から外の内部 API を呼ぶときは `X-Internal-Token` を付ける（85crm: `CRM_INTERNAL_URL` / `CRM_INTERNAL_TOKEN`、rocm_opencv_server: `IMAGE_SERVER_URL` / `IMAGE_SERVER_TOKEN`）

## 選択肢になる既存の値（2026-10-09、REST で取得）

- 商品 433 件（区分: used 356 / new 77。状態: active 297 / archived 92 / draft 44）
- `productType` は 20 種類（Shirts 141、Coats & Jackets 67、空 47、Sweatshirts 42、T-Shirts 36、Sweaters 19、…）
- `categoryId` は 23 種類。名前が同じで ID が違うものがある（例: Sweatshirts が `aa-1-13-14` と `aa-1-1-7-4`）。選ぶ画面では ID も見せて区別する
- ブランド 106 件

## 実機で確かめること

- [ ] REST の `POST /api/products` で、仮の `title` と `variants: [{ price: 0 }]` を送ったとき、商品名が作り直されて保存されるか
- [ ] `POST /api/productPhotos`（multipart）で長辺 2048px 以内の JPEG を上げたとき、縮められずに品質 85 で再圧縮されるか
- [ ] `images` に `autoAltLabel` を入れて PATCH できるか（隠し欄だが、アクセス制限は無い）
