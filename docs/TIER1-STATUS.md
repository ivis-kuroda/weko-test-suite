# Tier-1 仕様・テストの状況

v4.2 ケース仕様書の Tier-1 範囲を、hub の仕様エンティティ（`spec-draft/sword-error-codes` ブランチ）と
生成テスト（機能ブランチ `tests/generated/`）にした結果。**仕様はすべて機械生成の提案で、人のレビュー前**。
どのケースも `verified` にしていない（実 WEKO で一度も実行していない）。

## 読み方

| 列 | 意味 |
|---|---|
| 作成 | 仕様エンティティを書いたか |
| 生成 | `scripts/gen-test.sh` でテストを生成したか（`manual` は生成していない） |
| rig | `tools/sword-stub`（WEKO ではない）で機構が動いたか。**配管（multipart、env トークン、`{{step.x}}`、`produces`、`cleanup`、応答 JSON の判定、証跡のマスク）の確認であり、WEKO への適合ではない** |
| 阻害 | 実 WEKO での実行を妨げる、または自動化できない理由 |

rig の実行: `scripts/rig-run.sh --all`（68 件中 67 件合格。残り 1 件 S8-02 はスタブが WEKO と違うために落ちる）。
`--faithful-log` を付けるとスタブが 4xx の前に ERROR 行を出し、無関係な ERROR とスタックトレースも毎回出す（修正前の実コードの挙動 A-5 と、
範囲外のノイズ）。**この場合も 68 件中 67 件合格する**（ログの内容では不合格にしない。下の「ログ判定」）。終了時に
`tools/log_remarks.py` が範囲外の ERROR 行を備考として列挙し、`--all` で 1 件も出なければ rig-run.sh が失敗する
（ERROR 行が証跡から見えなくなっていないことの確認）。`--no-handler-log` はスタブがハンドラ行
`[コード] メソッド パス: メッセージ` を出さなくなる指定で、ハンドラ行を断言する全件（68 件中 29 件）が不合格になる（肯定判定の確認）。

## エンティティ数

| 種別 | 件数 |
|---|---:|
| 基準（BL-SW-GET-SERVICE-DOC / POST-DIRECT / GET / PUT-DIRECT / DELETE-DIRECT） | 5 |
| 因子（水準） | 6（EP5、書き込み EP2、トークン状態2、ロール5、ファイル不備4、パッケージ不正6） |
| マトリクス | 4（S1-03、S2-01、S5-02、S5-05） |
| ケース `TC-` | 61（うち生成 54、手動 5、実施不可 2） |
| シナリオ `SC-` | 15（うち生成 14、手動 1） |
| 生成テスト | 68 |

## 仕様ケースごとの状況

| 仕様 | エンティティ | 作成 | 生成 | rig | 阻害・備考 |
|---|---|---|---|---|---|
| S1-01, S1-02 | （範囲外。UI・前提作成、Tier 2） | - | - | - | `docs/spec-trace.md` に記載 |
| S1-03 | `TC-SW-S1-03-{ABSENT,REVOKED}-EP1..5`（10） | ○ | ○ | ○ | 無効トークンの 401/403 は U-21（改修前実測で確定） |
| S2-01 | `TC-SW-S2-01-<ROLE>-EP1..5`（25） | ○ | ○ | ○ | U-01（ロール別可否が未確定）。非破壊化のため入力を変更（判断事項 3） |
| S3-03 | `SC-SW-S3-03` | ○ | ○ | ○ | `SW_TOKEN_W2` が要る（bootstrap に追加） |
| S3-04 | `SC-SW-S3-04` | ○ | ○ | ○ | EP2 の成功に実メタデータが要る（`needs:real-metadata`） |
| S3-05 | `SC-SW-S3-05` | ○ | ○ | ○ | `SW_TOKEN_W2` |
| S3-06 | `SC-SW-S3-06` | ○ | ○ | ○ | トークン⑤の発行可否は Q-2 |
| S5-01 | `TC-SW-S5-01` | ○ | ○ | ○ | |
| S5-02 | `TC-SW-S5-02-{NOFILE,NOTSELECTED,NOCD,CDMISMATCH}-{EP2,EP4}`（8） | ○ | ○ | ○ | |
| S5-04 | `SC-SW-S5-04` | ○ | ○ | ○ | |
| S5-05 | `TC-SW-S5-05-<変種>-{EP2,EP4}`（12） | ○ | 8 | 8 | 非対応 Packaging・構成不正 3 種は自動。Content-Type は `blocked:content-type-not-expressible`、XML は `blocked:config-toggle-xml-S0-03`（手動 4 件） |
| S5-06 | `SC-SW-S5-06` | ○ | ○ | ○ | 構造欠落は実測（1501／3201 の許容範囲） |
| S5-07 | `SC-SW-S5-07` | ○ | ○ | ○ | 1503（類似）は重複検知の設定切替が要るため除外（`blocked:duplicate-check-toggle`） |
| S5-08 | `SC-SW-S5-08` | ○ | ○ | ○ | |
| S6-01 | `SC-SW-S6-01` | ○ | ○ | ○ | |
| S6-02 | `TC-SW-S6-02` | ○ | ○ | ○ | |
| S6-03 | `SC-SW-S6-03` | ○ | ○ | ○ | 413 は設定切替（S0-12）のため除外（`blocked:config-toggle-S5-03`） |
| S8-02 | `TC-SW-S8-02` | ○ | ○ | ×（スタブが 202 を返す） | 実 WEKO が必要。実メタデータの差し替えも要る。アクティビティが残る |
| S11-01 | `SC-SW-S11-01` | ○ | ○ | ○ | ロケール指定なし。U-11 は不要 |
| S11-02 | `SC-SW-S11-02` | ○ | - | - | `blocked:locale-method-U-11`（ロケールの指定方法が未確定。手動） |
| S12-01 | `SC-SW-S12-01` | ○ | ○ | ○ | 改修前ベースラインとの比較は `blocked:pre-change-baseline` |
| S12-02 | `SC-SW-S12-02` | ○ | ○ | ○ | 413 は設定切替で除外 |
| S12-03 | `SC-SW-S12-03` | ○ | ○ | ○ | |
| S12-04 | `TC-SW-S12-04` | ○ | - | - | `manual`、`blocked:pre-change-baseline`（比較対象も基準値も無い） |
| S15-07 | `TC-SW-S15-07` | ○ | - | - | `not_runnable`（下の「実施不可」）。仕様書も実施不可でクローズ |
| S15-15 | `TC-SW-S15-15` | ○ | - | - | `not_runnable`（M14。下の「実施不可」） |

