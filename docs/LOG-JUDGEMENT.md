# アプリケーションログの判定規則

オーナー決定（2026-10-09）。WEKO の内部は、改修範囲の外でも、重要でないものも重大なものも区別せず、ERROR ログと
スタックトレースを出す。そのため「アプリケーションログに ERROR 行がない」を判定条件にすると、範囲外のノイズを
判定に引き込む。**アプリケーションログの内容では、ケースもシナリオも不合格にしない**。

## 規則

1. ケースごとに、**期待するログ行が存在し、かつ正しい場所から正しいレベルで出ている**ことを肯定的に確認する。
   - 正しい場所: ブループリントのエラーハンドラ（`handle_weko_swordserver_exception`。429 は `handle_ratelimit`）。
     その行の書式は `[{code}] {method} {path}: {message}`（詳細設計 2.2 処理仕様 3。仕様書 v4.2 S13-01 の前提条件も
     同じ）。送出前の `current_app.logger.error(...)` はこの書式ではないので、それらや無関係な行は、この判定を満たせない。
   - 正しいレベル（基本設計 5.4）: **4xx は WARNING**。**500・501・503 は ERROR**。型で伝播する 503（`handle_dependency_error`。
     認証段階、EP3・EP5）はスタックトレース付き（仕様書 C-5xx-3）。EP2・EP4 のインポート段階の固定値経由の
     3108〜3110 はトレースを求めず、有無を記録する（F-08）。
2. それ以外のログ行（範囲外の ERROR 行、スタックトレース、4xx の前に出る `current_app.logger.error` を含む）は
   **判定に使わない**。証跡のログ差分（`diff-app-log-*`）に残し、結果欄の備考に記録する
   （`tools/log_remarks.py`）。4xx と一緒に ERROR が出ていた場合だけ「A-5 候補」と注記して、実装担当への所見にする。
3. 期待するハンドラ行が**ない**、レベルが違う、コードが違う場合は不合格（対象の不具合か、仕様書のログ書式の前提の誤りか
   をトリアージする）。

## hub の機構での表現

| 部品 | 内容 |
|---|---|
| `plugin.yaml` の `OP-APP-LOG` | web コンテナのログを `--since {{run.startedAt}}` で読む。`app_log` 証跡の収集もこの操作を使う |
| ケース／シナリオ手順の `expect` | `operation_result`（`OP-APP-LOG`、`params.since: "{{run.startedAt}}"`）の `matches` で、ハンドラ行の正規表現を判定する |
| ポリシー | `app_log: clean`（下の「なぜ informational でないか」）。`evidence.ignore` は全エンティティで `[".*"]` |
| タグ | `log:handler-line`（ハンドラ行を断言する）／`log:not-judged`（ログについて何も断言しない） |
| 補助ツール | `tools/log_expect.py`（正規表現を作る唯一の場所）、`tools/check_log_rule.py`（規則の機械検査。`scripts/check.sh` から実行）、`tools/log_remarks.py`（範囲外の ERROR 行を備考にする） |

正規表現（`re.search`。`Variant(code, status)` から作る）:

```
\bWARNING\b[^\n]*\[(?:WEKO_SWORDSERVER_E_)?1301\] POST /sword/service-document:
```

- レベルが同じ行の、コードより前にある。`[^\n]` で 1 行に閉じる。コードは `[1301]` でも `[WEKO_SWORDSERVER_E_1301]`
  でも通す（設計書は `{code}`＝数字部分。v2.2.0 のログはプレフィックス付き）。
- コードは帯（`13\d\d`、`140[4-7]`）や代替（1501 の WARNING または 3201 の ERROR）にもできる。
- 503 型伝播のトレース要求は `trace=True`: `... [3108] GET /sword/deposit/9: ...\nTraceback \(most recent call last\):`
  （ハンドラ行の直後にトレースが付いていること）。

### 具体例: `TC-SW-S5-02-NOFILE-EP2`（`spec-draft/sword-error-codes`）

```yaml
expect:
  - kind: http_status
    status: 400
  # ...（キー集合、error の先頭、@type はそのまま）
  - kind: operation_result
    operation: OP-APP-LOG
    params:
      since: "{{run.startedAt}}"
    assert:
      kind: matches
      pattern: '\bWARNING\b[^\n]*\[(?:WEKO_SWORDSERVER_E_)?1301\] POST /sword/service-document:'
evidence:
  ignore:
    - .*
tags: [..., log:handler-line]
```

