# Phase 4.0 — OD Inclusion Policy

## 結論

Primary OD eligibility 定義為：

> 非quarantine record，origin與destination皆存在，且兩端都能透過已鎖定的cleaned evidence或exact metadata evidence解析成唯一canonical station ID。

Primary OD node key只使用`station_id`；canonical station name只作display label。Primary boundary是**full observed uniquely identifiable station universe**，不限臺北市；已確認的新北站與跨市旅次納入primary network，city是node attribute，不是inclusion filter。

Machine-readable contract：[`config/od_inclusion_policy.yaml`](../config/od_inclusion_policy.yaml)。檔案內容使用JSON-compatible YAML，可直接以JSON parser讀取。Impact evidence：[`od-inclusion-impact.json`](od-inclusion-impact.json)。

## Evidence labels

- **Report-specified**：原報告把站點當節點、起站至迄站旅次量當有向邊權重；報告研究主題是臺北市，但沒有留下可執行的市界filter、station identity或cross-city handling規則。
- **Observed in raw data**：2023/01–2025/03共109,713,899 records；Phase 3.7產生109,713,772 accepted與127 quarantine。Raw data本身沒有station ID，且既有cleaned Parquet只為approved repairs保存ID；New Taipei `not_an_error`與正常站名的ID要由既有exact evidence解析。
- **Evidence-supported reconstruction**：鎖定的current snapshot、2024/05/31 snapshot與station-universe evidence可以為1,817個exact station names與1,311個New Taipei raw Base64 values提供唯一ID；本次未觀察到exact name對應多ID的collision。
- **Reconstruction decision**：市界、station ID requirement、ambiguous handling、cross-city inclusion、historical operation與exclusion precedence均是本階段方法決策，不冒充原報告做法。

## Endpoint taxonomy

| Endpoint status | Primary OD | Identity key | 處理 |
|---|---|---|---|
| `eligible_unique_id` | 是 | canonical station ID | 允許進primary |
| `eligible_valid_name_no_id` | 否 | sensitivity才可用namespaced Base64 key | 保留，不強塞ID |
| `ineligible_missing` | 否 | 無 | 保留於非OD QA |
| `ineligible_candidate_only` | 否 | 不採用candidate ID | 可於sensitivity用raw pseudo-node |
| `ineligible_ambiguous` | 否 | 無唯一ID | 只可廣義sensitivity，不選candidate |
| `ineligible_unresolved` | 否 | 無 | 只可廣義sensitivity／QA |
| `ineligible_name_collision` | 否 | 同名多ID | fail closed；本次計數0 |
| `ineligible_quarantine` | 否 | unsafe | 只保留於quarantine QA |

### Status-specific rules

- `approved_repair`：canonical name、ID、city與provenance完整時，endpoint為eligible。OD key只用ID。
- `unchanged_no_rule`：不是錯誤狀態。非空、serialization-safe的exact station name若在鎖定metadata中只對應一個ID，則primary eligible；無ID時不進primary，只保留於sensitivity。
- `not_an_error`：若exact raw Base64命中station-universe evidence且有唯一ID，則eligible；新北市不是排除理由。
- `candidate_only`：證據不足以approved repair，不強制套用candidate ID，不進primary。
- `ambiguous`：若當作一個pseudo-node，會將多個真實站點錯誤合併，偏誤OD weights、weighted degree、betweenness、PageRank與Louvain；因此排除primary。
- `unresolved`：沒有可靠identity，排除primary；raw-name pseudo-node只能用於broad sensitivity。

## Trip taxonomy與precedence

Primary trip status：

- `od_eligible`：兩端皆`eligible_unique_id`。
- `quarantined`：execution／serialization safety未通過。
- `missing_endpoint`：任一端缺失。
- `identity_ambiguous`：任一端ambiguous。
- `identity_unresolved`：任一端unresolved。
- `candidate_only`：任一端只有candidate。
- `name_collision`：任一exact name對應多ID。
- `no_unique_station_id`：前述問題皆無，但至少一端沒有唯一ID。

Primary exclusion reason precedence：

1. `quarantined`
2. `missing_endpoint`
3. `identity_ambiguous`
4. `identity_unresolved`
5. `candidate_only`
6. `name_collision`
7. `no_unique_station_id`
8. `od_eligible`

