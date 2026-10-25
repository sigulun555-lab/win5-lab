# WIN5履歴のみモデル：結果評価の実行手順

## 入力

- 予測スナップショット（結果を見て変更しない）：
  `data/win5_joint/2026-10-25/gpt-exploratory-history-only-probabilities.csv`
- 結果CSVテンプレート：
  `data/backtest/win5-results-template.csv`

テンプレートは空欄のままなので、そのまま評価には使えない。JRA公式結果を確認してから、各行の `winner_no` と `winner_name`、確認時刻を入力して保存する。

## 実行

```bash
python scripts/evaluate_win5_history_only.py \
  --predictions data/win5_joint/2026-10-25/gpt-exploratory-history-only-probabilities.csv \
  --results data/backtest/win5-results-template.csv \
  --output reports/win5-history-only-evaluation-2026-10-25.md
```

## 指標

- Top-1：各レースでモデル確率1位の馬が勝った数（5レース中）。
- Top-3：勝ち馬がモデル確率上位3頭に入ったレース数。
- 勝ち馬平均Log loss：勝ち馬に割り当てた確率の評価。低いほど良い。
- Multiclass Brier：全出走馬の確率誤差。低いほど良い。

小標本での数値は参考値であり、モデル優位性を証明しない。結果を見て予測を変更することは禁止。市場との比較には同じ時刻の市場オッズが必要。
