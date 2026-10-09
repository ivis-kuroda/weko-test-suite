# HANDOFF: SWORD エラーコード結合テストを実 WEKO（ローカル）で実行する

一時ブランチ `tmp/handoff-sword-error-codes`。HANDOFF.md を足したコミットだけが目的で、コードの正は機能ブランチ
`claude/ai-test-spec-management-0j1mom`（この文書が参照するファイルはすべてそこにある）。作業が機能ブランチへ入ったらこのブランチは削除する。

## 1. 目的と到達点

WEKO3 の SWORD v3 エラーコード改修（weko `test/sword-error-codes`）の結合テスト（仕様書 v4.2）を、
agentic-test-hub で 仕様 → 生成テスト → 実行 できる状態にした。**到達点: Tier 1（非破壊の 68 テスト）を生成し、
WEKO ではない機構検証用スタブ（rig）で配管が動くところまで。実 WEKO では一度も実行していない。**
次の作業はローカルマシン（docker あり）で新しい Claude Code セッションが行う: 環境起動 → helpers 初回検証 →
改修前ベースライン採取 → Tier 1 実行 → トリアージ → Tier 2／モックのスパイク／破壊的グループ。

### オーナー決定（拘束力あり）

(a) 実行はローカルの新セッション。WEKO は `install.sh` 直後のデモデータ（パスワード `uspass123`、アイテムタイプ 30001/30002、
ワークフロー 1/2、SwordClient・トークン・削除フローなし）から始め、シナリオ間で初期化しない。
(b) UI ケースは実 Playwright で https（nginx、`weko3.example.org`、自己署名証明書）。
(c) 削除フローは Start+End のみ（EP5 は 204）。(d) S14 の障害注入は自動化し、cleanup で必ず起動し直す。最後の破壊的グループ。
(e) モック M1〜M15 はまず DB・データ・環境の書き換え（helpers の `inject_fault`）。ソース改変は最後の手段で承認が要る。
(f) 設定切替が要るケース（重複検知、XML、OBO、上限サイズ L と再起動）は Tier 2（未自動化）。

**2026-10-09 の追加決定（今回反映済み）**

1. **ログ判定は肯定的・箇所限定**。「ERROR 行がない」は判定に使わない（WEKO 内部は重要でない状況でも範囲外でも ERROR とトレースを出すため）。
   ケースごとに、期待するハンドラ行 `[コード] METHOD path: message` が web ログに**存在**し、基本設計 5.4 のレベル
   （4xx は WARNING、500/501/503 は ERROR）で出ていることを断言する。範囲外の ERROR・トレースは証跡に残し、結果欄の備考にするだけ
   （`docs/LOG-JUDGEMENT.md`、`tools/log_expect.py`、`tools/check_log_rule.py`、`tools/log_remarks.py`）。
2. 観点 VP-SW-BD-60 / VP-SW-EG-19 の文面は、インポータの上書き（`tools/viewpoint_overrides.json`、`docs/VIEWPOINT-OVERRIDES.md`）で直した。
   生成 YAML は手で編集しない。
3. 自己署名証明書: 環境変数 **`ATH_BROWSER_IGNORE_HTTPS_ERRORS=1`**（hub の Python Playwright ドライバが読む。生成テストの編集も NSS db も不要）。
4. 同一 recid への連続呼び出しは、テストが必要とするなら許容。守るのはファイル間の 3 秒間隔だけ（`scripts/run-ordered.sh`）。
5. ソース改変なしでは実施できないケースは hub の `automation.status: not_runnable`（理由・確認日・確認方法つき）。オーナーの確認待ち（下の 5 節）。

## 2. ブランチとコミットの対応（すべて origin に存在）

| リポジトリ | ブランチ | SHA | 内容 |
|---|---|---|---|
| weko-test-suite | `claude/ai-test-spec-management-0j1mom`（基準） | `54c8671` | コード、plugin.yaml、helpers、seeds、tools、スタブ、生成テスト 68 件、スキル 4 つ、docs。仕様 YAML は**置かない** |
| weko-test-suite | `spec-draft/sword-error-codes` | `65f8a40` | レビュー対象の仕様 YAML（観点 66、因子 6、マトリクス 4、基準 5、ケース 61、シナリオ 15）と docs/spec-trace.md。今後は YAML のみのコミット |
| weko-test-suite | `tmp/handoff-sword-error-codes` | この文書のコミット | HANDOFF.md |
| agentic-test-hub | `claude/ai-test-spec-management-0j1mom` | `d785da1`（`hub.lock` で固定） | 生成器・ランナー。`ignore_https_errors`、`not_runnable`、ブラウザのリクエスト排出（settle）修正を含む。**このリポジトリでは変更しない** |
| weko | `test/sword-error-codes` | `daf15d6f`（改修後）／`779c2d70`（改修前ビルド） | 対象。変更しない |