## ログ判定（A-5 を含む。オーナー決定 2026-10-09）

WEKO の内部は、重要でない状況も範囲外の状況も区別せず、ERROR ログとスタックトレースを出す。そのため「ログに ERROR が
ない」を判定条件にすると範囲外のノイズを判定に引き込む。**アプリケーションログの内容では不合格にしない**。代わりに
ケースごとに「期待するハンドラ行が正しい場所から正しいレベルで存在する」ことを肯定的に確認する。詳細と限界は
[LOG-JUDGEMENT.md](./LOG-JUDGEMENT.md)。

- ハンドラ行: `[コード] METHOD path: message`（`handle_weko_swordserver_exception`。基本設計 5.4 のレベルは 4xx が WARNING、
  500・501・503 が ERROR）。`plugin.yaml` の `OP-APP-LOG` を `operation_result` + `matches` で読む（`tools/log_expect.py` が正規表現を作る）。
  76 エンティティのうち 36（タグ `log:handler-line`。実施不可の 2 件を含む）がこの断言を持つ。残り 40 は `log:not-judged`: コードなしの 401/403、
  成功系、S2-01 の許可ロール、S1-03（応答だけで判定。理由は LOG-JUDGEMENT.md）。
- 全エンティティで `evidence.ignore` は `.*`、ポリシーは `app_log: clean`（存在ゲート。収集できなければ inconclusive）。
  `tools/check_log_rule.py`（`scripts/check.sh` が実行）がこの規則を機械検査する。
- 範囲外の ERROR 行・スタックトレースは証跡の `diff-app-log-*` に残り、`tools/log_remarks.py <ATH_EVIDENCE_DIR>` が結果欄の
  備考にする。4xx と一緒に ERROR が出ていた場合だけ「A-5 候補」と注記する（実装担当への所見。不合格にも保留にもしない）。
- 観点 VP-SW-BD-60 / VP-SW-EG-19 の本文は、インポータの上書き（`tools/viewpoint_overrides.json`、
  [VIEWPOINT-OVERRIDES.md](./VIEWPOINT-OVERRIDES.md)）で差し替えた。生成物は手で直していない。xlsx と仕様書 v4.2 への反映はオーナー。
- **実 WEKO のログ書式でハンドラ行が合うかは未検証**（ローカルの最初のスパイクで実測する。合わなければ不合格になる。
  直すのは `tools/log_expect.py` の 1 か所と再生成）。

## 実施不可（not_runnable）

hub の `automation.status: not_runnable`（reason／checkedAt／checkedBy）。**ソース変更なしでは実施できないことが、
コードの読み取りで確かめられたものだけ**に付けた。オーナーの確認待ち（承認が出てソース変更でやる場合は `manual` に戻す）。
`ath-generate-test` は生成を拒否する。確認はすべて weko `test/sword-error-codes`（daf15d6f）の読み取り専用のコードパス確認。

