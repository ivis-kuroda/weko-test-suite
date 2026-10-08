# HANDOFF: SWORD エラーコード結合テストを実 WEKO（ローカル）で実行する

一時ブランチ `tmp/handoff-sword-error-codes`。このファイルだけを持つ（機能ブランチ先端から分岐）。
作業が機能ブランチへ入ったらこのブランチは削除する。

## 1. 目的と到達点

WEKO3 の SWORD v3 エラーコード改修（weko `test/sword-error-codes`）の結合テスト（仕様書 v4.2）を、
agentic-test-hub で仕様 → 生成テスト → 実行できる状態にした。**到達点: Tier 1（非破壊の 68 テスト）を
生成し、WEKO ではない機構検証用スタブ（rig）で配管が動くところまで。実 WEKO では一度も実行していない。**
次の作業はローカルマシン（docker あり）で新しい Claude Code セッションが行う: 環境起動 → helpers 初回検証 →
改修前ベースライン採取 → Tier 1 実行 → トリアージ → Tier 2/破壊的グループ。

オーナー決定（拘束力あり）:
(a) 実行はローカルの新セッション。WEKO は `install.sh` 直後のデモデータ（ユーザー demo 系、パスワード `uspass123`、
アイテムタイプ 30001/30002、ワークフロー 1/2、SwordClient・トークン・削除フローなし）から始め、シナリオ間で初期化しない。
(b) UI ケース（管理画面設定、トークン失効）は実 Playwright で https（nginx、`weko3.example.org`、自己署名証明書）。
(c) 削除フローは Start+End のみ（EP5 は 204）。(d) S14 の障害注入（DB/Redis/ES の docker stop/start）は自動化し、
cleanup で必ず起動し直す。最後の破壊的グループで実行。(e) モック M1〜M15 はまず DB・データ・環境の書き換え
（helpers の inject_fault）。ソース改変は最後の手段で、オーナーの承認が要る。(f) 設定切替が要るケース（重複検知、XML、
OBO 許可、上限サイズ L と再起動）は未自動化（Tier 2）。(g) A-5（4xx の前の ERROR 行）は不合格にせず「保留」で記録。

## 2. ブランチとコミットの対応（すべて origin に存在）

| リポジトリ | ブランチ | SHA | 内容 |
|---|---|---|---|
| weko-test-suite | `claude/ai-test-spec-management-0j1mom`（基準） | `9f917eb` | コード、plugin.yaml、helpers、seeds、tools、スタブ、生成テスト 68 件、スキル 4 つ、docs。仕様 YAML は**置かない** |
| weko-test-suite | `spec-draft/sword-error-codes` | `d3a5272` | レビュー対象の仕様 YAML（観点 66、因子 6、マトリクス 4、基準 5、ケース 59、シナリオ 15）と docs/spec-trace.md。今後は YAML のみのコミット |
| weko-test-suite | `tmp/handoff-sword-error-codes` | この文書のコミット | HANDOFF.md のみ |
| agentic-test-hub | `claude/ai-test-spec-management-0j1mom` | `78dd13a`（`hub.lock` で固定） | 生成器・ランナー。**このリポジトリでは変更しない** |
| weko | `test/sword-error-codes` | `daf15d6f`（改修後）／`779c2d70`（改修前ビルド） | 対象。変更しない |

仕様の変更は `spec-draft/sword-error-codes` に YAML だけをコミットし、テストは
`SPECS_DIR=<spec-draft の worktree>/specs scripts/gen-test.sh <ID> --force` で機能ブランチへ再生成する。
push 前は必ず `git fetch origin && git rebase origin/<branch>`。

## 3. 検証済み／未検証

### 検証済み（この環境で実行して確認）

| 内容 | 方法 | 結果 |
|---|---|---|
| 独自コード 51 件の静的適合（`errors.py`・コード表・英語カタログ） | `tools/check_error_codes.py`、weko `test/sword-error-codes` `daf15d6f` | 差異 0（前セッションで実施。このセッションでは再実行していない） |
| 静的検査一式 | `scripts/check.sh`（ruff、pytest、生成テスト収集、fixtures、plugin/仕様の hub 検証、rig e2e） | 全通過（`9f917eb`） |
| rig（スタブ。**WEKO ではない**）での配管 | `scripts/rig-run.sh --all`、および `--faithful-log` | どちらも 68 件中 67 件合格。落ちる 1 件は S8-02（スタブが 202 を返すため。仕様どおり） |
| A-5 の保留扱い | `--faithful-log`（スタブが全 4xx の前に ERROR 行を出す）でも合格し、`tools/a5_scan.py` が 52 エンティティを保留として列挙 | 確認済み |
| CI | GitHub Actions `CI`。spec-draft `d3a5272` は success。機能ブランチ `9f917eb` はこの文書の作成時点で queued（要確認: 下の 7 節） | |

