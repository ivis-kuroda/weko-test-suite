# コンテナ内ヘルパー (`helpers/`)

テストコードはホスト（Python 3.11、hub のランタイム）で動く。一方、WEKO のデータベースに
触れる操作は WEKO 自身の ORM で行う必要があるため、`web` コンテナの中で動く小さな CLI
として `helpers/` を用意した。ホストからは `plugin.yaml` の `OP-HELPER`
（`weko_suite_ext.helper`）が `docker exec` で呼ぶ。

> **状態: 未検証。** このリポジトリの開発環境には docker デーモンがなく、WEKO を起動できない。
> 純粋ロジック（引数検証、SQL 生成、JSON 整形）は Python 3.11 の pytest で検証済みだが、
> ORM を使う部分と PostgreSQL に対する DDL は **実コンテナで一度も動かしていない**。
> 初回実行のチェックリスト（後述）を必ず通すこと。

## 配置と呼び出し

```sh
# ホストからコンテナへ配置する（<web> は WEKO_WEB_CONTAINER）
docker cp helpers <web>:/opt/ath-helpers

# 1 コマンド = 1 回の docker exec。stdin に JSON オブジェクト、stdout に JSON 1 個
echo '{}' | docker exec -i <web> python /opt/ath-helpers/run.py ping
docker exec -i <web> python /opt/ath-helpers/run.py list
```

`tests/` や `ruff.toml` もコピーされるが無害。不要なら
`docker cp helpers/. <web>:/opt/ath-helpers/` の後に `rm -rf /opt/ath-helpers/tests` でよい。

`python` はコンテナ内で WEKO の仮想環境（Python 3.6）を指している必要がある。そうでない場合は、
`docker exec` に渡す `python` を仮想環境のフルパスにする（初回チェック項目 1）。

## JSON 契約

- 入力: stdin に JSON オブジェクト 1 個（空なら `{}`）。
- 出力: stdout に 1 行の JSON オブジェクト 1 個。
  - 成功: `{"ok": true, "result": ...}`
  - 失敗: `{"ok": false, "error": {"type": "...", "message": "..."}}`
    DB 例外のときは `error.sqlstate` が付く。
- 終了コードは `ok: false` でも 0。非 0 はクラッシュ（契約外）のときだけ。
- ログと WEKO の import 時 print は stderr へ。stdout は応答専用。
- 秘密値を返すのは `create_token` の `access_token` だけ。パスワードハッシュ、
  クライアントシークレット、トークン値は `snapshot` を含む他のどこにも出ない。
- 冪等性: 各コマンドは再実行しても同じ状態に収束し、変更前の値を返す（ホストが復元できる）。

アプリケーションコンテキストは `invenio_app.factory:create_app` で作る
（`ATH_HELPERS_APP_FACTORY=module:callable` で上書き可、既定が失敗したら `create_ui` を試す）。
これは uwsgi が `invenio_app.wsgi` を使っていることからの推定で、**未検証**。

## コマンド一覧