仕様の変更は `spec-draft/sword-error-codes` に YAML だけをコミットし、テストは
`SPECS_DIR=<spec-draft の worktree>/specs scripts/gen-test.sh <ID> --force` で機能ブランチへ再生成する
（`scripts/check.sh` も `SPECS_DIR` を読む）。push 前は必ず `git fetch origin && git rebase origin/<branch>`。

## 3. 検証済み／未検証

### 検証済み（この環境で実行して確認）

| 内容 | 方法 | 結果 |
|---|---|---|
| 独自コード 51 件の静的適合 | `tools/check_error_codes.py`、weko `daf15d6f` | 差異 0（前セッション。今回は再実行していない） |
| 静的検査一式 | `SPECS_DIR=<spec-draft>/specs STRICT_HUB=1 scripts/check.sh`（ruff、pytest、生成テスト収集、fixtures、plugin／仕様の hub 検証、ログ規則、rig e2e、ノイズ耐性と欠落検出） | 全通過 |
| rig（**WEKO ではない**）での配管 | `scripts/rig-run.sh --all` と `--all --faithful-log`（範囲外 ERROR・トレースを毎回出す） | どちらも 68 件中 67 件合格。落ちる 1 件は S8-02（スタブが 202 を返す。仕様どおり） |
| ハンドラ行の肯定判定 | `scripts/rig-run.sh --all --no-handler-log`（スタブがハンドラ行を出さない） | 29 件不合格（ハンドラ行を断言する全件） |
| インポータの上書き | 観点 xlsx（v4.2 の `テスト観点` シートのもの）から再生成 | 観点 YAML 66 件が spec-draft とバイト一致。上書き 2 件適用 |
| CI | GitHub Actions `CI`（weko-test-suite の両ブランチ、hub `d785da1`） | success（最終 SHA は 7 節のコマンドで再確認） |
| 実施不可の根拠 | weko `daf15d6f` の `utils.py`、`views.py`、`decorators.py` の読み取り | `TC-SW-S15-07`、`TC-SW-S15-15` のみ。1403／1408／1401 は到達できるので付けていない（5 節） |

### 未検証（実 WEKO で一度も動かしていない）

- **実 WEKO のログ書式**: ハンドラ行が `<レベル> ... [コード] METHOD path: message`（レベルがコードより前、1 行、コードは数字のみ
  または `WEKO_SWORDSERVER_E_` つき）で出るか。合わなければハンドラ行を断言する 36 エンティティが不合格になる。直すのは
  `tools/log_expect.py` の 1 か所と再生成。503 型伝播（3108〜3110、EP3/EP5・認証段階）のスタックトレースが付くか。
- helpers の ORM 部分すべて（`create_user`、`create_token`、`register_sword_client`、`create_record`、`delete_record`、
  `create_flow`、`create_workflow`、`snapshot`、`baseline` ほか）。コンテナ内 Python が 3.6 か。`ping` の app context。
- `WEKO_TEST_TOKEN_` 接頭辞付きトークンが JWT 検証下で通るか（通らなければ `token_prefix: ""`）。
- RLS 障害レシピは DB ロールが superuser／BYPASSRLS だと効かない（`RlsBypassed`）。pgpool 経由の DDL、SQLSTATE 08006 の扱い。
- `create_record` の副作用（ES 反映、`RecordIdentifier` カウンタ）。recid は 900000 以上を使う。
- 削除フロー（Start+End のみ）で EP5 が 204 を返すか。`delete_record` 後に EP3 が 404 になるか（ならなければ `pid_only`）。
- デモユーザーでのログイン（`confirmed_at` が空だと失敗する可能性）。`SESSION_COOKIE_SECURE=True` での https の Cookie。
- Redis のロックキー名 `pid_<recid>_will_be_edit` と DB 番号（F-7）。
- 同一 recid への連続呼び出し（S3-03 の DELETE 2 回、S5-08 の PUT 3 回、S6-01）で 2201 が混ざるか（混ざっても許容。備考に記録）。
- `ATH_BROWSER_IGNORE_HTTPS_ERRORS=1` で Chromium が実際に nginx の自己署名証明書を受け入れるか（hub の単体テストでは確認済み）。
- 実メタデータ（S3-04、S8-02、S12-01）。fixtures の CSV は項目を登録できる形ではない。

