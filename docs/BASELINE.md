# テスト開始時の環境（ベースライン）

WEKO3 は `install.sh` がデモデータを投入して初めて使える状態になる。このスイートは
**「`install.sh` を実行した直後の環境」から始める**ことを前提にし、シナリオ間で環境を
初期化しない。したがって次の約束を守る。

- テストは自分で作るデータに一意な名前（例: `ath-<日時>-<乱数>`）を付け、終了時に自分で片付ける。
- 破壊的な障害ケース（S14/S15）は、復元手順（`restore_fault`、`delete_record_row` の `restore` など）を
  必ず通して終わる。
- 環境を最初からやり直したいときだけ `install.sh` を使う（下記の危険事項）。

## 1. スイートが存在を前提にするもの（`install.sh` が作る）

`/home/user/weko` の `install.sh` → `scripts/populate-instance.sh` と `scripts/demo/*.sql` で確認した内容。

| 区分 | 内容 |
|---|---|
| ユーザー | すべてパスワードは `INVENIO_USER_PASS`（手順書の例では `uspass123`）。下の対応表を参照 |
| ロール | `System Administrator`、`Repository Administrator`、`Contributor`、`Community Administrator` |
| アイテムタイプ | 30001（シンプル）、30002（フル） |
| JSON-LD マッピング | id 30001 `デフォルトマッピング（シンプル）`、id 30002 `デフォルトマッピング（フル）` |
| フロー | `Registration Flow`（id 1、登録フロー）。**削除フローは無い** |
| ワークフロー | id 1（アイテムタイプ 30002）、id 2（アイテムタイプ 30001）。どちらも削除フローなし |
| インデックス | id 1623632832836 |
| ファイルロケーション | `local`（`/var/tmp`、既定） |
| 管理設定 | `admin_settings` の id 1〜9 |
| 無いもの | SwordClient、OAuth2 クライアント/トークン、`sword_api_setting`、コミュニティ |
| 設定 | `SESSION_COOKIE_SECURE = True`、On-Behalf-Of 有効、On-Behalf-Of で拒否するロールは `System Administrator` のみ（`WEKO_ITEMS_UI_SHARED_USER_EXCLUDED_ROLE_NAME_LIST`） |

### デモユーザーと仕様書（S0-01）のロールの対応

デモユーザーを使い、新規ユーザーは作らない（欠けているときだけ `bootstrap` が作る）。

| 仕様書のロール | ユーザー | WEKO のロール | `.env.local` の変数 |
|---|---|---|---|
| システム管理者 | `wekosoftware@nii.ac.jp` | System Administrator（スーパーユーザー） | `SW_USER_SYSADMIN` |
| リポジトリ管理者 | `repoadmin@example.org` | Repository Administrator | `SW_USER_REPOADMIN` |
| コミュニティ管理者 | `comadmin@example.org` | Community Administrator | `SW_USER_COMADMIN` |
| コントリビュータ | `contributor@example.org` | Contributor | `SW_USER_CONTRIBUTOR` |
| 一般ユーザ | `user@example.org` | ロールなし（SWORD の登録・更新・削除は 403 になる想定） | `SW_USER_GENERAL` |
| U-OBO-OK（許可対象ロール） | `contributor@example.org` | Contributor | `SW_USER_OBO_OK` |
| U-OBO-NG（許可対象外ロール） | `wekosoftware@nii.ac.jp` | System Administrator | `SW_USER_OBO_NG` |

On-Behalf-Of の判定は `weko_items_ui.utils.is_shared_user_role_allowed`。除外ロールを持つユーザーを
`On-Behalf-Of` に指定すると 403 になる。別のユーザーを使いたいときは環境変数 `SW_USER_OBO_OK` /
`SW_USER_OBO_NG` か `--obo-ok` / `--obo-ng` で指定する（無ければ作る。OK 側は Contributor、NG 側は
System Administrator を付与）。

## 2. `bootstrap` が作るもの

