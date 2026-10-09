# SWORD 機構検証用スタブ (`tools/sword-stub/`)

> **これは WEKO ではない。WEKO の挙動については何も証明しない。**
> 起動時のバナー、すべての応答の `X-Stub: sword-mechanics-rig` ヘッダ、管理画面の帯にも同じ警告を出す。

## 目的

このリポジトリの開発環境には docker がなく、WEKO を起動できない。それでも、hub が生成した
Python テスト（`ath-generate-test --lang python`）が **機構として動くこと** は確かめたい。

- multipart アップロード、省略したヘッダ、Bearer トークン
- エラー JSON（`@type` / `error`）に対する断言
- 証跡ファイル（マスク済み）、アプリログ、DB スナップショット
- ブラウザ操作（スクリーンショット、コンソール、ネットワーク）
- ヘルパー（`docker exec ... run.py`）と docker 操作

そのための小さな代用サーバーがこれである。**検証できるのは「テストと hub の配管」だけ**で、
WEKO の仕様適合は検証できない（実環境で別に確認する）。

## 構成

| ファイル | 内容 |
|---|---|
| `tools/sword-stub/stub_server.py` | サーバー本体（標準ライブラリのみ、Python 3.11） |
| `tools/sword-stub/errtable.py` | エラーコード表（`errors.py` と英語カタログの転記） |
| `tools/sword-stub/fake_docker.py` | PATH に置く偽の `docker` |
| `tools/sword-stub/stub.example.json` | 世界の定義（トークン、クライアント、recid）の例 |
| `tools/sword-stub/examples/` | e2e 用の極小スイート（rig 専用と明記、仕様・追加操作・補助スクリプト） |
| `tools/tests/test_stub.py`, `test_stub_docker.py` | pytest（実 HTTP、httpx はテストのみ） |
| `scripts/rig-e2e.sh` | 生成から実行・証跡確認までの一括スクリプト |

## 起動

```sh
uv run python tools/sword-stub/stub_server.py \
  --config tools/sword-stub/stub.example.json \
  --log-file /tmp/stub-app.log --port 8080          # --port 0 で空きポート、--port-file で通知
```

`--config` を省くと空の世界で起動する（トークンが無いので SWORD は全部 401 になる）。

## 世界の定義 (`stub.json`)

| キー | 内容 |
|---|---|
| `tokens` | `{"<トークン文字列>": {"name", "client", "role", "scopes": []}}` |
| `revoked` | 失効済みトークン文字列の配列（管理画面の失効ボタンもここへ入れる） |
| `clients` | `{"<client>": {"name", "register_type": "Direct"/"Workflow", "duplicate_check", "workflow": "missing"/"not_registration", "action": "end_action", "deletion": "approval"}}` |
| `records` | `{"<recid>": {"title", "doi", "locked", "editing", "importing"}}` |
| `next_recid` | 新規 recid の起点。削除済みの recid は再利用しない |
| `settings` | `on_behalf_of`、`obo_users`、`max_upload_size`、`accept_archive_format`、`accept_packaging`、`digest_verification`、`import_enabled`、`roles_allowed`、`rate_limit`、`lock_seconds`、`faithful_log`、`location_header` |
| `containers` | `web` / `db` / `redis` / `search` の役割ごとのコンテナ名（既定 `weko-web-1` など） |
| `admin` | 管理画面のログイン（`user`, `password`） |

POST / PUT / DELETE はメモリ上の状態を変える（recid の採番、削除後の 404 `2101`）。
`POST /__stub__/reset` で初期状態へ戻る。

## 判定順（実コードの順）

`weko_swordserver/views.py` と `decorators.py`（WEKO のブランチ `test/sword-error-codes`）、
および v4.2 テスト仕様書 0.6 の 4-2 に合わせた。**デコレータが関数本体より先に動く**点に注意
（PUT の `2101` は、認可・OBO・ファイル検査より後ろ）。

| 順 | POST `/sword/service-document` | 応答 |
|---|---|---|
| 1 | トークン無し・不正・失効 | 401（コードなし、`AuthenticationRequired`） |
| 2 | レート制限（設定時） | 429 `2301` |
| 3 | スコープ `deposit:write`, `deposit:actions`, `item:create` | 403（コードなし、`Forbidden`） |
| 4 | ロール | 403（コードなし） |
| 5 | On-Behalf-Of 不許可 | 412 `1202` |
| 6 | `file` パート・空ファイル名・サイズ・Content-Type・Packaging ヘッダ | `1301` `1302` `1305` `1401` `1402` `1403` |
| 7 | Content-Disposition・パート名一致 | `1303` `1304` |
| 8 | ZIP を開く（壊れていれば汎用例外）／Packaging 構成 | `3201` ／ `1404`〜`1408` |
| 9 | OBO 対象 | `1203` `1204` |
| 10 | Digest | `1306` |
| 11 | 形式有効、XML の Direct、SWORD クライアント、Workflow 設定 | `1409` `1410` `2103` `2104` `2105` |
| 12 | Workflow のスコープ `user:activity` | `1201` |
| 13 | 項目検査（bag のチェックサム、`bagit.txt` 欠落、非 UTF-8、JSON 構文、タイトル欠落） | `1501` |
| 14 | 登録済み、重複（クライアントの `duplicate_check`） | `1502` `1503` |
| 15 | 作成 | 201（Workflow は 202） |