### 未検証（実 WEKO で一度も動かしていない）

- helpers の ORM 部分すべて（`create_user`、`create_token`、`register_sword_client`、`create_record`、`delete_record`、
  `create_flow`、`create_workflow`、`snapshot`、`baseline` ほか）。コンテナ内 Python が 3.6 の仮想環境か。`ping` の app context。
- `WEKO_TEST_TOKEN_` 接頭辞付きトークンが JWT 検証下で通るか（通らなければ `token_prefix: ""`）。
- RLS 障害レシピは DB ロールが superuser／BYPASSRLS だと効かない（`RlsBypassed`）。ロールの実際の属性。pgpool 経由の DDL、SQLSTATE 08006 の扱い。
- `create_record` の副作用（Elasticsearch 反映、`RecordIdentifier` カウンタ）。recid は 900000 以上を使う。
- 削除フロー（Start+End のみ）で EP5 が 204 を返すか。`delete_record` 後に EP3 が 404 になるか（ならなければ `pid_only`）。
- デモユーザーでのログイン（`confirmed_at` が空だと失敗する可能性）。`SESSION_COOKIE_SECURE=True` での https の Cookie。
- Redis のロックキー名 `pid_<recid>_will_be_edit` と DB 番号（F-7）。
- ログ書式（行頭にレベルが出るか）と、`evidence.ignore` の文言パターンが実際のログに合うか。
- 同一 recid への EP4/EP5 連続呼び出し（S3-03 の DELETE 2 回、S5-08 の PUT 3 回、S6-01）で 3 秒ロック（2201）が混入しないか。
- Chromium が自己署名証明書を受け入れるか。hub の `PlaywrightDriver` は `ignore_https_errors` を設定しない。
  NSS db に証明書を入れるか、hub 側の変更（オーナー承認）が要る。
- 実メタデータ（S3-04、S8-02、S12-01）。fixtures の CSV は項目を登録できる形ではない。

## 4. 実行手順（順序つき）

詳細はスキル（`.claude/skills/`、英語）。機能ブランチを clone して使う。

1. `git clone https://github.com/ivis-kuroda/weko-test-suite && cd weko-test-suite && git switch claude/ai-test-spec-management-0j1mom`、
   AGENTS.md・README.md・docs/ を読む。隣に hub と weko を置く: `scripts/bootstrap-hub.sh && uv sync`。
2. スキル `weko-env-up`: `install.sh`（改修後ビルド）→ hosts・証明書 → `.env` → helpers を web コンテナへ `docker cp` →
   `seeds/bootstrap.py baseline-check` → `run`（`.env.local` が出る）→ ヘルスチェック → helpers 初回チェックリスト 12 項目。
   **期待値と違えば止めて報告。**
3. スキル `sword-test-run` 手順 2: 改修前ビルド `779c2d70` でベースライン採取（S0-06。U-21、U-01、応答時間）。その後、改修後ビルドへ戻す。
4. `scripts/run-ordered.sh --out artifacts/run-1`（S1 → S16 順、ファイル間 3 秒）。`tools/a5_scan.py` で保留を一覧。
5. hub のスキル `triage-run-result` で非合格を分類し、結果行（合格／不合格／保留／実施不可。0.5）を作る。
6. Tier 2（設定切替、UI）を手順どおりに。続いてモック脚本（`weko-fault-injection`、M12 → M15 → … の順にスパイク）、最後に S14（破壊的、cleanup で必ず復旧、S0-08）。
7. 環境変数（値は書かない）: `WEKO_BASE_URL`、`WEKO_*_CONTAINER`、`SW_USER_*`、`SW_TOKEN_*`、`SW_CLIENT_ID_*`、`SW_R1..R9`、
   `SW_REDIS_DB`、`ATH_EVIDENCE_DIR`、`SSL_CERT_FILE`、`NO_PROXY`。値は人が `.env` に入れる。`.env.local` は bootstrap が書く（コミットしない）。