| コマンド | 入力 | 結果 | ORM 部の確度 |
|---|---|---|---|
| `list` | なし | コマンド名の配列 | 純粋（検証済み） |
| `ping` | `{}` | `db_ok`, `db_version`, `packages`, `commit` | 低（app context 生成が未検証） |
| `create_user` | `email`, `password`, `roles[]`, `reset_password?` | `id`, `created`, `roles_added`, `previous` | 中 |
| `create_token` | `user_email`, `name`, `scopes[]`, `client_name?`, `token_prefix?`, `allow_unknown_scopes?` | `access_token`, `token_id`, `client_id`, `scopes`, `reused`, `previous_scopes` | 中 |
| `revoke_token` | `access_token` または `name`（+`user_email?`） | `deleted_tokens[]`, `deleted_clients[]` | 中 |
| `register_sword_client` | `client_id` または `client_name`, `registration_type`, `active?`, `mapping_name?`/`mapping_id?`, `workflow_id?`/`workflow_name?`, `delete_flow_id?`, `duplicate_check?` | `created`, `current`, `previous`, `previous_delete_flow` | 中 |
| `set_client_field` | `client_id`, `field`, `value` | `previous`, `value` | 中 |
| `create_record` | `title`, `owner_email`, `recid?`, `with_doi?`, `item_type_id?` | `recid`, `uuid`, `created`, `doi` | 低（`WekoDeposit.commit` が ES などに触れる） |
| `insert_doi_pid` | `recid`, `doi?` | `doi`, `created` | 中 |
| `delete_record_row` | `recid`, `tables?` / `restore` | `backup[]` / `restored_tables` | 中（raw SQL） |
| `orphan_record` | `recid` / `restore` | 同上（M15 用） | 中（raw SQL） |
| `baseline` | `emails[]?`, `recids[]?`, `index_ids[]?` | install.sh のデモデータの有無（ロール、ユーザー、アイテムタイプ、マッピング、フロー、ワークフロー、ロケーション、`admin_settings`、件数、recid の PID、関連設定値）。読み取り専用 | 中（raw SQL） |
| `create_flow` | `flow_name`, `for_delete?`（既定 true）, `with_approval?`, `repository_id?` | `id`, `flow_id`, `created`, `actions` | 中 |
| `create_workflow` | `flows_name`, `copy_from?`, `itemtype_id?`, `flow_id?`, `delete_flow_id?`/`delete_flow_name?`, `repository_id?`, `index_tree_id?`, `location_id?`, `open_restricted?` | `id`, `created`, `delete_flow_id`, `previous_delete_flow_id` | 中 |
| `delete_record` | `recid`, `method?`（`soft_delete` 既定 / `pid_only`）, `restore?` | `recid`, `previous`, `deleted` / `restored` | 低（WEKO の `soft_delete` を呼ぶ） |
| `snapshot` | `tables[]`, `recid?` | 表ごとの `count` と行キー → sha256 | 中（raw SQL、列名はモデルと照合済み） |
| `inject_fault` | `kind`, `params{}` | `fault_id`, `info` | 低〜中（レシピごと、下表） |
| `restore_fault` | `kind` または `"all"`（既定）, `fault_id?` | `restored[]`, `swept[]`, `warnings[]` | 低〜中 |
| `list_faults` | `catalog?` | 有効な障害の配列（無ければ `[]`） | 中 |

### 各コマンドの補足

- `create_user`: 既存ユーザーは `active`/`confirmed_at` を満たすよう更新し（変更前を `previous` に返す）、
  足りない役割だけ追加する。パスワードは `reset_password: true` のときだけ上書き。
- `create_token`: `Token.create_personal` と同じ行を作る。`scopes: []` は **ライブラリが許す**
  （`""` として保存。スコープ検証は CLI の `process_scopes` にしかない）ので、「スコープなし」
  トークンはそのまま作れる。未登録スコープは既定で `UnknownScope` エラー、
  `allow_unknown_scopes: true` で素通し。同名クライアント（`client_name`、既定は `name`）の
  トークンがあれば再利用し、スコープが違えば更新して `previous_scopes` を返す。
  `access_token` は既定で `WEKO_TEST_TOKEN_` で始まる（`plugin.yaml` の redact パターンに一致）。
  `token_prefix: ""` で素の `create_personal` に戻せる。
- `register_sword_client`: `registration_type` は `"Direct"`(1) / `"Workflow"`(2) / **生の整数**
  （不正値テスト用。0 や 99 も通す）。`SwordClientModel` を直接書くので、`Workflow` で
  `workflow_id` なしのような不整合も作れる（アプリの `SwordClient.register` は拒否する）。
  `delete_flow_id` は `sword_clients` の列ではなく `workflow_workflow.delete_flow_id`
  なので、参照先の WorkFlow に書いて前の値を返す。
- `set_client_field`: 許可フィールドは `active`, `registration_type_id`（または `registration_type`）,
  `mapping_id`, `workflow_id`, `duplicate_check`, `meta_data_api`。整数は型だけ検証し範囲は検証しない（M12）。
- `create_record`: `tests/helpers.py::create_record` を踏襲（recid/depid/parent の PID、PIDRelation、
  `WekoRecord`、`ItemsMetadata`、`WekoDeposit.commit`）。`RecordIdentifier` のカウンタを進めるので、
  明示 recid は稼働中のカウンタより十分大きい値（900000 以降など）にする。
  `with_doi` は `https://doi.org/ath-test/<recid>` の doi PID を作る。
  既存 recid なら `created: false` で何もしない。
- `delete_record_row` / `orphan_record`: `records_metadata`（と `item_metadata`）の行だけを
  削除し PID は残す（M15）。結果の `backup`（行の JSON）を `{"restore": <backup>}` で戻す。
- `snapshot`: 論理名は `items records pids activities sword_clients tokens clients users roles
  user_roles workflows flows flow_actions jsonld_mappings`。行は主キー相当の文字列 → sha256
  （選択列の正準 JSON）。`recid` は `items records pids activities` だけを絞り込む
  （他は `recid_filter: false`）。トークン値・パスワード・クライアントシークレット列は選択しない
  （テストで確認）。

