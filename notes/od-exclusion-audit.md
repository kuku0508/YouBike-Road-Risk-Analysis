# Phase 4.1 — OD Exclusion Audit

本audit重用Phase 4.0 finalized precedence，不重新分類records。Machine-readable evidence見[`od-exclusion-audit.json`](od-exclusion-audit.json)。

| Precedence | Category | Records | Total input % | Status |
|---:|---|---:|---:|---|
| 1 | quarantine | 127 | 0.000116% | excluded from primary OD |
| 2 | missing endpoint | 667 | 0.000608% | excluded from primary OD |
| 3 | ambiguous identity | 926,108 | 0.844112% | excluded from primary OD |
| 4 | unresolved identity | 279 | 0.000254% | excluded from primary OD |
| 5 | candidate-only | 4,297 | 0.003917% | excluded from primary OD |
| 6 | name collision | 0 | 0% | excluded from primary OD |
| 7 | no unique station ID | 705,001 | 0.642581% | excluded from primary OD |

Excluded union為1,636,479（1.491588%）。加上eligible 108,077,420後等於full input 109,713,899。

每筆record只有一個precedence-resolved primary reason；secondary flags與overlap matrix仍保留在JSON。Individual flags不可相加當作excluded union。排除只是primary OD identity contract的結果，不等於原始旅次錯誤，也沒有刪除或修復來源records。

