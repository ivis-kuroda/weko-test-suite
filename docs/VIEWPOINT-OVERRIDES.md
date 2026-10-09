# 観点本文の差し替え（インポータの上書き）

観点 YAML（`specs/viewpoints/`）は、オーナーの観点表（xlsx）から `tools/import_viewpoints.py` が生成する。生成物を
黙って手で直さない。xlsx より先に本文を変えると決まったものは、`tools/viewpoint_overrides.json` に
**理由と原文付き**で書く。インポータはその本文で置き換えて生成し、観点 YAML の `source` に「差し替え済み」の項目
（`kind: other`、`note` に理由と原文）を足す。再生成しても同じバイト列になる。

- 形式: `id`（観点表の ID。`BD-60`）、`field`（`precondition`／`operation`／`expected`）、`from`（原文。セルの文字列の
  そのまま）、`to`（差し替え後）、`reason`。
- `from` が観点表に無く `to` も無いときはエラー（古い上書き）。`to` が既に観点表にあるときは「obsolete」と警告するので、
  xlsx に反映した後で上書きを消す。
- 再生成: `uv run python tools/import_viewpoints.py --xlsx <観点表.xlsx> --spec-md <仕様書.md> --out-root <作業ツリー>`
  （`--overrides` を省くと `tools/viewpoint_overrides.json`）。出力のうち観点 YAML だけを `spec-draft/sword-error-codes` に
  YAML のみのコミットとして入れる。

## 上書き一覧（オーナーが xlsx に反映する）

理由はどちらも同じ（オーナー決定 2026-10-09、[LOG-JUDGEMENT.md](./LOG-JUDGEMENT.md)）: アプリケーションログの
「ERROR 行がない」は判定条件にしない。範囲外のノイズが判定に入り込むため。期待するハンドラ行が正しい場所から正しい
レベルで出ていることを肯定条件にする。

### BD-60（4xx は WARNING）、`期待結果`

原文:

> ハンドラ行（`[code] METHOD path: message` 書式）がすべて WARNING。INFO で記録されない。かつ 4xx 応答のログに ERROR 行がない（同一リクエストに ERROR 行が併存すれば不合格。送出前の `current_app.logger.error` が出る場合は「実装不具合候補」として記録。U-20）

差し替え後:

> ハンドラ行（`[code] METHOD path: message` 書式。`handle_weko_swordserver_exception`、429 は `handle_ratelimit`）が出ていて、そのレベルがすべて WARNING。INFO で記録されない。判定はこのハンドラ行の有無とレベルだけで行い、同一リクエストやアプリケーション全体の ERROR 行・スタックトレース（送出前の `current_app.logger.error` や改修範囲外の既存ログを含む）の有無では合否を決めない（WEKO の内部は重要度に関わらず ERROR・トレースを出すため）。範囲外の ERROR 行・トレースは証跡のログ差分に残し、結果欄の備考に記録する（送出前の ERROR は「実装不具合候補」A-5。U-20）

### EG-19（EP5 の 2102）、`期待結果`

原文の末尾:

> 4xx のログ基準（BD-60）: 送出前に `current_app.logger.error`（`Record not found: {recid}.`）が出るため、ハンドラ行 WARNING と併存すれば BD-60 と同じ「実装不具合候補」（A-5。U-20）として記録する

差し替え後の末尾:

> 4xx のログ基準（BD-60 と同じ）: ハンドラ行（`[2102] DELETE /sword/deposit/<recid>: Record not found.`）が WARNING で出ていることを判定する。送出前に `current_app.logger.error`（`Record not found: {recid}.`）が出ても合否には使わず、証跡のログ差分と結果欄の備考に「実装不具合候補」（A-5。U-20）として記録する

（全文は `tools/viewpoint_overrides.json`。EG-19 の前半は原文のまま。）

## 観点表以外に残る同じ記述（オーナーが反映する）

ケース仕様書 v4.2（`integration_test_spec_v4.2.md`）: S13-01 の期待結果 2・3 行目（「ERROR 行が併存すれば不合格」、
「不合格となる見込み」）、S15-16 のログ欄、4.5 の A-5、0 章の U-20、v4.1 変更点 12（F-09）。観点 EG-18・BD-70 の
「ログはハンドラ行が WARNING」は新しい規則と合うので変更しない。