PUT は 1〜6 の後、`2101` → 7 以降 → `1504` `1505` `1506` → `1503` → ロック `2201` → 200。
DELETE は認可（`item:delete`）→ OBO → `2101` → DOI `2106` → OBO 対象 → クライアント `2103`（`3102`）
→ `1201` → ロック `2201` → `2202` `2203` → 204。

エラー JSON は `{"@context","@type","timestamp","error":"WEKO_SWORDSERVER_E_xxxx: <文言>"}`。
ステータスと `@type` は `errors.py` の `ErrorType`、文言は英語カタログから転記した。
`tools/tests/test_stub.py` が `spec-draft/sword-error-codes` ブランチの
`fixtures/error-code-map.json` と全コードのステータス・msgid を突き合わせる（ブランチが無ければ skip）。
**生成物のコード表自体はこのブランチへコピーしていない。**

### スタブが決めた（実 WEKO と一致する保証のない）部分

- パッケージの読み方（CSV は 6 行目以降を項目、`.id` があれば既存、無ければ新規。XML は `dc:title`。
  JSON-LD は根の `Dataset` の `name` と `identifier`）。取込の写像・項目タイプは再現しない。
- ステータス文書の中身（`@id` に Object-URL、`metadata.dc:title` だけ）。
- 項目検査の理由文（`1501` の detail）。存在しない `.id` は `1501` にした。
- 無効な登録種別は DELETE で `3102`、PUT で `3103`、POST で `3201`。
- ハンドラ行 `[コード] METHOD path: message`（`handler_log`、既定で出す。4xx は WARNING、5xx は ERROR。実コードの
  `handle_weko_swordserver_exception` の書式）。ケースはこの行の存在を肯定的に断言する（`docs/LOG-JUDGEMENT.md`）。
- 範囲外のノイズ: 4xx の前の ERROR 行（`faithful_log`。実コードは `current_app.logger.error` を投げてから例外を送出する）と、
  無関係な ERROR とスタックトレース（`noise_log`）。どちらも `--faithful-log` で出し、判定には使わない（証跡と備考だけ）。
- POST 201 の `Location` ヘッダ（`location_header`、**実 WEKO は出さない。発見事項 F-6**）。

## ログ

`--log-file` に 1 行 1 レコード（`<UTC ISO8601> <LEVEL> sword-stub: <本文>`）で書く。
コード付き 4xx は WARNING、5xx は ERROR（偽のトレースバック付き）、401/403 は ERROR（実コードに合わせた）。
リクエスト行は `GET /path -> 200` の形で、ヘッダやトークンは出さない（テストで確認）。

## 制御用エンドポイント `/__stub__/`

| | |
|---|---|
| `GET /__stub__/state` | 世界の状態（トークン値は出さず名前だけ） |
| `POST /__stub__/fault` | `{"endpoint": "GET /sword/deposit/{recid}" or "*", "code": "3108", "count": 3, "stage": "auth"/"process"}`。次の N 回を 5xx にする。3108〜3110 は認証前、他は処理段階が既定 |
| `DELETE /__stub__/fault` | 注入した障害を全部外す |
| `POST /__stub__/reset` | 初期状態へ（`{"clear_log": true}` でログも消す） |

`/__stub__/helper`、`/__stub__/docker`、`/__stub__/logs` は偽 docker 用の内部口。

## 管理画面 `/stub-admin/`

`data-testid` 付きの小さな画面（Playwright 用）。ログイン（`login-user`、`login-password`、`login-submit`）、
トークン一覧と失効ボタン（`revoke-<name>`、`status-<name>`。設定の失効集合へ反映され、以後そのトークンは 401）、
コンソールエラーを出すボタン（`log-console-error`）。トークン値は画面に出さない。

## 偽 docker (`fake_docker.py`)

`PATH` の先頭に `docker` という名前で置き、`STUB_URL` にスタブの URL を入れる。

