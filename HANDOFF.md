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
(e) モック M1〜M15 は DB・データ・設定・環境の書き換え（helpers の `inject_fault`）だけで再現する。**ソースは改変しない**（2026-10-09 確定。5.1）。再現できないものは `not_runnable`。
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
5. DB／データ／設定／環境で再現できないケースは hub の `automation.status: not_runnable`（理由・確認日・確認者つき）。**ソース改変はしない**（5.1）。未決事項は 5.3 の決定ログ。

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
| 実施不可の根拠 | weko `daf15d6f` の `utils.py`、`views.py`、`decorators.py` の読み取り | `TC-SW-S15-07`、`TC-SW-S15-15` のみ。1403／1408／1401 は到達できるので付けていない（5.3 D-07） |

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

## 5. 方針と決定ログ（Decision log）

### 5.1 確定方針: 対象のソースは改変しない

オーナー決定（2026-10-09）: **weko のソースは一切改変しない**（Playwright／pytest の実行は何度やっても同じ結果になる再現性・冪等性が要る。
発注元もソース変更は最終手段としている）。DB・データ・設定・環境の操作で再現できないものは、承認待ちにせず
`automation.status: not_runnable`（`reason`、`checkedAt`、`checkedBy`）にする。「モックのためのソース改変を承認する」という項目は存在しない。

- 既に `not_runnable`（コードの読み取りで証明済み）: `TC-SW-S15-07`（3107）、`TC-SW-S15-15`（1411、M14）。**これ以外は、ローカルで証明（スパイク失敗）するまで付けない。**
- モックはローカルのスパイクでモックごとに成否を決める。失敗したら `not_runnable`。手順（スキル `weko-fault-injection` の "When a spike fails" と同じ）:
  1. ケース YAML の変更は **`spec-draft/sword-error-codes` のみ**（YAML だけのコミット）。`automation: {status: not_runnable, reason, checkedAt, checkedBy}`。
  2. 機能ブランチで `SPECS_DIR=<spec-draft の worktree>/specs scripts/check.sh`、refuse された生成テストを `tests/generated/` から削除（`git rm`）、`docs/TIER1-STATUS.md` の実施不可表を更新。
  3. `hub.lock` と互換のまま（hub は変更しない）。両ブランチとも `git fetch origin && git rebase origin/<branch>` の後に `git push -u origin <branch>`、CI 緑を確認（7 節）。

### 5.2 決定の記録のしかた

未決事項はローカルセッションが開始後、オーナーに **AskUserQuestion** で 1 項目ずつ確認する（選択肢と既定を示す）。決まったら次の順で行う。

1. この節の該当項目の末尾に `**決定 YYYY-MM-DD**: <結果と理由>` を追記する（このブランチ `tmp/handoff-sword-error-codes` へコミット。`git fetch origin && git rebase origin/tmp/handoff-sword-error-codes` の後に push）。
2. 項目の「決まった後の作業」を実行する（変更先のブランチはその項目に書いてある）。
3. 項目の見出しに `[決定済]` を付ける。作業が機能ブランチに入ったら、このブランチごと削除してよい。

### 5.3 決定ログ（未決 D-01〜D-12）

各項目の「既定」は、オーナーが決めるまでローカルセッションが取る暫定の振る舞い。略称: FB = 機能ブランチ `claude/ai-test-spec-management-0j1mom`、SD = `spec-draft/sword-error-codes`。
SPECS は `SPECS_DIR=<SD の worktree>/specs`。

#### D-01 U-21／U-01 ベースライン（無効トークンは 401 か 403、ロール別可否）

- 論点: 仕様書の U-21（無効トークンの応答）と U-01（ロールごとの可否）は改修前ビルド `779c2d70` の実測で確定する。
- 選択肢: (a) 実測した値を期待に採用 (b) 改修後の仕様書どおり（401）を期待にし、差を対象の挙動変更として記録 (c) 両方許容。
- 既定: 実測前は S1-03、S2-01、S12 を inconclusive 扱いにする。実測値は報告し、期待は変えない。
- 影響: ケース `TC-SW-S1-03`、`TC-SW-S2-01`（マトリクス）、S12 系の YAML、`docs/BASELINE.md`、仕様書 S0-06。
- 決まった後の作業: SD で該当ケース／マトリクス YAML の期待ステータスを変更（YAML のみ）→
  `SPECS=... scripts/gen-test.sh <ID> --force`（FB へ再生成）→ `scripts/check.sh` → 実 WEKO で再実行。採取値は `docs/BASELINE.md` に追記（FB）。

