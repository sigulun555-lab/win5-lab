# WIN5 Racecard Validation — 2026-11-08

Checked: 2026-11-08 13:15 JST
Source of truth: JRA official racecards and official WIN5 target-race listing.
Status: race identity and field-size validation only; this is not a forecast.

## Confirmed WIN5 legs

| Leg | JRA race | Race | Start (JST) | Conditions | Starters |
|---:|---|---|---:|---|---:|
| 1 | Tokyo 10R | 錦秋ステークス | 14:55 | Dirt 1600m, 3-win class, track officially listed as 良 in the detailed card | 11 |
| 2 | Kyoto 10R | 清水ステークス | 15:05 | Turf 1600m outer, 3-win class, 良 | 10 |
| 3 | Fukushima 11R | みちのくステークス | 15:20 | Turf 1200m, Open, 稍重 | 16 |
| 4 | Tokyo 11R | アルゼンチン共和国杯 (GII) | 15:30 | Turf 2500m, Open handicap, 良 | 18 |
| 5 | Kyoto 11R | みやこステークス (GIII) | 15:45 | Dirt 1800m, Open, 良 | 16 |

Total: 71 declared starters.

## Validation notes

- The JRA official WIN5 list identifies the five target race numbers for 2026-11-08 as Tokyo 10R, Kyoto 10R, Fukushima 11R, Tokyo 11R, Kyoto 11R.
- JRA's official weekly page separately identifies the Sunday feature races as the 2026-11-08 Argentine Republic Cup and Miyako Stakes. The Keio Hai Nisai Stakes and Muromachi Stakes are Saturday 2026-11-07 races, not the Sunday WIN5 legs.
- An earlier JRA-VAN search result surfaced Saturday's race names while showing the week selector for both dates. That result was not used to redefine the Sunday legs.
- The morning shortlist in this PR has the correct Sunday race identities. It remains provisional top-three-only: its percentages are subjective, not full-field probabilities, and are not normalized to 100%.
- No Claude predictions or market odds were used to make the GPT morning marks.
- No production settings or main-branch files were changed.

## Primary references

- JRA official WIN5 target list: https://www.jra.go.jp/kouza/win5/info/racelist.html
- JRA official 2026-11-08 race program: https://www.jra.go.jp/keiba/calendar2026/2026/11/1108.html
- JRA official racecards:
  - Tokyo 10R 錦秋S: https://app.jra.jp/JRADB/accessD.html?CNAME=sw01dde0105202605021020261108/3D
  - Kyoto 10R 清水S: https://app.jra.jp/JRADB/accessD.html?CNAME=sw01dde0108202605021020261108/55
  - Fukushima 11R みちのくS: https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01dde0103202603021120261108/FC
  - Tokyo 11R アルゼンチン共和国杯: https://app.jra.jp/JRADB/accessD.html?CNAME=sw01dde0105202605021120261108/F2
  - Kyoto 11R みやこS: https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01dde0108202605021120261108/0A
