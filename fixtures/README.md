# fixtures

SWORD API のテスト入力（登録用 ZIP など）。**生成物は ZIP を含めてコミットせず、
生成器 `seeds/build_fixtures.py` とその記録 `manifest.json` をコミットする。**

```sh
uv run python seeds/build_fixtures.py build          # fixtures/generated/*.zip を作る
uv run python seeds/build_fixtures.py build --check  # manifest.json が最新か確認（CI でも実行）
uv run python seeds/build_fixtures.py digest FILE    # Digest ヘッダ値（SHA-256=<hex>）
uv run python seeds/build_fixtures.py put-item --id 42 --out fixtures/generated/put-42.zip
uv run python seeds/build_fixtures.py sized --size 1048576 --out fixtures/generated/sized.zip
```

- ZIP は無圧縮・固定日時・固定順で作るため、どの環境でも同じバイト列・同じハッシュになる。
  そのため `manifest.json` の `digest` を仕様書やケースにそのまま書ける。
- `manifest.json` は S0-04 の一覧（用途・サイズ・ハッシュ）の機械可読版。生成器を変えたら
  `build` を再実行して一緒にコミットする。

## 一覧（S0-04）

用途は `manifest.json` の `purpose` を参照。正常系（SimpleZip・SWORDBagIt・RO-Crate・XML）、
壊れた ZIP、bagit チェックサム不一致、bagit 構造欠落（`bagit.txt` なし）、文字コード不正
（Shift_JIS）、JSON-LD 構文エラー（行・列は `facts` に記録）、メタデータ欠落、Packaging 構成不正
（SimpleZip に sword.json、RO-Crate の `ro-crate-metadata.json` 位置違い）、複数アイテム、
タイトル違い・類似ファイル、EP4 用のアイテム（ID なし／ID 指定）。

## Digest

weko の `is_valid_file_hash` は、ヘッダの `SHA-256=` 以降を、アップロードされた**ファイルパート**
（ZIP のバイト列。multipart 全体ではない）の SHA-256 の小文字 16 進と比較する。
Base64 ではない。不一致ケースは、別ファイルの Digest を付ける。

## Content-Length 境界（S5-03）

weko は `Content-Length` ヘッダ（multipart 全体の長さ）を上限と比較する。
`sized` はファイルパートの前後の multipart 部分の長さを差し引いて、リクエスト全体が
ちょうど指定バイト数になる ZIP を作る。

制限:

- 本スイートの HTTP 実行器（httpx、境界文字列 32 文字、ファイル名 `.zip`）で送る前提。
  別のクライアントで送ると長さがずれる。`--filename` はパートのファイル名と一致させる。
- 最小値より小さい指定は拒否する（`payload.zip` で約 600 バイト）。
- メモリ上に作るため、既定の上限（約 15.6 GiB）ではなく、S0-12 のとおり上限を小さく
  下げて（例: 1 MiB）使う。

## 内容の限界

構造（アーカイブ構成・BagIt のマニフェスト・パッケージ判定・JSON 構文）は weko が見る
ものに合わせてある。一方、メタデータの**中身**（CSV の列、XML、RO-Crate の項目）は汎用の
最小形で、対象環境のアイテムタイプや SWORD クライアントのマッピングには合っていない。
そのため、アイテム登録まで進むケースには、対象環境から書き出したメタデータの差し替えが
必要（オーナー確認事項）。