Precedence只用來產生互斥主理由；所有secondary flags仍保留，不會因單一reason而遺失overlap資訊。

## Full-period impact

| Precedence-resolved outcome | Records | Full period % |
|---|---:|---:|
| Primary `od_eligible` | 108,077,420 | 98.508412% |
| `identity_ambiguous` | 926,108 | 0.844112% |
| `no_unique_station_id` | 705,001 | 0.642581% |
| `candidate_only` | 4,297 | 0.003917% |
| `missing_endpoint` | 667 | 0.000608% |
| `identity_unresolved` | 279 | 0.000254% |
| `quarantined` | 127 | 0.000116% |
| `name_collision` | 0 | 0% |

合計109,713,899 records，與full-period cleaning manifest守恆。Primary exclusion union為1,636,479（1.491588%）。Individual flags不可直接相加：例如ambiguous 926,114 trips與valid-name-no-ID 706,230 trips均和其他flags有overlap；完整cross-count見impact JSON。

## Cross-city decision

Primary network不限Taipei-only。ID-required primary中：

- Taipei → Taipei：106,302,441。
- Taipei → New Taipei：1,774,979。
- New Taipei → Taipei：0。
- New Taipei → New Taipei：0。

這是既有evidence的結果：New Taipei站在本資料主要以destination-only出現。不因city=New Taipei排除，因為它們已由exact official station-universe evidence唯一辨識；日後可另做Taipei-only sensitivity，但不把它改為primary。

## Historical operational status

Metadata exact match只證明identity/name evidence，不證明站點在2023–2025每月的官方營運區間。本policy將raw trip在當月出現解釋為「source recorded this endpoint at this trip time」，與唯一identity合用時足以進入reconstructed OD；但不將它寫成官方`valid_from/valid_to`或確定營運狀態。

這項決策避免因缺少完整historical station master而排除絕大多數真實旅次，同時不把current metadata誤寫成歷史營運證明。

## Repeated rows與duration

- Repeated identical records全數計入OD weight；沒有trip ID且timestamp只到整點，沒有證據支持deduplication。
- Duration不影響OD eligibility。`duration=0`、`>24h`、`>7d`與cross-midnight均不在Phase 4.0排除；routing或accident analysis若需要過濾，必須另立方法決策。

## Sensitivity plan（只設計，未建網）

| Variant | Estimated retained | % | Difference from primary | Main risk |
|---|---:|---:|---:|---|
| Primary ID-required full universe | 108,077,420 | 98.508412% | — | lowest identity ambiguity |
| Hybrid safe-name fallback | 108,782,421 | 99.150994% | +705,001 | rename fragmentation / same-name collision |
| Hybrid + candidate pseudo-nodes | 108,786,718 | 99.154910% | +709,298 | candidate may imply false identity |
| Broad raw pseudo-nodes | 109,713,105 | 99.999276% | +1,635,685 | false merge, fragmentation, centrality/community bias |
| Taipei-only ID-required | 106,302,441 | 96.890587% | -1,774,979 | removes valid cross-city flow |

未執行任何variant network。Phase 4.1若執行，builder必須讀取policy config，不可將決策重新hard-code在aggregation程式。

## Risks and rationale

- **Raw-name pseudo-node**：可以保留更多records，但改名會分裂node，同名會誤合併，後續centrality與community detection會被系統性偏誤。
- **Ambiguous as one node**：把多個真實站點聚成一個虛構hub，可能膨脹weighted degree、betweenness與PageRank，並拉動Louvain community boundary。
- **ID-only exclusion**：排除0.642581%「名稱安全但無唯一ID」records，可能低估部分流量；因此保留hybrid sensitivity設計，但不放寬primary。
- **City filtering**：Taipei-only會移除1,774,979筆已唯一辨識的跨市records，把真實市界流動當作dirty data；因此不採用。

## Implementation boundary

Phase 4.0只定義policy與profile impact。`src/profile_od_eligibility.py`只讀取cleaned partitions、quarantine、station metadata與manifest，並以hash gate確認evidence版本；它不產生eligible trip dataset，不對origin/destination groupby，不計算edge weight。

Phase 4.1的最小任務才是：讀取finalized policy，建立第一版primary OD aggregation，同時輸出exclusion audit；不自動進入SNA或其他分析。
