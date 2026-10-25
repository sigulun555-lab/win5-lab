# B2 preliminary benchmark report — 2026-10-25

## Status and interpretation

This is a **preliminary retrospective diagnostic**, not the registered full B2 test and not an adoption decision. Popularity is the final popularity parsed from result pages; it must not be interpreted as the popularity available before the betting deadline.

Input prepared dataset SHA256: `5c4cf787dce49d5c022351b8cb8f95ed1eea86e624f0724e3ea605d38abb6569`

## Split and results

- Training period: 2025-10-01 to 2026-07-31; 2,850 races.
- Test period: 2026-08-01 to 2026-10-25; 864 races.
- Popularity-only mean log likelihood: -1.9912279979406444.
- Popularity + current history score mean log likelihood: -1.9914394858158861.
- Difference (combined minus popularity only): -0.00021148787524195238.
- Race bootstrap 95% CI: [-0.0022924124730757827, +0.0018625147131230689].

Higher log likelihood is better. The point estimate is slightly worse, and the confidence interval crosses zero. This does **not** establish an improvement.

## Limitations

1. This is not B2 with class interaction, local-to-JRA adjustment, JRA-run shrinkage, or rating.
2. No nested rolling-origin selection of L2/k/tau was run.
3. Final popularity is a retrospective benchmark, not pre-off operational input.
4. This one split is not enough to meet the preregistered adoption criteria.
5. The current dataset preparation has 3 multi-winner races labelled fractionally. The preregistered protocol's exact one-winner filter differs; the discrepancy must be reconciled before formal evaluation.

## Next work

Implement the registered candidate sequence with fold-specific feature construction and nested chronological validation; compare B0-original, B0-refit, popularity-only, and each candidate using identical eligible races. Preserve the original B files. Do not adopt B2 unless all preregistered criteria pass.
