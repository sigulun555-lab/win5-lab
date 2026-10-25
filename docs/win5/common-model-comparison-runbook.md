# 共通WIN5モデル比較スクリプト

scripts/evaluate_win5_model_comparison.py は、GPT・Claude・市場確率を同じ評価コード・同じ結果CSVで採点するための共通ランナーです。

## 実行例（2026-10-25）

JRA公式結果が5レースすべて確定したあとに実行してください。結果ファイルは collector/fetch_win5_results.py で取得し、予測ファイルは変更しません。

```bash
python collector/fetch_win5_results.py \
  --date 2026-10-25 \
  --output data/win5_joint/2026-10-25/win5_official_results.csv

python scripts/evaluate_win5_model_comparison.py \
  --date 2026-10-25 \
  --results data/win5_joint/2026-10-25/win5_official_results.csv \
  --model "GPT-history|data/win5_joint/2026-10-25/gpt-exploratory-history-only-probabilities.csv|gpt_exploratory_win_probability_pct|leg|horse_number" \
  --model "Claude-morning-model-column|data/win5_joint/2026-10-25/win5_claude_morning.csv|model_prob_pct|win5_order|horse_no" \
  --model "Claude-morning-market-column|data/win5_joint/2026-10-25/win5_claude_morning.csv|market_prob_pct|win5_order|horse_no" \
  --output reports/win5-model-comparison-2026-10-25.json
```

上記のClaude朝CSVは、記録上 model_prob_pct が market_prob_pct とほぼ同じで、公式単勝オッズの逆数を正規化した市場確率を丸めた値です。独立したClaude予測として解釈してはいけません。そのため例では「Claude列」と「市場列」を分けて並べ、差がほぼないことも確認できるようにしています。GPTの履歴のみ探索モデルとは情報源が異なるため、同じ時点比較とはみなさず、オッズ時刻と予測時刻を別途確認してください。

## 出力指標

- Top-1 的中数、Top-3 内率
- 勝ち馬の平均Log loss
- Multiclass Brier（レース合計の平均）
- Brier / 馬（レース平均・全頭プール）
- 各指標の全頭同確率（1/頭数）基準
- レース別の勝ち馬確率・Top-1・頭数・取消除外処理

## 注意

- 公式結果の5レグが揃わなければ評価を開始しません。
- 取消・除外馬は結果CSVの scratched_nos を使って評価時だけ除外し、残りの確率を再正規化します。元の予測CSVは変更しません。
- 確率列は百分率（0〜100）を想定します。
- multiclass_brier_per_horse_pooled は頭数の構成で変わります。開催をまたいだ比較では、レース合計のBrierと全頭同確率基準も併せて確認してください。
- 5レースだけでモデル優位性を断定しません。発走前保存の時刻が証明できない予測は正式なバックテストから除外します。