| 呼び出し | 動作 |
|---|---|
| `docker exec -i <c> python /opt/ath-helpers/run.py <cmd>` | stdin の JSON をスタブの状態に対して処理し `{"ok":true,"result":...}` を返す |
| `docker exec -i <c> redis-cli -n <db> GET/EXISTS/TTL/DEL/SETEX ...` | メモリ上の Redis。`lock` を含み末尾が recid のキーが生きている間、その recid は `2201` |
| `docker logs --since <ts> <c>` | スタブのアプリログ（`--since` 以降）を **標準エラー** へ。DB コンテナには SQL 風の行 |
| `docker stop|start|restart <c>` | web 停止＝接続を切る、db 停止＝認証前に 503 `3108`、redis 停止＝PUT/DELETE が 503 `3109`、search 停止＝`/sword/deposit/*` が 503 `3110` |

ヘルパー命令は `list` `ping` `create_user` `create_token`（`WEKO_TEST_TOKEN_` 接頭辞）`revoke_token`
`register_sword_client` `set_client_field` `create_record` `insert_doi_pid` `orphan_record` `snapshot`
`inject_fault` `restore_fault` `list_faults`。`snapshot` はトークン値を出さない。`inject_fault` の
`trigger_raise` / `check_violation_new_rows` は書き込みを `3105` / `3106` にする。
契約は `helpers/run.py` と `docs/helpers.md` に合わせた（`weko_suite_ext` が `docker` を PATH から探すので、
PATH だけで差し替わる。テストで確認済み）。

## 実行

```sh
uv sync
uv run pytest tools/tests/test_stub.py tools/tests/test_stub_docker.py -q   # スタブ自体のテスト
scripts/rig-e2e.sh                  # 生成→実行→証跡確認（ブラウザ含む）
scripts/rig-e2e.sh --no-browser     # Chromium 無し（CI はこちら、scripts/check.sh から呼ぶ）
scripts/rig-e2e.sh --unpatched      # F-1 の回避策を外す（エラーケースが落ちることの実演）
```

`rig-e2e.sh` がやること（`specs/` と `tests/` には触らず、一時ディレクトリに作る）:

1. `seeds/build_fixtures.py build` で `fixtures/generated/` を作る（git 管理外）
2. スタブを空きポートで起動、偽 `docker` を PATH へ、`WEKO_BASE_URL` などを設定
3. `plugin.yaml` の **コピー** に rig 専用操作（`examples/rig-ops.yaml`）を追加（本物は変更しない）
4. `examples/specs/`（基準 1、4xx ケース 2＋成功 1、シナリオ 1、UI ケース 1）をコピーして検証
5. hub の `generate-test.ts` で Python テストを生成
6. `ATH_EVIDENCE_DIR` を付けて pytest、続いて証跡を検査（生トークンが無い、Authorization がマスクされている、
   app-log / db-records / スクリーンショット / コンソール / ネットワークが在る）

Playwright が固定するリビジョンとサンドボックスの Chromium が違うときは、一時ディレクトリに
`PLAYWRIGHT_BROWSERS_PATH` 用のシンボリックリンクを作って回避する（コミットしない）。

## 検証結果の例（2026-10-08、このサンドボックス）

```
sc_rig_lifecycle.py::test_sc_rig_lifecycle PASSED
tc_rig_001.py::test_tc_rig_001 PASSED
tc_rig_1306.py::test_tc_rig_1306 PASSED
tc_rig_401.py::test_tc_rig_401 PASSED
tc_rig_ui.py::test_tc_rig_ui PASSED
ok   raw token absent from the evidence tree
ok   Authorization is masked in a saved exchange        ("authorization": "***REDACTED***")
ok   app-log evidence present (via fake docker logs)
ok   db-records evidence present (via fake docker + helper snapshot)
ok   screenshot present / browser console evidence present / browser network evidence present
ok   the intentional console error was captured
```

## 限界

- WEKO の項目タイプ、写像、ワークフロー、検索、非同期（Celery）、ロールの実際の判定は再現しない。
- 実コードの全分岐ではなく、テスト仕様が触る分岐だけ。`2401` `2402` `3107` `3101` の経路などは再現していない
  （`/__stub__/fault` で応答だけ出すことはできる）。
- 応答の細部（ヘッダ、ステータス文書の項目）は推測。これに合わせてテストを書かないこと。
- スタブで通ったことは、**実環境で通る根拠にならない**。逆に、スタブで落ちたら配管側の問題である可能性が高い。

## 発見事項

hub や `plugin.yaml` などスタブの担当外のファイルは**直していない**。振り分けのために記録する。

