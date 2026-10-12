# Phase 6.1｜Louvain sensitivity and stability

所有variant都使用相同2,782-node universe。ARI與NMI直接比較station membership，不比較任意numeric community IDs。

## Multi-seed stability

| Seed | Communities | Q | ARI vs seed 42 | NMI vs seed 42 |
| ---: | ---: | ---: | ---: | ---: |
| 42 primary | 8 | 0.634430 | 1.000000 | 1.000000 |
| 7 | 10 | 0.636958 | 0.552628 | 0.721935 |
| 19 | 9 | 0.640464 | 0.609155 | 0.758193 |
| 73 | 9 | 0.639640 | 0.631930 | 0.758982 |

Q只在0.63443–0.64046間變動，但community count為8–10，ARI為0.553–0.632。故modularity相對穩定，station membership只有中度穩定；不能因Q接近就宣稱partition穩定。Seed 42仍是預先鎖定的primary，不因其他seed Q略高而更換。

## Projection and self-loop sensitivity

| Variant | Communities | Q | ARI | NMI |
| --- | ---: | ---: | ---: | ---: |
| Sum primary | 8 | 0.634430 | 1.000000 | 1.000000 |
| Max projection | 9 | 0.619135 | 0.869371 | 0.873213 |
| Unweighted projection | 3 | 0.190292 | 0.228749 | 0.392483 |
| Retain self-loops | 10 | 0.653074 | 0.674302 | 0.805999 |

Max projection與primary仍高度相近；移除flow weight後結果大幅改變，顯示community structure高度依賴trip strength。保留6,023,568 self-loop trips亦改變群數與membership，支持將self-loop policy視為實質方法選擇。

## Resolution sensitivity

| Resolution | Communities | Q under same gamma | ARI | NMI |
| ---: | ---: | ---: | ---: | ---: |
| 0.5 | 5 | 0.732985 | 0.554512 | 0.717954 |
| 1.0 primary | 8 | 0.634430 | 1.000000 | 1.000000 |
| 1.5 | 12 | 0.579359 | 0.619002 | 0.759087 |

Resolution越高得到較多communities，符合契約語意。不同gamma下的Q採各自相同resolution定義，不能把數值大小直接當成跨resolution模型優劣；本次也沒有因resolution 1.5得到接近11群而把它升格為primary。

## Analytical implication

Primary partition可重現，但對random seed、self-loop與weighting存在實質敏感度。這不是execution blocker，卻是後續描述community或比較群組時必須保留的methodological caveat。完整machine-readable結果見[`louvain-sensitivity-summary.json`](louvain-sensitivity-summary.json)。
