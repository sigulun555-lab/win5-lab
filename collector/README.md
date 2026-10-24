# オッズ保存（collector）

実際の単勝オッズを基準にした予想の検証をするために、**発走前の単勝オッズ**を貯める仕組みです。お金を賭けない、記録上の検証です。

## しくみ（収集は2つに分けています）

`jra_odds_snapshot.py` は、実行のたびに、次の3つを `odds-data` ブランチの `odds/` に追記します（標準ライブラリのみ。`--scope` で切り替え）。

| scope | 保存先 | 内容 |
|---|---|---|
| `all`（通常の収集） | `odds/<日付>.jsonl` | これから75分以内に発走するレースを、1レース1行で保存。WIN5のレースには `win5: true` と `win5_leg`（1〜5）が付く。WIN5以外のレースが混ざるのは設計どおり（検証用のデータを広く貯めるため）。 |
| `win5`（WIN5だけ） | `odds/win5/<日付>.jsonl` | JRA公式の「WIN5対象レース」一覧を取得し、開催ページの印と、会場・レース番号・順番で照合する。**ちょうど5レースで、欠落・余分・重複・順番違いがないときだけ**、5レース1組で保存。 |
| 既定 `both` | 上の両方 | WIN5の組は、第1レースの発走前までに限る。 |

どちらも、取得したJRAの「オッズは○時○分現在」が前回と同じなら保存しません。発走後（結果ページになったレース）は保存しません。

**照合に失敗したとき**：WIN5の組は保存せず、終了コード2で終わります（GitHub Actionsの収集の手順が赤になります）。通常の収集で取れたぶんは、そのまま保存されます。

**ログ**：実行のたびに `odds/logs/<日付>.jsonl` に1行追記します。取得元（URL・cname）、取得時刻、公式の対象レース一覧と締切時刻、開催ページで見つかった印、照合結果（欠落・余分・重複・順番違い）、保存結果（件数、WIN5の組を保存したか）、注意、リクエスト回数が入ります。

## ワークフロー

- `.github/workflows/odds-snapshot.yml`：競馬開催日（JSTの土・日・月の8:00〜16:59）に10分ごとに実行（`--scope both`）。実行の前に、収集コードのテストを走らせます。手動実行（workflow_dispatch）もできます。
- `.github/workflows/win5-morning-snapshot.yml`：土・日の朝8:00に、その日のこれからのレースを広く保存します。
- 2つのワークフローは、同じ `odds-data` ブランチに書くため、同時に動かないよう、同じ排他の名前（`odds-data-writer`）にしてあります。
- `.github/workflows/collector-tests.yml`：`collector/` と `tests/` の変更で、テストを実行します。

### 保存されるWIN5の組（1行）

`fetched_at`、`date`、`deadline`（公式の締切時刻）、`official_source`、`verified`、`odds_times`（5レースのオッズ時刻）、`races`（`leg`・`venue`・`race_no`・`post_time`・`odds_time`・`surface`・`dist`・`going`・`weather`・`cls`・`race_name`・`horses`）。

### 通常の収集の1行

`fetched_at`、`date`、`venue`、`venue_code`、`race_no`、`post_time`、`win5`、`win5_leg`、`odds_time`、`surface`、`dist`、`going`、`weather`、`cls`、`race_name`、`horses`（`num`・`name`・`odds`・`pop`・`sexage`・`wt`・`jockey`）。

## 使い道

発走の直前に取った最後のオッズを、各馬の市場確率（逆数を合計1に正規化）にして、結果（JRAの過去結果ページ、`research/factor-validation/` の取得コードで取れます）と照らします。人気順位より情報の多い「実際のオッズ」を基準にして、近走・騎手などの要素が上乗せになるかを、改めて検証します。数週間分たまってから行う予定です。

## 手で動かす

```sh
python3 collector/jra_odds_snapshot.py --window-min 90      # 通常の収集 + WIN5の照合（--scope both）
python3 collector/jra_odds_snapshot.py --scope win5         # WIN5の5レースだけ
python3 collector/jra_odds_snapshot.py --date 2026-10-24 --all --out /tmp/odds   # 全レース（確認用）
python3 -m unittest discover -s tests -p "test_collector.py" -v                 # テスト
```

## 注意

- JRAのサイトに負担をかけないよう、リクエストの間隔を空けています（約0.4秒）。1回あたりの取得は、10〜15ページ程度です。
- 取得できない・形式が変わったときは、保存せずに終わります（推測で補いません）。
