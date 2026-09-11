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

## 開発の規約

AI エージェント向けの規範は [AGENTS.md](./AGENTS.md) に、コミット規約は
[docs/GIT.md](./docs/GIT.md) にある。