- `baseline`: `seeds/bootstrap.py baseline-check` が使う。秘密値（パスワードハッシュ、トークン値、
  クライアントシークレット）は選択しない。判定（何が欠けているか）はホスト側で行う。
- `create_flow`: 削除フロー（`workflow_flow_define.flow_type = 2`）を作る。アクションは
  `begin_action` と `end_action`（`with_approval: true` で間に `approval`。承認者の設定は別途必要で、
  実機で未確認）。同名のフローがあれば何もしない（種別が違えば `FlowTypeMismatch`）。
- `create_workflow`: `copy_from` の行から未指定の列を写して `workflow_workflow` に行を追加する
  （デモのワークフローには触れない）。同名があれば `delete_flow_id` だけを揃え、前の値を返す。
  `delete_flow_id` が削除フロー（`flow_type = 2`）でなければ拒否する。
- `delete_record`: PID の状態を DELETED にして「削除済み recid」にする（R3 用）。`soft_delete` は
  UI と SWORD EP5（Direct）が使う `weko_records_ui.utils.soft_delete` を呼ぶ。`pid_only` は PID 行だけを更新する。
  `restore: true` で戻す。
- `register_sword_client`: マッピングは `mapping_id`（存在確認あり）または `mapping_name`（一意でなければ
  `AmbiguousMapping`）、ワークフローは `workflow_id` または `workflow_name`（同時指定は不可）。
  デモのマッピングは id 30001/30002、ワークフローは id 1/2。既存のワークフローへ `delete_flow_id` を
  書くとデモデータを書き換えるので、通常は `create_workflow` で新しいワークフローを作って使う。

### ホスト側で行うこと（ここでは実装しない）

`chmod_path {container_path, mode}`: ファイル権限の障害は `docker exec` で `chmod` するホスト側の仕事。
元の mode を `stat -c %a` で控えて復元する。

## 障害レシピ

オーナーの方針: **バックエンド障害は DB や環境の書き換えで再現し、ソースコードの改変は最後の手段。**
このヘルパーは WEKO のコードに一切触れない。作るオブジェクトはすべて `ath_fault_<n>_*`
という名前で、状態は `ath_fault_state` / `ath_fault_backup` に保存する。
どちらも障害が 0 件になると `DROP` されるので、`list_faults == []` で「何も残っていない」を確認できる。
`restore_fault all` は状態テーブルを後入れ先出しで巻き戻した後、`pg_trigger` / `pg_constraint` /
`pg_policy` / `pg_proc` から `ath_fault_` 接頭辞の孤児も掃除する（`kind: "orphan"` として
`list_faults` にも出る）。

| kind | 仮説（何を書き換えて何を起こすか） | 狙う spec モック | 確度 |
|---|---|---|---|
| `trigger_raise` | 対象表の BEFORE ROW トリガが指定 SQLSTATE を RAISE する。`event` insert/update/delete、`row_condition`（`column`,`op`,`value`,`ref`）で行を絞る | M3/M4（取込書き込みの SQLAlchemy エラー）、M5/M13-DB（削除時エラー: 23xxx/42xxx と 08006 の比較） | 中 |
| `check_violation_new_rows` | `CHECK (false) NOT VALID` 制約。新規・更新行が SQLSTATE 23514 で失敗する（既存行は検査されない）。`row_condition` で行を絞れる | M3/M4/M5 | 中 |
| `rls_raise_on_row` | 対象表に RLS を ENABLE+FORCE し、`CASE WHEN column=value THEN ath_fault_*() ELSE true END` のポリシで、その行を読むと RAISE。適用前の RLS 状態を記録し、復元時は元が無効・非 FORCE だった場合にだけ戻す。既定は `FOR SELECT` | M1（読み取り経路の非接続 DB エラー）、M8/M10（On-Behalf-Of のユーザー検索で対象ユーザー行を読むと DB エラー） | 低 |
| `corrupt_record_json` | `records_metadata`/`item_metadata` の JSON を `empty_object` / `json_string` / `json_array` / `null_json` / `drop_key` に壊す。元の行を `ath_fault_backup` に保存 | M9 | 中 |
| `corrupt_mapping_json` | `jsonld_mappings.mapping` を同様に壊す | M7（壊れたマッピング） | 中 |
| `break_workflow_flow` | `delete_flow_actions`（既定: フローのアクション行を退避して削除）/ `flow_status` / `mark_deleted` | M11/M6 | 低〜中 |
| （レシピなし）`set_client_field` | `registration_type_id` に不正な整数 | M12 | 中 |
| （レシピなし）`orphan_record` | PID が残り record 行が無い | M15 | 中 |
| （ホスト側）`chmod_path` | ファイル権限 | — | — |