| ケース | 内容 | 根拠 |
|---|---|---|
| `TC-SW-S15-07` | Workflow 経路でアクティビティが取れず 501（3107） | `_get_status_workflow_document` が activity_id 空で 3107 を送出するが、空になるのは `import_items_to_activity` が URL なしで返すとき（error も非空）だけで、`post_service_document`／`put_object` は error があれば先に 2401／3106 系を送出する。入力・DB・設定では到達できない。仕様書 v4.2 も実施不可でクローズ |
| `TC-SW-S15-15` | 形式判定が未知を返し 415（1411、M14） | `check_import_items` の else 節のみ。`check_import_file_format` は JSON／XML／TSV/CSV を返すか 1404〜1408 を送出するので到達不能（防御分岐）。M14 は動作中プロセスの関数の差し替えで、ソース変更（差し替え版での再起動）が要る |

**付けなかったもの（確認したが、実施不可と言えない）**:

- **1403（Packaging 必須）と 1408（Packaging 形式不可）**: `decorators.py` は `WEKO_SWORDSERVER_SERVICEDOCUMENT_ACCEPT_PACKAGING` に `*` が
  あるときだけ 1403 を、`*` かつ SimpleZip/SWORDBagIt 以外の値のときに 1408（`check_import_file_format`）に至る。既定の一覧
  では 1402 が先に出て到達しないが、**設定の変更（`["*"]` に切替。設定切替＋再起動の操作）で到達できる**。ソース変更は不要なので
  `manual`（設定切替 Tier 2）のまま。
- **1401（Content-Type 不可）**: リクエストとファイルパートの両方の Content-Type が許可外のときに出る。multipart ではリクエストの
  Content-Type が許可外になるので、ファイルパートの Content-Type を許可外にすれば到達する見込み。hub の http 操作で
  パートの Content-Type を指定できるかの問題（`blocked:content-type-not-expressible`、Q-5）で、実施不可ではない。
- M14 以外のモック（M1〜M13、M15）: DB／データ／環境の操作で作れる見込みで、ローカルのスパイクで成否を確かめる（HANDOFF）。

## 判断事項（オーナー確認）

仕様書の入力が曖昧・不足だったところ、または自動化のために形を変えたところ。黙って決めたものはない。

1. **多 EP・多入力のケースの形**。入力パターン表のあるケース（S1-03、S2-01、S5-02、S5-05）だけを因子・マトリクスで展開し、
   他は 1 仕様ケース = 1 エンティティにした。1 つの操作で書けないもの（EP2 と EP4、作成して削除、など）は
   シナリオ `SC-` にした。マトリクスの `strategy` は、仕様書がその表の全セルを実行するため `full` にした（本来は人の決定）。
2. **記録の使い方**。仕様書の R4（EP5 で消費）や R1（EP4 で更新）の代わりに、シナリオ内で `create_record` した
   自作レコードを使い、`cleanup` で `delete_record` する（R4 の再作成が不要）。R1/R2/R3/R9 は読み取りと拒否される要求にだけ使う。
   作ったレコードのタイトルは `ath-<run.id>-...`。`delete_record` は実コンテナで未検証（`docs/helpers.md`）。
3. **S2-01 は非破壊の入力にした**。許可されたロールで EP2 が項目を作り、EP5 が R4 を消すため、EP2 は
   ファイルパートなし（許可なら 1301）、EP4/EP5 は存在しない R9（許可なら 2101）で呼ぶ。認可は 1301・2101 の検査より先なので、
   「許可か不許可か」は見える。仕様書の「正常ファイル／R1／R4」とは違う。許可・不許可の確定は U-01 のため、
   一般ユーザ以外は許可の結果または 403（コードなし）を許容（`alsoAccepts`）。
4. **無効トークン（S1-03）**: 401 を期待し 403 も許容（U-21）。EP5 のセルは、R1 が削除されていないことを EP3 で確認する。
5. **コードなしの 401/403**: キー集合は検査せず、`error` が `WEKO_SWORDSERVER_E_` で始まらないことと `@type` の族
   （401: AuthenticationRequired／Unauthorized、403: Forbidden／AuthenticationFailed）だけを見る。改修前の文言・形式との一致は
   S0-06 が無く判定できない。
6. **`@type`** は `fixtures/error-code-map.json`（ステータスのみ）には無いので、詳細設計 2.0 のコード表の ErrorType を使った。
   14xx の構造不正のように仕様書が「いずれか」と書くものは族で許容。
7. **S3-04**: 仕様書は「成功または別要因のエラー」。作ったレコードを片付けるため `produces` で recid を取るので、
   成功（201／200／204）を期待にした。別要因のエラーだとステップが失敗する。