#### D-02 実メタデータ（S3-04、S8-02、S12-01）

- 論点: fixtures の CSV は項目を登録できる形ではなく、成功系（S3-04 取得、S8-02 更新、S12-01）が実 WEKO で通らない可能性がある。
- 選択肢: (a) オーナーが対象環境から書き出した CSV／JSON-LD（実エクスポート）を提供 (b) アイテムタイプ 30001/30002 から手で作る (c) 当該ケースを保留。
- 既定: (a) を依頼。届くまで該当 3 ケースは保留で、他は進める。
- 影響: `fixtures/`（FB。S3-04、S8-02、S12-01 が参照するファイル）、`plugin.yaml` の `create_record` 周辺、該当ケース YAML（SD）の `produces`／入力。
- 決まった後の作業: FB の `fixtures/` に実エクスポートを置く（個人情報はマスク）→ 必要なら `tools/` のフィクスチャ生成を更新 → `scripts/check.sh` → ローカルで S3-04、S8-02、S12-01 を実行。ケース YAML の入力を変えるなら SD で YAML のみコミットし `gen-test.sh <ID> --force`。

#### D-03 U-11 ロケール指定方法（S11-02）

- 論点: 言語をどう指定するか（Accept-Language ヘッダ／クエリ／ユーザー設定）が仕様書で未確定。
- 選択肢: (a) Accept-Language (b) ユーザーのロケール設定の DB 書換（`set_client_field` 系の操作を追加）(c) 手動のまま。
- 既定: (c)（`blocked:locale-method-U-11`）。
- 影響: `TC-SW-S11-02` ほか S11 系の YAML（SD）、`plugin.yaml`（操作追加なら）。
- 決まった後の作業: (a) は SD で YAML のヘッダ入力を足し再生成。(b) は FB の `plugin.yaml` と helpers に操作を足し（`docs/helpers.md` 更新）、SD の YAML を更新して `gen-test.sh S11-02 --force`。

#### D-04 マトリクス strategy（現在 `full`）

- 論点: S2-01 の 25 セルなどを全実行するか、削るか。
- 選択肢: (a) `full` のまま (b) `pairwise` 等へ変更（理由を決める）。
- 既定: (a)。
- 影響: SD の `matrices/*.yaml`（S2-01、S1-03、S5-02、S5-05）と、FB の生成テスト。
- 決まった後の作業: (b) のとき SD で matrix YAML の `strategy` を変更（YAML のみ）→ `SPECS=... scripts/gen-test.sh <ID> --force` → `scripts/check.sh`。

#### D-05 トグル系ケースの Tier 2（重複検知 1503、XML、OBO、上限サイズ L の 413）

- 論点: 設定切替（と再起動）を伴うケースを自動化するか。
- 選択肢: (a) 手動のまま（`sword-test-run` の手順）(b) plugin に設定変更の操作を追加して自動化 (c) 一部だけ自動化。
- 既定: (a)。
- 影響: `plugin.yaml`、helpers（設定変更・復元）、`docs/helpers.md`（FB）、該当ケース YAML（SD）の `automation`。
- 決まった後の作業: (b)/(c) は FB で操作と復元を実装し `scripts/check.sh`、SD で YAML を更新、`gen-test.sh <ID> --force`。破壊的になるものは最後の直列グループへ。

#### D-06 新ログ判定ルールの xlsx／仕様書 v4.2 への反映

- 論点: 「ERROR 行がない」を判定に使わず、期待ハンドラ行の存在を肯定的に検証する規則（`docs/LOG-JUDGEMENT.md`）を、観点表 xlsx と仕様書 v4.2 の文面へ戻す。
- 選択肢: (a) オーナーが xlsx／仕様書を修正（本リポジトリは受領資料を編集しない）(b) 当面は `tools/viewpoint_overrides.json` の上書きで運用。
- 既定: (b)。
- 影響: 反映対象の一覧は `docs/VIEWPOINT-OVERRIDES.md`（観点 VP-SW-BD-60、VP-SW-EG-19）、仕様書 S13-01、S15-16、4.5 A-5、U-20、F-09。
- 決まった後の作業: (a) 後に xlsx を再インポートして上書きが不要になれば `tools/viewpoint_overrides.json` の該当項を削除（FB）し、観点 YAML を再生成してバイト一致を確認（SD へ YAML のみ）。

