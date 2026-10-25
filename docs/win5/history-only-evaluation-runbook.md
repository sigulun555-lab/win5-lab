# WIN5履歴のみモデル：結果評価の実行手順

## 入力

- 予測スナップショット（結果を見て変更しない）：
  `data/win5_joint/2026-10-25/gpt-exploratory-history-only-probabilities.csv`
- 結果CSVテンプレート：
  `data/backtest/win5-results-template.csv`

テンプレートは空欄のままなので、そのまま評価には使えない。JRA公式結果を確認してから、各行の `winner_no` と `winner_name`、確認時刻を入力して保存する。

## 結果CSVの作り方（推奨：公式ページから自動取得）

```bash
python collector/fetch_win5_results.py --date 2026-10-25 \
  --output data/win5_joint/2026-10-25/win5_official_results.csv
```

- 公式のWIN5対象レース一覧の並びで5レースを決め、開催日結果ページから1着馬を取り出す。
- 5レースすべてで1着がちょうど1頭のときだけ書き出す。未確定・同着・欠けがあるときは何も書かず終了コード2。
- `scratched_nos` に、結果ページで「取消」「除外」と表示された馬番が入る。評価時のみ除外して確率を再正規化する（予想ファイルは変更しない）。
- 動作確認済み：2026-10-12／10-17／10-18／10-24 の5レースの1着馬が、保存済みの公式結果と一致。

## 実行

```bash
python scripts/evaluate_win5_history_only.py \
  --predictions data/win5_joint/2026-10-25/gpt-exploratory-history-only-probabilities.csv \
  --results data/backtest/win5-results-template.csv \
  --output reports/win5-history-only-evaluation-2026-10-25.md
```

他の確率列も同じコードで評価できる（例：Claudeの予想 `--probability-column claude_estimated_win_probability_pct`）。
数字は `1`、`01`、`1.00000` のどれでもよい（整数として読む）。

## 指標

- Top-1：各レースでモデル確率1位の馬が勝った数（5レース中）。
- Top-3：勝ち馬がモデル確率上位3頭に入ったレース数。
- 勝ち馬平均Log loss：勝ち馬に割り当てた確率の評価。低いほど良い。
- Multiclass Brier：全出走馬の確率誤差。低いほど良い。

- Brierの定義が3通りある（全頭プール／レース平均／レース合計）。レポートに3つとも出し、1/頭数の基準も併記する。
  Brier/馬は頭数が多いほど小さくなるため、日をまたぐ比較は基準との差で見る。
- 勝ち馬確率が0のときは、`--log-loss-floor`（既定1e-15）で下限をかけ、警告を出す。
- Top-1／Top-3の同点は馬番の小さい順で決め、警告を出す。

小標本での数値は参考値であり、モデル優位性を証明しない。結果を見て予測を変更することは禁止。市場との比較には同じ時刻の市場オッズが必要。