8. **S5-01**: 帯 `13xx` までを断言（仕様書どおり）。個別コードは S5-02 が担う。
9. **S5-05**: 非対応 Packaging の値（`http://example.org/ath/unsupported-packaging`）は仕様書に指定が無いので決めた。
   構造不正は「415 または 400、1404〜1407 のいずれか」。Content-Type は plugin の操作で指定できず、既定設定では到達不能の可能性（Q-5）。
10. **S5-07**: 「登録済みと同一」は、item ID が R1 のファイル（`put-item --id <R1>`）を EP2 に送る形にした（推定）。
    「メタデータ不備」用のファイルが無かったので `simplezip-no-title.zip` を fixtures に追加した。
11. **S5-08**: 1505（未登録）は ID なしのファイル（`put-item-without-id.zip`）、1506 は R2 の ID を持つファイルを R1 へ送る。
12. **ログ**。オーナー決定（2026-10-09）で、ログの内容では不合格にしない。ケースごとに期待するハンドラ行
    （`[コード] METHOD path: message`、4xx は WARNING、5xx は ERROR）が存在することを `OP-APP-LOG` の `operation_result` で肯定的に断言する
    （上の「ログ判定」）。コードなしの 401/403 はログ書式が無い（`handle_unauthorized`/`handle_forbidden`）ので断言しない。
    5xx の「ERROR 行がある」の断言は、Tier-1 に確定した 5xx ケースが S5-06 の実測ステップだけなので、そこに限る。
13. **S6-03、S12-02 の 413**、**S5-07 の 1503**、**S5-05 の XML** は設定切替が要るため含めない（オーナー決定 4）。
14. **S11-01**: 「英語」は、先頭語が英字で始まることと大文字スネークの識別子が出ないことで近似した。
15. **S12-01〜S12-04**: 改修前との比較が必要な部分は書けない。S12-01 はステータスと URL・メソッド（`@id` の形）だけ。S12-04 は基準値を作らず手動。
16. **POST の recid** は `body.@id` から `{from, pattern}` で取る（WEKO は `Location` を返さない。F-6）。
17. **Digest** は常に付ける（生成ファイルは `put-item` の標準出力から `produces` で取る）。Digest を省略した場合の挙動は未確認。
18. **`appliesTo`** は `branch: test/sword-error-codes`、`release: integration_test_spec_v4.2` のみ。weko のコミットは不明なので書いていない。
19. 削除フローは Start+End のみ（オーナー決定 2）。EP5 の Workflow 経路は 204（202 も許容）。

## 見つかった不具合・要望（担当ファイル別）

| 担当 | 内容 |
|---|---|
| hub `evidence.py` | 判定がレベルを見ない（F-5）。ログは `.*` 抑止の存在ゲートにして、ハンドラ行は `operation_result` で断言した。期待がすべて満たされ決めるチャンネルがポリシーに無いときに pass とする方式が欲しい（そうなれば `.*` は不要） |
| スタブ `stub_server.py` | `delete_record` ヘルパーが無かった（追加済み）。Workflow の複数アイテム登録を 202 の `StatusList` で返す（実 WEKO は仕様どおりなら 400／2401）。S8-02 が落ちる理由 |
| `plugin.yaml` | ロケール（Accept-Language）を指定する操作が無い（S11-02）。Content-Type を指定できない（S5-05）。管理設定（重複検知、XML）を切り替える操作が無い |
| seeds / fixtures | `simplezip-no-title.zip`、`SW_TOKEN_W2` を追加済み |
| 実環境の確認が要るもの | helpers の ORM 部分（特に `create_record`、`delete_record`）は未検証。fixtures の CSV は項目を実際に登録できる形ではない（S3-04、S8-02、S12-01 に `needs:real-metadata`） |

## オーナーに決めてほしいこと

1. U-21（無効トークンが 401 か 403 か）と U-01（ロール別の可否）の確定。S0-06 の改修前実測が前提。
2. ログ判定は肯定的なハンドラ行の断言で決定済み。残りは実 WEKO のログ書式（レベルが `[コード]` より前に 1 行で出るか）の確認と、
   仕様書 v4.2・観点表 xlsx への文面反映（VIEWPOINT-OVERRIDES.md）。
3. 設定切替を伴うケース（重複検知、XML、上限サイズ、ロケール）を自動化するか。plugin に設定変更の操作を足す必要がある。
4. 実メタデータ（対象環境から書き出した CSV）の用意。それまで S3-04、S8-02、S12-01 は実 WEKO で通らない可能性がある。
5. マトリクスの `strategy`（現在 `full`）。
6. 実施不可（`TC-SW-S15-07`、`TC-SW-S15-15`）の確認。ソース変更の承認が出るなら `manual` に戻す。1403／1408 は設定切替で到達できる
   ので実施不可にしていない（確認の根拠は上の表）。
