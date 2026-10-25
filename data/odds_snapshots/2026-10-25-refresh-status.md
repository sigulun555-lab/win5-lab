# WIN5 odds refresh status — 2026-10-25

## Completed
- Retrieved the JRA official race-card odds shown on the five WIN5 race pages.
- Calculated inverse-odds market probabilities for all 75 listed runners (9 + 15 + 17 + 16 + 18).
- Normalized each race independently; each race totals 100% before CSV rounding.
- Saved the calculations to `data/odds_snapshots/2026-10-25-full-field-market-probabilities.csv`.
- Re-fetched the saved CSV from GitHub and verified 75 data rows and near-100% sums after rounding.

## Source pages
1. Tokyo 10R Yamanakako Tokubetsu: https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01ddd0105202604091020261025/6D
2. Kyoto 10R Canopus Stakes: https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01ddd0108202604091020261025/4B
3. Niigata 11R Lumiere Autumn Dash: https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01dde0104202604041120261025/99
4. Tokyo 11R Kannazuki Stakes: https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01ddd0105202604091120261025/22
5. Kyoto 11R Kikuka-sho: https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01dde0108202604091120261025/C6

The JRA page for Kyoto 11R explicitly says odds are current as of 13:46. The other four pages' exact timestamp was not independently exposed in the text extraction; treat their values as the retrieved JRA page snapshot, not a verified synchronized 13:46 snapshot.

## Not completed — model prediction refresh
The repository's `win5_gpt_primary.csv` on `main` is dated 2026-10-24, and the expected 2026-10-25 GPT/Claude joint CSV paths were not found on either `main` or `odds-data`. Therefore no GPT model probabilities or model ◎○▲ were overwritten or invented. Market probabilities in the CSV are explicitly marked market-only and must not be interpreted as GPT predictions.

## Required next step
Locate or generate the independently computed 2026-10-25 GPT full-field probability file, compare its rankings against the refreshed market probabilities, record any justified changes separately, and then push the prediction refresh. Do not change model win probabilities solely to follow market odds without a validated correction rule.
