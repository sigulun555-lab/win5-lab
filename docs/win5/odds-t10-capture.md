# 全レース 発走10分前オッズの記録（odds-t10）

目的: 将来のモデル比較で、市場確率の基準データとして使えるよう、JRAの全レースについて「発走10分前以前の最新」の単勝オッズを保存する。前向き検証のためではない。
既存の `odds-snapshot.yml`・`collector/jra_odds_snapshot.py`・既存データは変更しない（読み込みだけ）。

## 仕組み
- `collector/odds_t10.py`（標準ライブラリのみ）。開催日の出馬表から全レース（会場・番号・発走時刻）を取り、レースごとに `cutoff = 発走時刻 − 10分` を決める。
- cutoff より前に、そのレースの出馬表ページを一定間隔（既定: cutoff の24分前から3分おき、最後は cutoff の30秒前）で取得し、すべて候補として保存する。
- cutoff の5秒後に、候補から次の3条件を**すべて**満たす最新を1つ選び、1レース1行で保存する。
  1. `odds_time`（ページの「HH時MM分現在」）≦ cutoff
  2. 取得時刻 ≦ cutoff
  3. ページの発走時刻が、予定の発走時刻と同じ
  最新 = `odds_time` が最大（同じなら取得が後）。満たす候補がなければ `status: "missing"` と理由を書く（補間しない）。
- 発走後のページは結果ページでオッズがなく、候補にならない。最終人気は使わない。cutoff を過ぎてからの取得は行わない。
- 保存前に機械検証（`verify_selected`）: `odds_time_at ≦ cutoff_at`、取得時刻 ≦ cutoff、cutoff = 発走−10分、staleness = cutoff − odds_time ≧ 0、馬別オッズがあること。

## 保存先（odds-data ブランチ、新しいファイルだけ・追記のみ）
| ファイル | 内容 |
|---|---|
| `odds_t10/selected/<日付>.jsonl` | レースごとに1行。`status` ok / missing |
| `odds_t10/candidates/<日付>.jsonl` | 取得したすべての候補（会場・レース・odds_time ごとに1行） |
| `odds_t10/logs/<日付>.jsonl` | セッションの記録（対象数、取得回数、失敗、欠測、リクエスト数、問題点） |

`selected` の主な項目: `scheduled_post_time`, `cutoff_at`, `selected_snapshot_fetched_at`, `odds_time`（HH:MM）, `odds_time_at`（ISO）, `staleness_seconds`（cutoff − odds_time）, `source`（POST先とcname）, `github_run_id`, `session`, `n_candidates`, `candidate_odds_times`, 馬別 `horses`（馬番・馬名・単勝オッズ・人気・状態）。`missing` のときは `missing_reason`（例: `no_eligible_snapshot:no_candidates`, `session_started_after_cutoff`）。時刻はすべて JST（+09:00）付き。

## 運用（手動起動のみ。schedule はない）
1. 開催日の朝（最初の cutoff の約25分前まで）に、Actions の `odds-t10` を `session=am` で起動する（`dry_run=true` なら odds-data に書かない）。
2. 午前のうちに（最初の午後 cutoff の約25分前まで）、同じ日付で `session=pm` を起動する。
- 午前/午後の境は発走 12:30（`split_time`）。各ジョブの timeout は360分。コードの上限は345分で、超えたら未記録のレースを明示して終了コード1。
- 途中で失敗しても、同じ入力で再実行できる。記録済みのレースは取り直さず、二重に追記しない。cutoff を過ぎたレースは `session_started_after_cutoff` の欠測になる（後から補間しない）。
- 終了コード: 0 全レース記録・欠測なし／2 全レース記録・欠測あり／1 レース一覧を取得できない・一覧が空・未記録がある・保存（push）に失敗。
- 開催のない日、出馬表が未掲載の日は、成功扱いにならない（終了コード1）。

## 負荷と費用の見積もり
- 2026-10-31 の実ページ（東京・京都）: 24レース。午前 10レース（取得予定90回）、午後 14レース（126回）。3会場開催の日は36レース前後。
- 取得: 1レースあたり9回（24・21・…・3分前、30秒前）。1日 約216回（24レース）〜約324回（36レース）＋セッションごとの一覧取得（約3リクエスト）。HTTP間隔は0.5秒以上、失敗時は最大3回まで再試行（待ち時間を延ばす）。
- 保存: 候補は1日 約0.2〜0.4MB、選択は約0.1MB。
- Actions の実行時間（目安）: 午前 約3.2時間（09:15〜12:20）、午後 約4.2時間（12:05〜16:20）＝1開催日 約7.4 runner-hours（上限12時間以内）。リポジトリは公開なので、標準ランナーの利用時間は課金対象外。
- 鮮度: 取得間隔が3分なので、JRAの更新が頻繁なら staleness はおおむね数分以内になる見込み。実際の値は開催日の実測で確認する（`staleness_seconds`）。

## テスト
- `tests/test_odds_t10.py`（26件）: cutoff 境界（odds_time = cutoff は採用、+1分は不採用、取得が1秒後は不採用）、最新の選択、発走後ページ、欠測、遅れて開始、重複・再実行、途中失敗後の再実行、午前/午後の境、JST/UTC、桁の揃っていない発走時刻、一覧が空/取得失敗が成功にならない、出力先が `odds_t10/` だけであること、実ページ解析との結線。
- `odds-t10-check.yml`（このブランチ専用）: 実ページでレース一覧・取得予定の確認、開催のない日が成功扱いにならないこと、既存ファイルが無変更であること。
