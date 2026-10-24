# オッズ保存（collector）

実際の単勝オッズを基準にした予想の検証をするために、**発走前の単勝オッズ**を貯める仕組みです。お金を賭けない、記録上の検証です。

## しくみ

- `jra_odds_snapshot.py`：JRA公式の出馬表ページから、これから75分以内に発走するレースの単勝オッズ・人気・馬名・騎手・斤量・馬場などを取り出し、`data/odds/<日付>.jsonl` に1レース1回ぶんを1行で追記します（標準ライブラリのみ）。JRAの「オッズは○時○分現在」が前回と同じレースは、保存しません。発走後（結果ページになったレース）は保存しません。
- `.github/workflows/odds-snapshot.yml`：競馬開催日（JSTの土・日・月の8:00〜16:59）に、10分ごとに上の処理を実行して、保存先ブランチ **`odds-data`** に追記します。`main` は汚しません。手動実行（workflow_dispatch）もできます。

## 保存される内容（1行＝あるレースのある時点のオッズ）

`fetched_at`（取得時刻、JST）、`date`、`venue`、`race_no`、`post_time`（発走時刻）、`win5`（WIN5対象か）、`odds_time`（JRAのオッズ時刻）、`surface`、`dist`、`going`、`weather`、`cls`、`race_name`、`horses`（各馬の `num`・`name`・`odds`・`pop`・`sexage`・`wt`・`jockey`）。

## 使い道

発走の直前に取った最後のオッズを、各馬の市場確率（逆数を合計1に正規化）にして、結果（JRAの過去結果ページ、`research/factor-validation/` の取得コードで取れます）と照らします。人気順位より情報の多い「実際のオッズ」を基準にして、近走・騎手などの要素が上乗せになるかを、改めて検証します。数週間分たまってから行う予定です。

## 手で動かす

```sh
python3 collector/jra_odds_snapshot.py --window-min 90      # 今日のこれから90分以内のレース
python3 collector/jra_odds_snapshot.py --date 2026-10-24 --all --out /tmp/odds   # 全レース（確認用）
```

## 注意

- JRAのサイトに負担をかけないよう、リクエストの間隔を空けています（約0.4秒）。1回あたりの取得は、10〜15ページ程度です。
- 取得できない・形式が変わったときは、保存せずに終わります（推測で補いません）。
