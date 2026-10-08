# weko-test-suite

WEKO3 の結合テスト仕様と、[agentic-test-hub](https://github.com/ivis-kuroda/agentic-test-hub)
用のプラグインを保持するリポジトリ。

## 役割分担

| | 担当 |
|---|---|
| `agentic-test-hub` | 汎用の仕組み。スキーマ、編集 UI、マトリクス導出、出力、実行基盤 |
| **このリポジトリ** | WEKO3 固有のすべて。テスト仕様、操作の実体、状態の作り方、納品様式 |

hub は WEKO3 について何も知りません。`shell` / `http` / `sql` / `browser` の
4 種類の動かし方だけを知っており、それをどう組み合わせて WEKO3 を操作するかは
`plugin.yaml` が決めます。

## ディレクトリ

```
plugin.yaml            操作・接続・状態プロバイダの宣言
specs/
  viewpoints/          テスト観点（レビュー対象の中心）
  factors/             因子と水準（マトリクスの軸）
  matrices/            マトリクスの軸・方針・除外理由
  baselines/           ケース群が共有する完全な実行定義
  operations/          仕様側から参照する共通操作
  cases/               マトリクス型のテストケース
  scenarios/           順序と状態に依存するシナリオ
fixtures/              テストデータ
seeds/                 前提条件を作る Python スクリプト等
templates/             納品用 Excel の様式
tests/                 生成された Playwright コード
```

## なぜ仕様を weko 本体に置かないか

- `weko` は上流 OSS のフォークであり、仕様書ツリーを足すと上流マージが複雑化する
- 既存の仕様書が「ブランチ名」と「コミットID」を記録する運用を確立済みなので、
  別リポジトリでも追跡性は失われない。スキーマ側の `appliesTo.commit` が
  その慣行をそのまま構造化している

## ツール

`tools/` に仕様の取り込みと静的検査の小さなスクリプトがある（Python 3.11 標準ライブラリ
＋ openpyxl。`uv` で実行）。

```sh
cd tools
uv sync

# 観点表（xlsx）とケース仕様書（md）から観点 YAML・コード対応表・トレース表を生成する。
# 出力は入力のみで決まり、再実行しても同一バイト列になる。
uv run python import_viewpoints.py --xlsx <観点表.xlsx> --spec-md <仕様書.md> --out-root ..

# weko の errors.py をコード対応表と静的に突き合わせる（weko は import しない）。
uv run python check_error_codes.py \
  --errors <weko>/modules/weko-swordserver/weko_swordserver/errors.py \
  --map ../fixtures/error-code-map.json \
  --catalog <weko>/modules/weko-swordserver/weko_swordserver/translations/en/LC_MESSAGES/messages.po

uv run ruff check . && uv run pytest
```

`check_error_codes.py` の終了コードは、差異なしが 0、差異ありが 1、引数・解析エラーが 2。

生成物（`specs/viewpoints/`・`fixtures/error-code-map.json`・`docs/spec-trace.md`）は
機械生成の提案であり、`spec-draft/*` ブランチでレビューしてから取り込む。

## hub の使い方・生成・検証

hub は隣のディレクトリのチェックアウトを使い、コミットは `hub.lock` で固定する
（詳細は [docs/HUB.md](./docs/HUB.md)）。

```sh
scripts/bootstrap-hub.sh          # hub を用意（無ければ clone、pnpm install）
uv sync                           # Python 環境
scripts/gen-test.sh <TC-id|SC-id> # tests/generated/ にテストを生成
scripts/check.sh                  # ruff・pytest・hub による検証（CI と同じ）
```

テストデータは `seeds/build_fixtures.py` が決定的に生成する（[fixtures/README.md](./fixtures/README.md)）。
`plugin.yaml` の SWORD v3 操作・docker 操作・証跡収集、`weko_suite_ext/`（コンテナ内ヘルパー
`helpers/` を呼ぶホスト側拡張）、必要な環境変数は `.env.example` にある。

## 実環境（ローカルの WEKO）での実行

実 WEKO への実行は、ローカルマシンの新しい Claude Code セッションで行う。手順は
`.claude/skills/` の 4 つのスキル（`weko-env-up`、`sword-test-run`、`weko-fault-injection`、
`weko-helpers`）にある。引き継ぎ文書 `HANDOFF.md` は一時ブランチ
`tmp/handoff-sword-error-codes` にだけ置く（機能ブランチには入れない）。
4xx の前の ERROR 行（A-5）は不合格にせず「保留」として記録する（[docs/TIER1-STATUS.md](./docs/TIER1-STATUS.md)）。

## 開発の規約

AI エージェント向けの規範は [AGENTS.md](./AGENTS.md) に、コミット規約は
[docs/GIT.md](./docs/GIT.md) にある。
