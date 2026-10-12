# Phase 7.4｜Hierarchical Sensitivity

Sensitivity使用與primary相同的2,782站與report-reference k；沒有執行額外組合。Cophenetic correlation只作secondary diagnostic，不用來反向選擇linkage。

## Weekday k=5

| Variant | ARI vs Ward primary | NMI vs Ward primary | Cophenetic | Cluster sizes |
| --- | ---: | ---: | ---: | --- |
| StandardScaler＋Complete | 0.010032 | 0.035716 | 0.906813 | 2,770／3／4／1／4 |
| StandardScaler＋Average | 0.016833 | 0.058219 | 0.943948 | 2,762／17／1／1／1 |
| No scaling＋Ward | 0.514025 | 0.484577 | 0.863388 | 89／324／458／176／1,735 |

## Holiday k=4

| Variant | ARI vs Ward primary | NMI vs Ward primary | Cophenetic | Cluster sizes |
| --- | ---: | ---: | ---: | --- |
| StandardScaler＋Complete | 0.038628 | 0.071157 | 0.924888 | 2,767／9／1／5 |
| StandardScaler＋Average | 0.018146 | 0.036868 | 0.953797 | 2,775／5／1／1 |
| No scaling＋Ward | 0.620627 | 0.473244 | 0.781442 | 177／314／1,963／328 |

Complete／average與Ward primary的partition差異極大；no-scaling亦有實質差異，顯示結果對linkage與feature scaling敏感。不同scaling下的merge distances不作同尺度objective比較；較高cophenetic correlation也不代表應取代report-specified Ward.D2。

完整數值與hash見[`hierarchical-sensitivity-summary.json`](hierarchical-sensitivity-summary.json)。
