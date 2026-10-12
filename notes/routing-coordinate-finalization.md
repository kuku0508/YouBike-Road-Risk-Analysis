# Phase 8.0C｜Routing coordinate finalization

## Source precedence

1. 能覆蓋routing month的verified direct historical evidence。
2. `routing-coordinate-assumption-v1`接受的legacy monthly coordinate。
3. 既有accepted temporally bracketed coordinate。
4. Unresolved。

本次沒有可覆蓋core期間的verified direct evidence。Phase 8.0A五個temporally bracketed stations也都有legacy coordinate，故依precedence使用legacy source；沒有current-only fallback。

## Stable coordinates and conflict handling

2,769個identity-mapped IDs中，2,756個至少有一筆有效座標，且每站所有legacy months只有一組exact coordinate，因此final artifact每站一列。沒有觀察到accepted source內的monthly coordinate change，故不產生coordinate-era artifact，routing unit維持unique directed OD pair；此結果不能證明現實中沒有relocation。

31個Phase 8.0A conflicts全部保留：28個有legacy coordinate，進final artifact且`coordinate_conflict=true`；3個legacy coordinate全缺，留在gap artifact。Legacy coordinate不會靜默覆寫evidence ledger內的2024／2026座標；三者仍可在既有conflict timeline追溯。

## Immutable artifacts

| Artifact | Rows | SHA-256 |
|---|---:|---|
| `routing_station_coordinates_2023_2024.parquet` | 2,756 | `8e5b4bbe3511b0145234f209768f0eec0f766e9121716ae510170724dab1ad06` |
| `core_routing_coordinate_gap.csv` | 26 | `a0e93f581a9610f7fb17be25dbf11fff90880dbeca740f146817a1c96bf33c20` |
| `unroutable_od_due_to_coordinate_gap.parquet` | 23,096 | `feab37705c95204621eb8eb3c46a791e00ab157d92df032b8909c41acab4e6a6` |

Final station-ID fingerprint為`1cf8fa00388dd9b89b16eb8ee895a9bb5913f62344d69791095d591b9eafc820`；coordinate fingerprint為`b744b692ba020cd13293f5429f8d6e43400d70737560f1d921ccb0309281bd02`。大型artifact依`.gitignore`留在本機，不commit。

Contract升為`road-routing-contract-v1.1`：routing unit沒有改成era，但coordinate acceptance、artifact hash及cache identity已變更。Phase 8.1不得重新查current API決定座標。

## Validation

- Phase 8.0C專屬測試：24/24 passed。
- 完整regression suite：279/279 passed（269.133秒）。
- Source／mapping hash gates、JSON parsing、Python syntax、artifact SHA-256、Git ignore與row／edge／trip conservation均通過。
- `full_routing_executed=false`；沒有呼叫BRouter full routing。
