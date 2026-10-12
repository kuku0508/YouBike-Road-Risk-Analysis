# Phase 7.3｜2023–2024 Hourly SNA Feature Reconstruction

## Outcome

**HOURLY SNA FEATURES: COMPLETE**

本階段依分析者明確決策，以2023/01–2024/12重建平日／假日各24個逐時network，並產生兩份2,782站×72 features矩陣。沒有StandardScaler、Ward clustering、cut或dendrogram。

## Period and source boundaries

- **Report-specified**：原報告p.7與p.27仍寫2022–2024；此證據沒有被覆寫。
- **Analyst reconstruction decision**：本次將該期間差異視為報告內部不一致／筆誤，沿用核心network period 2023–2024；因此結果不能宣稱是原報告期間的完全重現。
- **Observed in input**：Phase 4.0 `od-inclusion-policy-v1`下共有91,138,763筆core eligible trips。
- **Authoritative calendar**：只使用分析者提供的`2020_2025假日.fst`之`IsHoliday`。

## Conservation and hourly network QA

全部eligible records依`borrow_date` exact join calendar，再依cleaned `borrow_time`中的整點hour分到唯一bucket；timestamp日期另與`borrow_date`逐筆核對。Repeated identical records全部保留。

| Day type | Dates | Trips | Hourly trip range | Hourly edge range | Active-node range | Self-loop trips total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Weekday | 498 | 66,096,385 | 115,045–6,501,476 | 45,788–416,054 | 2,059–2,538 | 4,013,929 |
| Holiday | 233 | 25,042,378 | 102,283–2,087,624 | 51,523–286,213 | 2,075–2,495 | 2,009,639 |

`66,096,385 + 25,042,378 = 91,138,763`，48 buckets守恆。個別hour可能只有490–492個weekday source dates或232–233個holiday source dates，代表該日型別某些日期在該hour沒有eligible trip，不是calendar缺日。

## Fixed station universe and inactive semantics

報告未指定逐時station universe。**Reconstruction decision**：所有48個graph固定加入Phase 4.1 core primary OD union的2,782個canonical station IDs，ordering固定為`station_id`升冪。

- Betweenness：full-node directed graph；inactive isolates自然為0。
- Eigenvector：移除self-loop後在有edge的active-node子圖計算；固定universe中的isolates明確填0，active values維持unit Euclidean norm。若power iteration不收斂則fail closed，沒有fallback。
- PageRank：在包含全部2,782 nodes的weighted directed graph計算；isolates／dangling nodes保留uniform teleportation mass，因此inactive station的PageRank不必為0。

## Metric contract

| Metric | Contract | Execution result |
| --- | --- | --- |
| Betweenness | directed、unweighted、normalized、endpoints=False、self-loop excluded、exact | 48/48完成；無近似或抽樣 |
| Eigenvector | directed left/predecessor、unweighted、self-loop excluded、max_iter=1000、tol=1e-9 | 48/48收斂 |
| PageRank | directed、`trip_count` weighted、alpha=0.85、uniform personalization／dangling、self-loop retained、max_iter=1000、tol=1e-9 | 48/48 sum≈1 |

Exact betweenness使用python-igraph 0.11.9的編譯型Brandes實作，raw directed count除以`(n-1)(n-2)`以符合NetworkX directed normalized語意。Synthetic test及兩個真實gate buckets與NetworkX逐站比較的最大絕對差均為0.0；這是exact backend替換，不是approximation。

## Outputs and numerical validation

| Matrix | Shape（stations×features） | SHA-256 | Bytes |
| --- | --- | --- | ---: |
| Weekday | 2,782×72 | `ed00378e3ce489b7c80bbc9a7a22198dffa7dc1c6b9bbd18804074963d987054` | 1,419,558 |
| Holiday | 2,782×72 | `b232620f2ee14ff436439c715efaf89794e9ddbf7af8c8323f0814e44a2685d8` | 1,416,774 |

兩份Parquet另含`station_id`、`station_name`、`city`三個metadata columns；72個feature columns精確為`betweenness_h00..h23`、`eigenvector_h00..h23`、`pagerank_h00..h23`。全部無NaN／Inf，station ID唯一且排序一致，沒有套用scaling。

48 buckets逐一通過Betweenness range、Eigenvector non-negative／norm／isolate-zero、PageRank non-negative／sum-to-one驗證。完整hour-level數值、hash、convergence與graph fingerprint見[`hourly-sna-feature-manifest.json`](hourly-sna-feature-manifest.json)。大型OD、metric checkpoints與matrix Parquet保留於Git忽略的`data/processed/network/hourly_2023_2024/`。

## Runtime and resumability

- Small gate：977.18秒（包含首次全量分桶）；平日08時／假日14時的NetworkX exact betweenness分別104.15／97.85秒。
- Full execution：1,042.18秒，包含最後一次全量分桶、48 OD checkpoint落盤及48×3 metrics。
- 48套metrics累計：Betweenness 69.59秒、Eigenvector 31.81秒、PageRank 55.45秒。
- Checkpoint identity包含cleaned partition hashes、calendar hash、OD policy、contract、day type、hour、graph fingerprint、metric、library version與output hash；不是只看檔案存在就skip。

## Readiness

兩份未標準化72-feature matrices已具備Phase 7.4輸入條件。但它們是分析者選定的2023–2024 reconstruction variant，不可稱為原報告明載2022–2024期間的exact reproduction。