注意点:

- **RLS は DB ロールが superuser/BYPASSRLS だと無効。** そのときは `RlsBypassed` エラーで拒否する
  （`allow_bypass: true` で強制）。WEKO の既定構成（`invenio` ユーザー）がどちらか不明。
  回避できない場合は M8/M10 を `trigger_raise`（`event: update` など）か、ユーザー行を読む
  経路の別手段で再現する必要があり、**オーナー判断事項**。
- pgpool 経由の DDL が通るか、SQLSTATE 08006 が SQLAlchemy/pgpool でどう扱われるか（接続断扱いで
  リトライされる等）は未検証。
- 障害はトランザクションごとに作る。途中で失敗すれば `ROLLBACK` され何も残らない。
- 例: `{"kind":"trigger_raise","params":{"table":"records","event":"delete","sqlstate":"23503"}}`

## 初回実行チェックリスト（実コンテナで）

期待値は「`ok: true`」を基本とし、気になる点だけ書く。

1. `docker cp helpers <web>:/opt/ath-helpers` のあと `run.py list` が 19 個前後の名前を返す。
   `python` が WEKO の Python 3.6 であること（`python --version`）。
2. `ping`: `db_ok: true`。失敗したら `appctx.build_app` のファクトリ（`ATH_HELPERS_APP_FACTORY`）を直す。
   インスタンス設定（`invenio.cfg`）が読めているか。
3. `create_user` を 2 回: 1 回目 `created: true`、2 回目 `created: false`、`roles_added: []`。
   ログインできる（`confirmed_at`、`active`）。
4. `create_token` で `scopes: []` と `["deposit:write"]` を作り、`Authorization: Bearer <token>` で
   SWORD の `/sword/service-document` を叩いて認証が通ること。`WEKO_TEST_TOKEN_` 接頭辞が
   通らない（JWT 検証が有効など）場合は `token_prefix: ""` を試す。
5. `register_sword_client`: 作成→更新で `previous` が入る。`registration_type: 99` を通す。
6. `create_record` を `recid: 900001` で。作成後 `snapshot` の `records`/`items`/`pids` が 1 行ずつ。
   Elasticsearch への反映有無と、`item_type_id` を省略したときの既定が妥当か。
7. `orphan_record` → `snapshot`（`pids` は残り `records` は 0 行）→ `{"restore": ...}` で元に戻る。
8. `inject_fault`/`restore_fault` を各レシピで: 注入 → 狙った操作が期待 SQLSTATE で失敗 →
   `restore_fault all` → `list_faults == []`、`snapshot` が注入前と一致。特に
   `rls_raise_on_row`（ロールの BYPASSRLS）、`trigger_raise` の `08006`、`break_workflow_flow` の復元。
9. `snapshot` の出力にトークン値・パスワードハッシュが無い。`snapshot` を 2 回連続で取り、差分が空。
10. すべてのコマンドで stdout が 1 行の JSON（WEKO の起動ログが混ざらない）。

11. `baseline` が install.sh 直後の環境で、ロール 4 つ、ユーザー 5 人、アイテムタイプ 30001/30002、
    マッピング 30001/30002、フロー id 1、ワークフロー id 1/2、ロケーション `local` を返す。
12. `create_flow`（2 回目は `created: false`）→ `create_workflow`（`copy_from: 2`）→
    `register_sword_client`（`registration_type: "Workflow"`, `workflow_id`）→ EP5 が Workflow 経路になる。
13. `delete_record` 後に EP3 が 404 を返す（`soft_delete` が実環境で動くか。動かなければ `pid_only`）。

初回実行の全体手順は `docs/BASELINE.md` と `seeds/bootstrap.py` を参照。

## 開発

```sh
cd helpers
ruff check . && ruff format --check .
pytest          # Python 3.11。純粋ロジックと、注入したフェイクに対する検証
```

- Python 3.6 互換: walrus、f-string の `=`、`dataclasses`、`from __future__ import annotations`
  は使わない。`tests/test_py36_syntax.py` が `ast.parse(feature_version=(3, 6))` で全 `helpers/*.py` を検査する
  （ruff の最古ターゲットは py37 なので、3.6 文法の判定はこのテストが担う）。
- 構成: `run.py`（ディスパッチ）、`contract.py`（契約と検証、純粋）、`registry.py`、
  `appctx.py`、`dbx.py`（raw SQL 実行）、`faultlib.py`（レシピと復元、純粋＋実行器注入）、
  `cmd_*.py`（WEKO の import は関数内で遅延）。
