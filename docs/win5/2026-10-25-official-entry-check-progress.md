# WIN5 2026-10-25 official entry check — progress

Checked against indexed JRA official race-card pages on 2026-10-25. This is an entry-list cross-check, not a complete independent prediction.

| WIN5 leg | Race | Start (JST) | Official source | Status |
|---:|---|---:|---|---|
| 1 | Tokyo 10R 山中湖特別 | 14:45 | https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0105202604091020261025%2FA6 | official page found; full field data not independently extracted into CSV |
| 2 | Kyoto 10R カノープスステークス | 15:00 | https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0108202604091020261025%2F84 | official page found; 15 entries indicated by prior market CSV; full field data not independently extracted into CSV |
| 3 | Niigata 11R ルミエールオータムダッシュ | 15:10 | https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0104202604041120261025%2FD2 | official page found; 17 entries and recent-form rows visible in indexed page |
| 4 | Tokyo 11R 神無月ステークス | 15:20 | https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0105202604091120261025%2F5B | official page found; 16 entries indicated by prior market CSV; full field data not independently extracted into CSV |
| 5 | Kyoto 11R 菊花賞 | 15:40 | https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0108202604091120261025%2F39 | official page found; 18 entries; jockeys and 57.0 kg weights visible in indexed page |

## Data integrity notes
- This check confirms official JRA race-card pages exist and confirms the five race identities and start times.
- Search-indexed pages expose some or all of the fields, but not a stable complete machine-readable extraction for all 75 runners in this run.
- Existing market-probability files are not evidence of an independent GPT forecast.
- Do not fill missing runner features with guesses.
- The large horse-history JSON at data/horse_history/2026-10-25.json exists in GitHub, but the GitHub file-fetch connector returned an empty body for both UTF-8 and base64 retrieval. It must be repaired/re-exported before model features can be computed reproducibly.

## Next step required before a defensible independent probability file
Re-export the history JSON as line-delimited JSON or per-race CSVs, fetch the complete official runner fields (horse number, name, jockey, weight, last four runs, scratches), then define and run a reproducible scoring method without Claude's picks. Validate that each race's unrounded probabilities sum to 100%. Until then, any numeric independent probability would be speculative and should not be presented as finished.