## 4. 実行手順（順序つき）

詳細はスキル（`.claude/skills/`、英語）。機能ブランチを clone して使う。

1. `git clone https://github.com/ivis-kuroda/weko-test-suite && cd weko-test-suite && git switch claude/ai-test-spec-management-0j1mom`。
   AGENTS.md・README.md・docs/（`TIER1-STATUS.md`、`LOG-JUDGEMENT.md`、`BASELINE.md`、`helpers.md`）を読む。
   隣に hub と weko を置く: `scripts/bootstrap-hub.sh && uv sync`。仕様 YAML は
   `git worktree add ../weko-test-suite-spec spec-draft/sword-error-codes` で取り、`export SPECS_DIR=$PWD/../weko-test-suite-spec/specs`。
2. スキル `weko-env-up`: `install.sh`（改修後ビルド）→ hosts・証明書 → `.env`（`ATH_BROWSER_IGNORE_HTTPS_ERRORS=1` を含む）→
   helpers を web コンテナへ `docker cp` → `uv run python seeds/bootstrap.py baseline-check` → `run`（`.env.local`）→ ヘルスチェック →
   helpers 初回チェックリスト。**期待と違えば止めて報告。**
3. スキル `sword-test-run` 手順 2: 改修前ビルド `779c2d70` でベースライン採取（S0-06。U-21、U-01、応答時間）。その後、改修後ビルドへ戻す。
4. `scripts/run-ordered.sh --out artifacts/run-1`（S1 → S16 順、ファイル間 3 秒）。終了時に
   `uv run python tools/log_remarks.py artifacts/run-1/evidence --rows` が範囲外 ERROR の備考を出す（判定には使わない）。
5. hub のスキル `triage-run-result`（`agentic-test-hub/.claude/skills/`）で非合格を分類し、結果行（合格／不合格／保留／実施不可。0.5）を作る。
   ハンドラ行の欠落は、対象の不具合か「ログ書式の前提の誤り（仕様の不備）」かを切り分ける。
6. Tier 2（設定切替、UI）、モックのスパイク（`weko-fault-injection`。M12 → M15 → … の順）、最後に S14（破壊的、cleanup で必ず復旧、S0-08）。
7. 環境変数（値は書かない。人が `.env` に入れる。`.env.local` は bootstrap が書く）: `WEKO_BASE_URL`、`WEKO_*_CONTAINER`、`SW_USER_*`、
   `SW_TOKEN_*`、`SW_CLIENT_ID_*`、`SW_R1..R9`、`SW_REDIS_DB`、`ATH_EVIDENCE_DIR`、`ATH_BROWSER_IGNORE_HTTPS_ERRORS`、`NO_PROXY`。

再開コマンド: `scripts/bootstrap-hub.sh`（hub を `hub.lock` の SHA に合わせる）、`scripts/check.sh`（CI と同じ）、
`scripts/rig-run.sh --all [--faithful-log|--no-handler-log]`（rig。実 WEKO ではない）。

## 5. 判断が必要な事項（オーナー）

| 事項 | 選択肢と推奨 |
|---|---|
| U-21（無効トークンは 401 か 403）、U-01（ロール別可否） | 改修前ビルドの実測（S0-06）で確定。実測前は S1-03、S2-01、S12 は inconclusive 扱い |
| 実メタデータ（S3-04、S8-02、S12-01） | 対象環境から書き出した CSV／JSON-LD を提供してもらう。それまで成功系は実 WEKO で通らない可能性 |
| ロケール指定方法（U-11、S11-02） | 決まるまで手動のまま（`blocked:locale-method-U-11`） |
| マトリクス `strategy`（現在 `full`） | S2-01 は 25 セルを全実行。削るなら理由を決める |
| 設定切替ケース（Tier 2: 重複検知 1503、XML、OBO、上限 L の 413） | 手順は `sword-test-run`。自動化するなら plugin に設定変更の操作を足す（別途承認） |
| モック M1〜M15 のスパイク | DB 書き換えでまず試す。**ソース改変の承認が要りそうなもの**: M14（`TC-SW-S15-15`、データで届かない）、M2、M13 の Redis/ES、M1/M8/M10（DB ロールが RLS を回避する場合）、場合により M6 |
| Content-Type の到達性（S5-05、Q-5、1401） | リクエストとファイルパートの両方が許可外のとき 1401。パートの Content-Type を指定できる操作が plugin に無い（`blocked:content-type-not-expressible`）。操作を足せば到達できる見込み。実施不可ではない |
| **新しいログ判定規則** | 肯定的なハンドラ行の断言と、範囲外 ERROR の備考化（`docs/LOG-JUDGEMENT.md`）。仕様書 v4.2（S13-01、S15-16、4.5 A-5、U-20、F-09）と観点表 xlsx に同じ文言を反映する（`docs/VIEWPOINT-OVERRIDES.md` に一覧）。429（S10）のログ書式は未確定 |
| **実施不可（not_runnable）一覧の確認** | `TC-SW-S15-07`（3107。`import_items_to_activity` が URL なしで返るのは error も非空のときだけで、先に別コードが出る。仕様書も実施不可でクローズ）と `TC-SW-S15-15`（1411。`check_import_file_format` が未知を返さない防御分岐。M14 は関数の差し替えでソース変更が要る）。根拠は各 YAML の `automation.reason/checkedAt/checkedBy` と `docs/TIER1-STATUS.md`。承認が出てソース変更で実施するなら `manual` に戻す。**1403／1408 は付けていない**（`ACCEPT_PACKAGING` に `*` を設定すれば到達でき、設定切替の Tier 2）。1401 も同様 |
| hub への要望（任意） | 期待がすべて満たされ決めるチャンネルがポリシーに無いとき pass とする方式（今は `app_log: clean` と `ignore: .*` の存在ゲートで代用） |