`seeds/bootstrap.py run` が、ベースラインの上に仕様書 S0-02/S0-03/S0-05 が要るものだけを足す。
すべて `docker exec` で web コンテナのヘルパーを呼んで作る（ホストにデータベースの権限は要らない）。

| 仕様書 | 作るもの | 備考 |
|---|---|---|
| S0-01 | 欠けているデモユーザー・OBO ユーザー | 通常は何も作らない |
| S0-03 | 削除フロー `ath-sword-delete-flow`（`flow_type = 2`、Start→End） | 無いと EP5 が Direct 削除になる |
| S0-03 | ワークフロー `ath-sword-workflow`（ワークフロー id 2 の複製、削除フロー付き） | **デモのワークフローは書き換えない** |
| S0-03 | C-D: `sw-cd-*` クライアントに SwordClient（Direct、マッピング 30001） | |
| S0-03 | C-W: `sw-cw` に SwordClient（Workflow、上のワークフロー、マッピング 30001） | |
| S0-03 | C-OBO: `sw-cobo` に SwordClient（Direct） | |
| S0-03 | C-X: `sw-cx` は OAuth2 クライアントのみ（SwordClient なし） | |
| S0-02 | トークン ①②⑤、T-REV、失効済み③、C-W/C-OBO/C-X 用、ロール別① | 下表。値は `.env.local` にだけ書く |
| S0-05 | 記録 R1〜R8（recid 900001〜900008）。R2 は DOI 付き、R3 は作成後に削除、R9（900009）は作らない | |

| 変数 | 内容 |
|---|---|
| `SW_TOKEN_1` | ①: アクティビティ用スコープあり。C-D、所有者はシステム管理者 |
| `SW_TOKEN_2` | ②: write・actions・item:* あり、`user:activity` なし |
| `SW_TOKEN_3` / `SW_TOKEN_REVOKED` | ③: 作成後に失効済み（同じ値） |
| `SW_TOKEN_4` | ④: 未提示。**常に空** |
| `SW_TOKEN_5` | ⑤: スコープなしで発行 |
| `SW_TOKEN_REV` | T-REV: 失効用（S1-02 で失効させる。他では使わない） |
| `SW_TOKEN_W` / `SW_TOKEN_OBO` / `SW_TOKEN_X` | ① 相当のスコープで C-W / C-OBO / C-X 用 |
| `SW_TOKEN_W2` | ② 相当（アクティビティ用スコープなし）で C-W 用（`sw-cw-2`、同じ Workflow）。S3-03・S3-05 用 |
| `SW_TOKEN_ROLE_*` | ロール別の① （S2-01）。所有者がそのロールのユーザー |
| `SW_CLIENT_ID_1` / `_2` / `_3` / `_X` | C-D / C-W / C-OBO / C-X の OAuth2 クライアント ID |
| `SW_R1`〜`SW_R9` | 状態データの recid |
| `SW_WORKFLOW_ID`, `SW_DELETE_FLOW_ID`, `SW_ITEM_TYPE_ID` | 作ったワークフロー、削除フロー、記録のアイテムタイプ（30001） |

注意:

- 1 つのトークンには 1 つの OAuth2 クライアントが付く（WEKO の個人トークンの作り方どおり）。
  仕様書の「C-D」は複数のクライアントの総称になり、`sw-cd-*` はすべて同じ設定（Direct、マッピング 30001）。
  `SW_CLIENT_ID_1` は ① のクライアント。
- スコープ ID は `deposit:write`、`deposit:actions`、`item:create`、`item:update`、`item:delete`、
  `user:activity`（コード上の定義で確認済み）。
- 記録の所有者はシステム管理者、アイテムタイプは 30001（Direct の C-D のマッピングと同じ）。
- R4/R5 は使うと消費される。仕様書の再作成規則どおり、使ったら `create_record` で作り直して
  `.env.local` の値を更新する。

## 3. ベースラインを確認する