ファイルパートのない EP2 は 400、`[1301]` のハンドラ行が WARNING で出ていれば合格。同じログに
`ERROR ... No file part.`（送出前の行）や無関係な `ERROR ... Traceback` があっても合否は変わらない。ハンドラ行が
無ければ、他に何が出ていても不合格。

### なぜ `informational` でなく `clean` と `.*` か

hub は、判定を決めたチャンネルが 1 つもないと `inconclusive` にする（確認済み: すべて `informational` だと必ず
inconclusive）。決められる他のチャンネル（`db_records` の `expected_change`、ネットワークの `*_response`、
スクリーンショット）は、まだ観測値を埋める実装がない。そこで `app_log: clean` を残し、全エンティティの
`evidence.ignore` を `.*` にする。結果、`app_log` は「収集できていること」だけを要求する存在ゲートになる
（収集失敗は inconclusive。証跡が無いのに pass にはならない）。行の内容では、レベルにかかわらず不合格にならない。
無視した行数は観測値の `suppressed` に残る。**hub への要望**: 期待（`expect`）がすべて満たされ、決めるチャンネルが
ポリシーに無い場合に pass とする方式があれば、`.*` は不要になる。

## 検証できていること・できていないこと

| 項目 | 状態 |
|---|---|
| 正規表現がハンドラ行（WARNING／ERROR、トレース）に合い、送出前の ERROR や無関係な行、別のコード・メソッド・パス・レベルに合わない | 単体テスト（`tools/tests/test_log_expect.py`） |
| スタブ（rig。WEKO ではない）で、範囲外の ERROR とトレースがあっても 68 件中 67 件合格（S8-02 はスタブが 202 を返すため落ちる） | `scripts/rig-run.sh --all --faithful-log` |
| ハンドラ行を欠いたスタブで、ハンドラ行を断言する全件が不合格 | `scripts/rig-run.sh --all --no-handler-log`（`scripts/check.sh` が 1 件で確認） |
| **実 WEKO のログ書式**（レベルがコードより前に 1 行で出るか、`[code]` の中身が数字だけか、ロガーの接頭辞） | **未検証**。合わなければ不合格になる。直すのは `tools/log_expect.py` の 1 か所と再生成 |
| ログの書き込みが応答より遅れて、実行時点でまだ読めない | 未検証。起きたら再実行、続くなら hub に再試行を要望 |

## 注意（限界）

- 期待は `run.startedAt`（秒単位）以降のログ全体を対象にする。同じシナリオの前の手順や、直前のテストと同じ秒に
  出た同じコード・メソッド・パスの行が、後の手順の欠落を隠すことがある（例: `SC-SW-S6-01` の GET 2101 が 2 回）。
  ファイル間は 3 秒空けて実行する（`scripts/run-ordered.sh`）。recid は期待に埋められない（`assert` はテンプレートを描画しない）。
- ハンドラ行を断言しないエンティティ（`log:not-judged`）: 成功系、コードなしの 401／403（`handle_unauthorized`・
  `handle_forbidden` は変更対象外でコードもログ書式も無い）、S2-01 の許可ロール（U-01 が未確定で、結果がコード付き 4xx か
  403 か決まらない）、S1-03（U-21）。これらはレスポンスだけで判定する。
- 429（S10、未作成）は `handle_ratelimit` が `logger.warning(ex)` とだけ書かれており、`[code] METHOD path:` 書式かどうか
  設計書から読み取れない（仕様書 S13-01 は書式ありとする）。S10 を作るときに実測する。

## 観点・仕様書の文言

観点 VP-SW-BD-60・VP-SW-EG-19 は、観点表（オーナーの xlsx）で「ERROR 行があれば不合格」となっていた。インポータに
上書きの仕組みを足して本文を差し替えてある（`tools/viewpoint_overrides.json`。一覧は
[VIEWPOINT-OVERRIDES.md](./VIEWPOINT-OVERRIDES.md)）。ケース仕様書 v4.2 の本文（S13-01、S15-16、4.5 A-5、
0 章 U-20、変更点 12）にも同じ記述が残るので、オーナーが仕様書と xlsx に反映する。