再開コマンド: `scripts/bootstrap-hub.sh`（hub を `hub.lock` の SHA に合わせる）、`scripts/check.sh`（CI と同じ）、
`scripts/rig-run.sh --all [--faithful-log]`（rig。実 WEKO ではない）。

## 5. 判断が必要な事項（オーナー）

| 事項 | 選択肢と推奨 |
|---|---|
| U-21（無効トークンは 401 か 403）、U-01（ロール別可否） | 改修前ビルドの実測で確定。実測前は S1-03、S2-01、S12 は inconclusive |
| 実メタデータ（S3-04、S8-02、S12-01） | 対象環境から書き出した CSV／JSON-LD を提供してもらう。それまで成功系は通らない可能性 |
| ロケール指定方法（U-11、S11-02） | 方法が決まるまで手動のまま |
| マトリクス `strategy`（現在 `full`） | S2-01 は 25 セルを全実行。削るなら理由を決める |
| 設定切替ケース（Tier 2） | 手順は `sword-test-run` にある。自動化するなら plugin に設定変更の操作を足す（別途承認） |
| Content-Type（S5-05, Q-5） | 既定設定では 1401 に到達できない可能性。到達不能なら実施不可として記録 |
| モック M1〜M15 | DB 書き換えでまずスパイク。**ソース改変の承認が要りそうなもの**: M14（純 Python 関数、データで届かない）、M2、M13 の Redis/ES、M1/M8/M10（DB ロールが RLS を回避する場合）、場合により M6 |
| 観点 VP-SW-BD-60 / VP-SW-EG-19 の本文 | 「ERROR 行があれば不合格」のまま。A-5 の保留決定と食い違う。改訂するか |
| Chromium と自己署名証明書 | NSS db へ証明書、または hub に `ignore_https_errors` を足す（hub は触らない前提なので承認が要る） |

## 6. 注意（既知の罠）

- F-6: 実 WEKO は 201 に `Location` を返さない。recid は応答本文の `@id` から取る（`produces` の `{from, pattern}`）。
- A-5 の仕組み: 4xx 用ケースの `evidence.ignore` は `(WARNING|ERROR).*<コード/文言>`。無視された行は証跡の `diff-app-log-*` に残る。
  `uv run python tools/a5_scan.py <ATH_EVIDENCE_DIR> --rows` が結果行の備考文を出す。他の ERROR 行は今までどおり不合格。
- 生成テストは手で編集しない。`gen-test.sh` は `SPECS_DIR` 側の YAML に `automation` を書き戻す（spec-draft 側でコミット）。
- 証跡（`artifacts/`）はマスク済みだがコミットしない。`install.sh` は破壊的（ボリューム削除）。デモのワークフロー 1/2 は書き換えない。
- DB 停止中は有効トークンでも 503（トークン検索が先に失敗）。S14 の後は S0-08 の復旧確認を必ず行う。
- 手作業の混入に注意: weko は読み取りのみ。hub は変更しない。

## 7. 状態の確認

最新コミットの CI 結果は `gh`/GitHub Actions（ivis-kuroda/weko-test-suite）で確認すること。この文書に書いた SHA はすべて origin に存在する。

## 8. 新セッションへの開始プロンプト（そのまま貼り付け）

```
ivis-kuroda/weko-test-suite を clone し、ブランチ tmp/handoff-sword-error-codes の HANDOFF.md と、
機能ブランチ claude/ai-test-spec-management-0j1mom の AGENTS.md・README.md・.claude/skills/ を読んでください。
隣に agentic-test-hub（hub.lock の SHA）と weko（改修後 test/sword-error-codes と、改修前ビルド 779c2d70）を置き、
docker でローカルの WEKO を install.sh のデモデータから起動します。スキル weko-env-up に従って環境を整え、
helpers の初回チェックリストを順に確認し、期待と違う結果は直さず報告してください。その後 sword-test-run に従い、
改修前ベースライン採取 → Tier 1 実行 → トリアージの順に進めます。オーナー判断事項（HANDOFF 5 節）は、決める前に必ず報告して確認を取ってください。
weko と hub は変更しません。仕様 YAML の変更は spec-draft/sword-error-codes に YAML のみでコミットし、push 前に fetch と rebase をしてください。
```