## 6. 注意（既知の罠）

- F-6: 実 WEKO は 201 に `Location` を返さない。recid は応答本文の `@id` から取る（`produces` の `{from, pattern}`）。
- 生成テストは手で編集しない。`gen-test.sh` は `SPECS_DIR` 側の YAML に `automation` を書き戻す（spec-draft 側でコミット）。
  `not_runnable` のケースは hub が生成を拒否する（`--force` でも）。
- ログの期待は `run.startedAt`（秒単位）以降の全体が対象。同じ秒の直前のテストの行が欠落を隠すことがあるので、ファイル間を 3 秒空ける。
- 証跡（`artifacts/`）はマスク済みだがコミットしない。`install.sh` は破壊的（ボリューム削除）。デモのワークフロー 1/2 は書き換えない。
- DB 停止中は有効トークンでも 503（トークン検索が先に失敗）。S14 の後は S0-08 の復旧確認を必ず行う。
- weko は読み取りのみ。hub は変更しない（必要なら対象名を含まない汎用の形でオーナーに提案する）。

## 7. 状態の確認

```sh
for b in claude/ai-test-spec-management-0j1mom spec-draft/sword-error-codes tmp/handoff-sword-error-codes; do
  gh api "repos/ivis-kuroda/weko-test-suite/actions/runs?branch=$b&per_page=1" --jq '.workflow_runs[0]|[.head_sha[0:7],.status,.conclusion]|@tsv'
done
git ls-remote https://github.com/ivis-kuroda/weko-test-suite
```

## 8. 新セッションへの開始プロンプト（そのまま貼り付け）

```
ivis-kuroda/weko-test-suite を clone し、ブランチ tmp/handoff-sword-error-codes の HANDOFF.md と、
機能ブランチ claude/ai-test-spec-management-0j1mom の AGENTS.md・README.md・docs/TIER1-STATUS.md・docs/LOG-JUDGEMENT.md・.claude/skills/ を読んでください。
隣に agentic-test-hub（hub.lock の SHA）と weko（改修後 test/sword-error-codes と、改修前ビルド 779c2d70）を置き、
仕様 YAML は spec-draft/sword-error-codes の worktree を SPECS_DIR に指定します。docker でローカルの WEKO を install.sh のデモデータから起動します。
スキル weko-env-up に従って環境を整え（自己署名証明書には ATH_BROWSER_IGNORE_HTTPS_ERRORS=1）、helpers の初回チェックリストを順に確認し、
期待と違う結果は直さず報告してください。その後 sword-test-run に従い、改修前ベースライン採取 → Tier 1 実行 → トリアージの順に進めます。
ログの判定は「期待するハンドラ行が存在すること」の肯定判定で、範囲外の ERROR は備考に記録するだけです（docs/LOG-JUDGEMENT.md）。
最初に実 WEKO のログ書式がハンドラ行の正規表現に合うかを確認してください。
オーナー判断事項（HANDOFF 5 節。not_runnable の確認、モックのソース改変の承認を含む）は、決める前に必ず報告して確認を取ってください。
weko と hub は変更しません。仕様 YAML の変更は spec-draft/sword-error-codes に YAML のみでコミットし、push 前に fetch と rebase をしてください。
```