##### D-06a 429 のログ書式（S10）と実ハンドラ行書式【最初に確認】

- 論点: 429 のログ書式は仕様未確定。さらに、実ハンドラ行が `<レベル> ... [コード] METHOD path: message`（1 行、コードは数字または `WEKO_SWORDSERVER_E_` つき）で出るかは**実 WEKO で一度も確認していない**。
- 既定: **ローカルで最初に確認する**。`tools/log_expect.py` の正規表現を実ログに当てる。429 は期待を置かず、ログを証跡にだけ残す。
- 影響: ハンドラ行を断言する 36 エンティティ、S10 系 YAML（SD）。
- 決まった後の作業: 書式が違えば FB の `tools/log_expect.py` を 1 か所直し、`SPECS=... scripts/gen-test.sh <ID> --force` で再生成（ハンドラ行を断言する全件）、`scripts/check.sh`、`scripts/rig-run.sh --all --faithful-log`。429 は書式が決まったら SD の S10 YAML に `OP-APP-LOG` の期待を追加。

#### D-07 1401 の Content-Type 操作追加と 1403／1408 の設定

- 論点: (1401) ファイルパートの Content-Type を指定する操作が plugin に無い（`blocked:content-type-not-expressible`）。(1403/1408) 既定設定では 1402 が先に出る。`WEKO_SWORDSERVER_SERVICEDOCUMENT_ACCEPT_PACKAGING` を `["*"]` にすれば到達できる（コード読取り済み）。いずれも `not_runnable` ではない。
- 選択肢: 1401: (a) plugin に multipart パートの Content-Type 指定を追加して自動化 (b) 手動。1403/1408: (a) 設定切替＋再起動の操作を足して Tier 2 を自動化 (b) 手動。
- 既定: 手動（どちらも）。
- 影響: `plugin.yaml`（FB）、S5-05／Q-5、1403／1408 のケース YAML（SD）、`docs/TIER1-STATUS.md`。
- 決まった後の作業: FB で操作を追加（`docs/helpers.md`、`scripts/check.sh`）→ SD の YAML を更新 → `gen-test.sh <ID> --force`。1403/1408 は設定変更後に必ず元へ戻す（cleanup）。**`not_runnable` にはしない。**

#### D-08 モック M1〜M15 のスパイク（項目ごとの状態と、失敗時のフォールバック）

- 論点: 各モックを DB／データ／環境の書換（`inject_fault`）で再現できるか。ソースは改変しないので、**失敗 = `not_runnable`**（5.1 の手順）。
- 既定: スキル `weko-fault-injection` の順（M12 → M15 → M3/M4 → M5 → M7 → M9 → M11/M6 → M13(DB) → M2 → M1/M8/M10 → M14）で、モックごとに記録（レシピ、パラメータ、観測コード、観測ログ行、再現／非再現／別コード）。

| モック | 状態 | 失敗時のフォールバック |
|---|---|---|
| M1 | 未実施。RLS は DB ロールが superuser／BYPASSRLS だと効かない（`ping` の `db_user` で確認） | 代替の trigger が無ければ `not_runnable` |
| M2 | 未実施。`corrupt_mapping_json` で KeyError／TypeError を起こす案。`Unexpected error: <type>` の文言が合うか | `not_runnable` |
| M3、M4 | 未実施（`trigger_raise` 23505／23503、`check_violation_new_rows`） | 行条件の工夫でも不可なら `not_runnable` |
| M5 | 未実施（`pids` の update トリガ） | `not_runnable` |
| M6 | 未実施。削除フローが `WekoWorkflowException` を送出するか未確認 | `not_runnable` |
| M7 | 未実施（`corrupt_mapping_json`） | `not_runnable` |
| M8、M10 | 未実施。M1 と同じ RLS の前提（OBO の対象ユーザー行のみ） | `not_runnable` |
| M9 | 未実施（`corrupt_record_json`） | `not_runnable` |
| M11 | 未実施（`break_workflow_flow`、アクティビティ／下書きを残さない） | `not_runnable` |
| M12 | 未実施（`set_client_field`、確度高） | `not_runnable` |
| M13 | DB 部分は未実施（SQLSTATE 08006 の pgpool／SQLAlchemy での扱いが未検証）。Redis／ES の ConnectionError は DB 経路で作れない | DB 部分は `not_runnable`、Redis／ES 部分は `not_runnable` |
| M14 | **`not_runnable`（`TC-SW-S15-15`、コードで証明済み）** | - |
| M15 | 未実施（`orphan_record`。2101 の先行チェックが別の Resolver で 2101 になる恐れ。Q-10） | `not_runnable` |

