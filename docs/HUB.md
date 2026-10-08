# agentic-test-hub の使い方

このリポジトリは `agentic-test-hub`（以下 hub）を **隣のディレクトリのチェックアウト**
として使う。パッケージ公開や git サブモジュールは使わない（オーナー決定）。

```
<作業ディレクトリ>/
  agentic-test-hub/    hub（hub.lock の SHA に合わせる）
  weko-test-suite/     このリポジトリ
  weko/                テスト対象（任意）
```

## 固定するもの

| ファイル | 内容 |
|---|---|
| `hub.lock` | hub の URL と **コミット SHA**。生成・検証はこの SHA を前提にする |
| `pyproject.toml` | 生成テストの Python 環境。`agentic-test-hub-runner` を `../agentic-test-hub/python/agentic-test-hub-runner` のパス依存で参照する |
| `uv.lock` | Python 依存の固定 |

hub を更新したいときは `hub.lock` の SHA を書き換え、`scripts/check.sh` が通ることを
確認してから 1 コミットにする（SHA の変更は内容を見て判断する変更なので、オーナーに確認する）。

## 初回セットアップ

```sh
scripts/bootstrap-hub.sh     # hub が無ければ clone して SHA に合わせ、pnpm install
uv sync                      # Python 環境（runner・pytest・ruff）
```

- 前提: Node.js 22.18 以上（hub は 26 以上を宣言しているが、TypeScript を直接実行できれば動く。
  22 では pnpm が警告を出すだけ）、pnpm、uv、git。
- 既存の hub チェックアウトは **動かさない**（他の作業中かもしれないため）。SHA が違うと警告だけ出す。
- hub の場所を変えるときは `HUB_DIR=/path/to/agentic-test-hub` を指定する。
  ただし `pyproject.toml` のパス依存は `../agentic-test-hub` 固定なので、通常は隣に置く。

## テストを生成する

```sh
scripts/gen-test.sh TC-SWORD-001          # tests/generated/test_tc_sword_001.py ができる
scripts/gen-test.sh TC-SWORD-001 --force  # 再生成
```

中身は次のコマンドと同じ。

```sh
node ../agentic-test-hub/packages/cli/bin/generate-test.ts <ID> \
  --specs specs --plugin plugin.yaml --plugin-root . \
  --lang python --python-extensions-module weko_suite_ext \
  --out tests/generated/test_<モジュール名>.py
```

- 生成物は手で編集しない（再生成で消える）。直したいときは仕様か `plugin.yaml` を直す。
- ケースの生成に成功すると `specs/cases/<ID>.yaml` の `automation` が `generated` に更新される。
  テストと一緒にコミットする。
- `OP-HELPER` を使うケースは `weko_suite_ext`（リポジトリ直下）を import する。
  `pytest` はリポジトリ直下で実行すること（`pyproject.toml` が import パスを通す）。

### 仕様を別のチェックアウトから読む

仕様 YAML は `spec-draft/*` ブランチでレビューし、テストコードは機能ブランチへ入れる運用のため、
`SPECS_DIR` で仕様の場所を指定できる。`automation: generated` の書き戻しは `SPECS_DIR` 側のファイルに入る
（spec-draft 側でコミットする）。

```sh
git worktree add ../weko-test-suite-spec spec-draft/sword-error-codes
SPECS_DIR=../weko-test-suite-spec/specs scripts/gen-test.sh TC-SW-S5-01 --force
```

## 実行する

```sh
cp .env.example .env     # 値を埋める。.env はコミットしない
set -a; . ./.env; set +a
ATH_EVIDENCE_DIR=artifacts/evidence uv run pytest tests/generated/test_tc_sword_001.py   # または tests/generated 全体
```

`ATH_EVIDENCE_DIR` を指定すると証跡（HTTP 往復、アプリログ、DB レコードの前後、差分）が保存される。
`artifacts/` は `.gitignore` 済み。証跡は Authorization などをマスク済みだが、
**コミットしない**。

## 検証

```sh
scripts/check.sh    # ruff、pytest、hub による仕様・マニフェスト検証
```

CI（`.github/workflows/ci.yml`）も同じスクリプトを、`hub.lock` の SHA の hub を並べて実行する。