```sh
uv sync                                   # 初回のみ
set -a; . ./.env; set +a                  # WEKO_WEB_CONTAINER など（無ければ既定値）
docker cp helpers/. "$WEKO_WEB_CONTAINER":/opt/ath-helpers   # helpers の配置（docs/helpers.md）

uv run python seeds/bootstrap.py baseline-check
```

`baseline-check` は何も変更しない。結果を `[ERROR]`（足りない前提。`bootstrap` を止める）、`[WARN]`
（作る予定・要確認）、`[INFO]` で並べ、エラーがあれば終了コード 1 を返す。主な確認項目:

- ロール 4 種、アイテムタイプ 30001/30002、マッピング 30001/30002（アイテムタイプとの対応）、
  登録フロー id 1、ワークフロー id 1/2、ファイルロケーション。
- デモユーザーが有効で、期待するロールを持つこと。`confirmed_at` が空なら警告（`install.sh` は
  `--active` だけで作るため。UI のログインが通るかを確認する）。
- OBO 用ユーザーのロールが、除外ロールの設定と食い違わないこと。
- R9 の recid（900009）が存在しないこと。

何を呼ぶかだけを見たいときは `uv run python seeds/bootstrap.py run --dry-run`（docker は使わない。
パスワードとトークンは `***` で表示）。

```sh
uv run python seeds/bootstrap.py run      # .env.local を書く（権限 0600、git 管理外）
```

`run` は何度実行しても同じ状態に収束する（トークンは再利用、記録とフローは名前/recid で検出）。
例外は ③ の失効済みトークンで、毎回作り直して失効させるので値が変わる。標準出力には変数名だけを出し、
トークンの値やパスワードは出さない。テストを走らせる前に
`set -a; . ./.env; . ./.env.local; set +a` で読み込む。

## 4. 接続（TLS と hosts）

| 経路 | `WEKO_BASE_URL` | 備考 |
|---|---|---|
| web コンテナ直結（既定） | `http://127.0.0.1:5001` | 証明書不要。アップロードサイズ境界のケースはこちら（nginx が先に 413 を返し得るため） |
| nginx | `https://weko3.example.org` | 自己署名証明書。`/etc/hosts` に `127.0.0.1 weko3.example.org` を足す（または `curl --resolve weko3.example.org:443:127.0.0.1`）。`curl -k`、または `SSL_CERT_FILE` に証明書を指定 |

`SESSION_COOKIE_SECURE = True` のため、ブラウザでの操作（UI ケース）を `http://127.0.0.1:5001` で行うと
セッション Cookie が保存されない可能性がある（**未検証**）。UI ケースは https の経路を使う。
Bearer トークンでの API 呼び出しには影響しない。プロキシ環境では `NO_PROXY=127.0.0.1` を設定する。

## 5. 危険事項

- **`install.sh` は破壊的**。`docker compose down -v` でボリュームごと消し、データベースを作り直す。
  `bootstrap` や テストから呼ばないこと。環境を初期化したいときだけ人が実行し、その後で
  `baseline-check` → `bootstrap run` をやり直す（トークンも記録も消えるので `.env.local` を作り直す）。
- `scripts/demo/resticted_access.sql` は `install.sh` で**コメントアウト**されている。投入されていない
  ものとして扱う（制限公開の ID 31001 台のフローは無い）。
- 既存のワークフロー（id 1/2）に `register_sword_client` の `delete_flow_id` を書くと、デモデータを
  書き換える。C-W には `bootstrap` が作る専用ワークフローを使う。
- `create_user` は既存ユーザーの `confirmed_at` を埋める（`previous` に変更前を返す）。`bootstrap` は
  存在するユーザーに対して呼ばない。
- 記録は `RecordIdentifier` のカウンタを進める。recid は 900000 以降にする（`--recid-base`）。
- XML の登録（S5-05）は管理画面の `sword_api_setting` を変更する。終わったら元に戻す。
- `.env.local` には秘密値が入る。コミットしない、貼り付けない（`.gitignore` の `.env.*` で除外済み）。