- 影響: S15 のケース YAML（SD）、`docs/TIER1-STATUS.md` の実施不可表（FB）、生成テスト（FB）。
- 決まった後の作業: 失敗したモックは 5.1 の手順（SD に YAML のみ → FB でテスト削除・TIER1-STATUS 更新 → 両 push・CI）。成立したモックは `automation` を `manual` のまま、`gen-test.sh <ID> --force`（SD の YAML に書き戻される）で生成し、`weko-fault-injection` の検証手順（restore と `list_faults == []`）を守る。

#### D-09 hub への要望（任意）

- 論点: 期待がすべて満たされ決めるチャンネルがポリシーに無いときに pass とする方式。今は `app_log: clean` と `ignore: .*` の存在ゲートで代用している。
- 選択肢: (a) hub に要望を出す（対象名を含まない汎用の形で）(b) 代用を続ける。
- 既定: (b)。hub は変更しない。
- 影響: hub（このリポジトリでは触らない）。要望が通った場合のみ、FB の生成方針と各ケース YAML の `ignore: .*` を外す。
- 決まった後の作業: (a) は要望文面をオーナーに提示。hub 側で実装され `hub.lock` が進んだら、`scripts/bootstrap-hub.sh` → `scripts/check.sh` →（YAML から `ignore: .*` を除く場合は SD で YAML のみ）→ 再生成。

#### D-10 U-08 OBO 設定キー

- 論点: On-Behalf-Of を有効にする設定キーが未確定。
- 選択肢: (a) オーナーが設定キーを提供 (b) weko の設定定義を読み取りで探す（変更はしない）。
- 既定: (b) で候補を探し報告。決まるまで OBO ケース（M8/M10 を含む）は Tier 2 で手動。
- 影響: OBO 系ケース YAML（SD）、D-05 のトグル操作、`sword-test-run` の Tier 2 手順（FB）。
- 決まった後の作業: キーを `sword-test-run` と `docs/helpers.md` に追記（FB）、D-05 で自動化するなら操作を足す。

#### D-11 U-03 レート制限のしきい値（S10）

- 論点: 429 を出すまでのリクエスト数・窓が未確定。
- 選択肢: (a) オーナーがしきい値を提供 (b) weko の設定を読み取りで探す (c) S10 は保留。
- 既定: (c)。
- 影響: S10 系ケース YAML（SD）、D-06a（429 ログ書式）。
- 決まった後の作業: SD の S10 YAML にしきい値を反映（YAML のみ）→ `gen-test.sh <ID> --force`。3 秒間隔ルール（`scripts/run-ordered.sh`）との関係を確認。

#### D-12 Q-2（トークン⑤の発行可否）

- 論点: トークン⑤を発行できるかが仕様書で未確定。
- 選択肢: (a) 発行できる → `create_token` で作る (b) 発行できない → 該当ケースを保留（コードで不可と証明できる場合のみ `not_runnable`）。
- 既定: (a) を実 WEKO で試し、結果を報告。
- 影響: トークン⑤を使うケース YAML（SD）、`plugin.yaml` の `create_token`（FB）、`SW_TOKEN_*`。
- 決まった後の作業: (b) で証明できれば 5.1 の手順。(a) なら `docs/BASELINE.md` と `.env` の項目を更新（FB）。

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
未決事項は HANDOFF 5.3 の決定ログ（D-01〜D-12）にあります。該当する作業の前に、AskUserQuestion でオーナーに 1 項目ずつ確認し（選択肢と既定を示す）、
決まったら 5.2 に従って決定ログへ日付つきで追記してから、その項目の「決まった後の作業」を実行してください。
weko のソースは一切改変しません（モックが DB／データ／設定／環境で再現できなければ not_runnable。5.1）。hub も変更しません。仕様 YAML の変更は spec-draft/sword-error-codes に YAML のみでコミットし、push 前に fetch と rebase をしてください。
```