| # | 担当 | 内容 | 再現 |
|---|---|---|---|
| F-1 | **hub**（Python ランタイムと生成テスト）。**hub 78dd13a で修正済み**（`hub.lock` を更新）。以下は当時の記録 | ケース／シナリオの `evidence.ignore` が判定に反映されない。`run_case` / `run_scenario` は `RunOptions(observe=ObserveOptions(ignore=...))` からしか読まず、生成テストはオプションを渡さない。`plugin.yaml` の方針（エラーケースは `app_log: clean`、期待する ERROR 行は `ignore` で除く）では、**エラーケースが必ず落ちる**。`RunOptions` / `ObserveOptions` はパッケージ直下からも export されない | `scripts/rig-e2e.sh --unpatched` |
| F-2 | **`plugin.yaml` ＋ hub の設計**。**hub 78dd13a で修正済み**（params が `{{env.X}}`・`{{step.x}}` を描画する。Tier-1 の仕様はこれに依存）。以下は当時の記録 | `action.params` は描画されずに `param` スコープへ入る。`{{env.X}}` も `{{step.x}}` も params に書くと文字列のまま。`plugin.yaml` の操作は `token` / `recid` を params で受けるため、(a) トークンを環境変数から渡せない（仕様に生トークンを書くことになる）、(b) シナリオが作成した recid を `OP-SWORD-GET-DEPOSIT` / `PUT` / `DELETE` へ渡せない。回避は、操作のテンプレートに `{{env.X}}` / `{{step.recid}}` を直接書くこと（`examples/rig-ops.yaml` に実例）。ただし `{{step.*}}` を書いた操作はシナリオ専用になる | `rig-e2e.sh` の `OP-RIG-*-STEP` |
| F-3 | **`plugin.yaml`** | `ui` 接続（kind: browser）はあるが、ブラウザ操作が 1 つも無い。スクリーンショット、コンソール、ネットワークの証跡は browser 操作が走って初めて残るので、UI ケースが書けない | `examples/rig-ops.yaml` の `OP-RIG-ADMIN-FLOW` |
| F-4 | **`pyproject.toml` / `docs/HUB.md`** | 生成ファイル名が `tc_*.py` / `sc_*.py` で pytest の既定（`test_*.py`）に合わない。`pytest tests/generated` は **0 件収集で成功扱い**になる。docs はファイルを直接指定する書き方だけ | `-o python_files='*.py'` が必要だった。**対処済み**: `scripts/gen-test.sh` が `test_<id>.py` を出力し、`scripts/check-generated.sh`（`check.sh` から実行）が命名と収集数を検査する |
| F-5 | **hub**（`evidence.py`） | `app_log` の判定は、行に `error` / `exception` / `traceback` などの語があるかだけを見る（レベルを見ない）。WARNING でも `Item check error: ...`（`1501`）のような文言の行は問題行になる。F-1 と合わせて、1501 系ケースは `ignore` が必須になる | `evidence.py` の `_PROBLEM` |
| F-6 | **WEKO**（`views.py`） | POST `/sword/service-document` の 201/202 に `Location` ヘッダを付けていない（`jsonify(...), 201`）。docstring は「MUST respond with a Location header」。ステータス文書の `@id` に Object-URL があるので、シナリオは `body.@id` から recid を取る方が安全。スタブは要望に合わせて既定で `Location` を付けるので、実 WEKO とは**この点で違う** | `settings.location_header` |
| F-7 | **`plugin.yaml` の注記** | `OP-REDIS-SETEX`（S0-11 のロック模擬）が使うキー名は WEKO 側の実装依存で、スタブは `lock...<recid>` を仮定している。実際のキー名を `plugin.yaml` か仕様に書く必要がある（`lock_item_will_be_edit` の実装確認） | — |

## オーナー判断事項

1. **F-1 と F-2 の扱い**。どちらも「生成テストを実環境で動かす」前提を崩す。hub 側で直す（`ignore` の受け渡し、
   `action.params` の描画）か、`plugin.yaml` 側で操作を作り直すか（トークンは `{{env.*}}`、recid は `{{step.*}}` を
   テンプレートに直接）。後者は hub に手を入れずに済むが、操作の数が増え、`{{step.*}}` を使う操作はシナリオ専用になる。
2. **UI ケースを載せるか**（F-3）。載せるなら、WEKO のどの画面を最初に自動化するか（`data-testid` の追加を伴う）。
3. **CI でブラウザまで回すか**。いまは `--no-browser`（CI は Chromium を入れていない）。入れる場合は
   `playwright install chromium` の時間とキャッシュの扱いを決める。
4. **`Location` ヘッダを WEKO に求めるか**（F-6）。仕様書の期待値に書く前に、設計書の記述とコードのどちらを正とするか。
