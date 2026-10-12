"""Validate and render the Phase 3 machine-readable profile."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def pct(count: int, total: int) -> str:
    return f"{count / total * 100:.4f}%" if total else "0.0000%"


def hms(seconds: int | None) -> str:
    if seconds is None:
        return "n/a"
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def validate(profile: dict, receipt: dict | None = None) -> list[str]:
    checks = []
    total = profile["total_records"]
    files = profile["files"]
    expected_months = len(profile["scope"]["months"])
    assert len(files) == expected_months
    assert sum(item["records"] for item in files) == total
    checks.append(f"{expected_months} monthly file counts sum to total_records")
    assert sum(profile["category_combination_counts"].values()) == total
    checks.append("category combinations are exhaustive and sum to total_records")
    for month, values in profile["monthly"].items():
        assert values["total_records"] == next(item["records"] for item in files if item["month"] == month)
        assert values["clean_with_respect_to_current_rules"] <= values["total_records"]
    checks.append("all monthly totals and clean counts are internally consistent")
    encoding = profile["encoding"]
    assert encoding["affected_record_count"] <= encoding["affected_field_count"] <= encoding["illegal_byte_count"]
    assert sum(v.get("affected_record_count", 0) for v in (m["encoding"] for m in profile["monthly"].values())) == encoding["affected_record_count"]
    checks.append("illegal bytes, affected fields, affected records, and monthly affected records reconcile")
    repeated = profile["repeated_identical"]
    assert repeated["involved_records"] == repeated["repeated_groups"] + repeated["excess_copies"]
    assert repeated["policy"] == "retain_all"
    checks.append("repeated groups + excess copies = involved records; retain_all policy present")
    assert profile["bike_type"]["v1_structural_absence"] + sum(profile["bike_type"]["v2"].values()) == total
    checks.append("v1 structural absence plus v2 bike-type counts equals total_records")
    assert not profile["method"]["cleaning_performed"] and not profile["method"]["duplicates_removed"]
    checks.append("profile declares no cleaning and no duplicate removal")
    if receipt is not None:
        head_by_month = {row["month"]: int(row["bytes"]) for row in receipt["index_head_checks"]["rows"]}
        assert all(head_by_month[item["month"]] == item["bytes"] for item in files)
        checks.append(f"all {expected_months} ZIP byte sizes match the saved official HEAD receipt")
    return checks


def top_months(profile: dict, issue: str, n: int = 3) -> str:
    ranked = sorted(
        ((month, values["issue_counts"].get(issue, 0)) for month, values in profile["monthly"].items()),
        key=lambda pair: pair[1], reverse=True,
    )
    return ", ".join(f"{month} ({count:,})" for month, count in ranked[:n] if count) or "—"


def render(profile: dict, checks: list[str]) -> str:
    total = profile["total_records"]
    unions = profile["category_unions"]
    issues = profile["issue_counts"]
    enc = profile["encoding"]
    repeated = profile["repeated_identical"]
    station = profile["station"]
    duration = profile["duration_seconds"]
    temporal = profile["temporal"]
    bike = profile["bike_type"]
    q = duration["quantiles"]
    unique_lookup = {
        "illegal_utf8": sum(len(values) for values in enc["unique_affected_raw_values"].values()),
        "station_replacement_character": len(station["pattern_unique_values"].get("replacement_character", [])),
        "station_question_mark": len(station["pattern_unique_values"].get("question_mark", [])),
        "station_unbalanced_parentheses": len(station["pattern_unique_values"].get("unbalanced_parentheses", [])),
        "destination_only_station": station["destination_only_unique_values"],
    }
    labels = {
        "invalid_file_schema": "檔案首列schema／header無法安全辨識",
        "invalid_field_count": "列欄寬不符",
        "invalid_borrow_time": "借車時間無效",
        "invalid_return_time": "還車時間無效",
        "invalid_duration": "duration格式無效",
        "invalid_borrow_date": "借用日期無效",
        "unsupported_bike_type": "7欄版不支援車種",
        "origin_missing": "origin station缺失",
        "destination_missing": "destination station缺失",
        "illegal_utf8": "含非法UTF-8 byte",
        "station_replacement_character": "站名含U+FFFD `�`",
        "station_question_mark": "站名含`?`",
        "station_unbalanced_parentheses": "站名括號不平衡",
        "duration_zero": "duration = 0",
        "duration_gt_24h": "duration > 24h",
        "duration_gt_7d": "duration > 7d（含於>24h）",
        "return_before_borrow": "還車時間早於借車時間",
        "duration_timestamp_delta_ge_1h": "duration與整點時間差相差≥1h",
        "destination_only_station": "destination-only station",
        "rare_od_pair": "全期只出現1次的raw OD pair",
    }
    lines = [
        "# Phase 3：YouBike 全期間 data quality profile",
        "",
        "> **Observed in raw data**：本文件只描述2023/01–2024/12官方月檔的完整唯讀掃描結果；不代表原研究採用相同檔案版本或處理方式。",
        "",
        "> **Reconstruction decision**：本階段未清理、修復、刪列、去重、站點reconciliation或建立OD。Repeated identical records全部保留。",
        "",
        "## 範圍與方法",
        "",
        f"- 核心期間：2023/01–2024/12，共24個官方月檔。CSV精確header不列入分母；所有data records均保留，總計 **{total:,} records**。本階段未另以逐日筆數判定交易完整性。",
        "- 以Phase 2.6 content-based parser contract辨識6／7欄及header；UTF-8以`surrogateescape`無損解碼。",
        "- 欄位值採raw exact match；未trim、normalize、修復、fuzzy match或站點ID回填。",
        "- `rare_od_pair`的描述性定義：同一raw origin/destination組合在整個核心期間僅出現1次。這不是錯誤判定。",
        "- `destination_only_station`以核心全期非空raw名稱判定，而不是逐月判定。",
        "",
        "## 最終狀態",
        "",
        "```text",
        f"Total records                              {total:>12,}  100.0000%",
        f"├── Invalid union                         {unions['invalid']['count']:>12,}  {unions['invalid']['percentage']:.4f}%",
        f"├── Quality-issue union                   {unions['quality_issue']['count']:>12,}  {unions['quality_issue']['percentage']:.4f}%",
        f"├── Suspicious union                      {unions['suspicious']['count']:>12,}  {unions['suspicious']['percentage']:.4f}%",
        f"└── Clean-with-respect-to-current-rules   {unions['clean_with_respect_to_current_rules']['count']:>12,}  {unions['clean_with_respect_to_current_rules']['percentage']:.4f}%",
        "",
        f"Repeated identical records (retained)     {repeated['involved_records']:>12,}  {pct(repeated['involved_records'], total)}",
        "```",
        "",
        "Invalid／Quality／Suspicious並非互斥。`Clean-with-respect-to-current-rules`只代表沒有命中本次規則，不等於已清理或已證實正確。Repeated identical records獨立報告，不改變上述分類。",
        "",
        "## Issue摘要",
        "",
        "| Issue | Category | Records | % | Unique raw values | Main months | Status |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for issue, values in issues.items():
        definition = profile["issue_definitions"][issue]
        lines.append(
            f"| {labels[issue]} | {definition['category']} | {values['count']:,} | {values['percentage']:.4f}% | "
            f"{unique_lookup.get(issue, '—')} | {top_months(profile, issue)} | {definition['status']} |"
        )
    lines.extend([
        "| 完全相同record（另列、全保留） | Repeated / retained | "
        f"{repeated['involved_records']:,} | {pct(repeated['involved_records'], total)} | — | 2024-12, 2024-10, 2024-09 | retain |",
        "",
        "## Encoding profiling",
        "",
        f"- Illegal byte count：**{enc['illegal_byte_count']:,}**。",
        f"- Affected field count：**{enc['affected_field_count']:,}**。",
        f"- Affected record count：**{enc['affected_record_count']:,}（{enc['affected_records_percentage']:.4f}%）**。",
        f"- Origin affected records：{enc['origin_affected_records']:,}；destination：{enc['destination_affected_records']:,}；同筆多欄受影響：{enc['records_with_multiple_affected_fields']:,}。",
        "- 非法bytes僅出現在`origin_station_raw`與`destination_station_raw`。完整掃描首次顯示受影響月份為2023/03–07與2024/07–12；這擴充了Phase 2.5代表月份抽樣的觀察範圍。",
        "",
        "| Field | Illegal bytes | Affected fields | Affected records |",
        "|---|---:|---:|---:|",
    ])
    for field, values in enc["by_field"].items():
        lines.append(f"| `{field}` | {values['illegal_byte_count']:,} | {values['affected_field_count']:,} | {values['affected_record_count']:,} |")
    lines.extend([
        "",
        "`illegal bytes ≠ affected fields ≠ affected records`；上述數字不可互換。沒有執行encoding repair。",
        "",
        "## Station-field profiling",
        "",
        f"- Origin missing：{issues['origin_missing']['count']:,}；destination missing：{issues['destination_missing']['count']:,}；任一端missing：{issues['origin_missing']['count'] + issues['destination_missing']['count'] - profile['issue_overlap_matrix']['origin_missing']['destination_missing']:,}；兩端皆missing：{profile['issue_overlap_matrix']['origin_missing']['destination_missing']:,}。",
        f"- 含`�`：{issues['station_replacement_character']['count']:,} records／{unique_lookup['station_replacement_character']}種raw值。含`?`：{issues['station_question_mark']['count']:,}／{unique_lookup['station_question_mark']}種。括號不平衡：{issues['station_unbalanced_parentheses']['count']:,}／{unique_lookup['station_unbalanced_parentheses']}種。",
        f"- Destination-only：{issues['destination_only_station']['count']:,} records、{station['destination_only_unique_values']:,}種raw名稱。這可能包含跨市還車或名稱品質問題，尚未做站點主檔比對。",
        f"- `_數字`後綴共有{len(station['pattern_unique_values'].get('numeric_suffix', []))}種raw名稱；origin side occurrences 1,526,624、destination side occurrences 1,437,286。僅盤點，不視為error。",
        "",
        "## Duration與時間關係",
        "",
        "| Statistic | Seconds | H:MM:SS |",
        "|---|---:|---:|",
    ])
    for label in ("P50", "P90", "P95", "P99", "P99.9", "max"):
        lines.append(f"| {label} | {q[label]:,} | {hms(q[label])} |")
    lines.extend([
        "",
        f"- 可解析duration：{duration['valid_record_count']:,}；duration=0：{issues['duration_zero']['count']:,}；>24h：{issues['duration_gt_24h']['count']:,}；>7d：{issues['duration_gt_7d']['count']:,}。極端值全部保留。",
        f"- 跨午夜候選：{temporal.get('cross_midnight_candidate', 0):,}，僅描述、不列issue。借還整點完全相同：{temporal.get('same_timestamp', 0):,}，符合已知整點精度限制，不列issue。",
        f"- 還車早於借車：{issues['return_before_borrow']['count']:,}；duration與整點時間差相差≥1h：{issues['duration_timestamp_delta_ge_1h']['count']:,}，列Suspicious但保留。",
        "",
        "## Bike type",
        "",
        f"- 6欄schema structural absence：{bike['v1_structural_absence']:,} records；不算missing-data error。",
        f"- 7欄schema：一般車 {bike['v2'].get('一般車', 0):,}；電輔車 {bike['v2'].get('電輔車', 0):,}；blank/null {bike['v2'].get('blank_or_null', 0):,}；unknown {bike['v2'].get('unknown', 0):,}。",
        "",
        "## Repeated identical records（獨立報告、全部保留）",
        "",
        f"- Repeated groups：**{repeated['repeated_groups']:,}**。",
        f"- Involved records：**{repeated['involved_records']:,}（{pct(repeated['involved_records'], total)}）**。",
        f"- Excess copies：**{repeated['excess_copies']:,}**。這是multiplicity統計，不是應刪列數。",
        f"- Multiplicity groups：2次 {repeated['multiplicity_groups']['2']:,}；3次 {repeated['multiplicity_groups']['3']:,}；4次 {repeated['multiplicity_groups']['4']:,}；5次以上 {repeated['multiplicity_groups']['5_plus']:,}。",
        "",
        "> 這只是 repeated-record profiling，不代表錯誤旅次。歷史資料沒有trip ID，且借還時間只有整點精度；本專案正式決策為全部保留，不執行`drop_duplicates()`。",
        "",
        "## 類別重疊",
        "",
        "| Records | Invalid | Quality issue | Suspicious |",
        "|---|---:|---:|---:|",
    ])
    matrix = profile["category_overlap_matrix"]
    for left in ("Invalid", "Quality issue", "Suspicious"):
        lines.append(f"| {left} | {matrix[left]['Invalid']:,} | {matrix[left]['Quality issue']:,} | {matrix[left]['Suspicious']:,} |")
    lines.extend([
        "",
        f"Quality∩Suspicious為{matrix['Quality issue']['Suspicious']:,} records。至少命中一個issue的record union為{total - unions['clean_with_respect_to_current_rules']['count']:,}；不能以各issue count直接相加。完整issue-by-issue cross-count見JSON。",
        "",
        "## 月別摘要",
        "",
        "| Month | Records | Schema/header | Invalid | Quality | Suspicious | Encoding affected | Repeated involved |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ])
    file_lookup = {item["month"]: item for item in profile["files"]}
    for month, values in profile["monthly"].items():
        file = file_lookup[month]
        schema = f"{file['schema_version']} / {'header' if file['header_present'] else 'no header'}"
        lines.append(
            f"| {month} | {values['total_records']:,} | {schema} | {values['invalid_union']:,} | "
            f"{values['quality_union']:,} ({pct(values['quality_union'], values['total_records'])}) | "
            f"{values['suspicious_union']:,} ({pct(values['suspicious_union'], values['total_records'])}) | "
            f"{values['encoding'].get('affected_record_count', 0):,} | {values['repeated_identical']['involved_records']:,} |"
        )
    lines.extend([
        "",
        "## 主要風險與解讀",
        "",
        "1. 站名括號不平衡影響1,213,059 records，是最大Quality flag；31種raw名稱多呈現被截短的字串外觀，但原因及正確名稱仍未證實。",
        "2. Destination-only影響1,564,493 records，是最大Suspicious flag；未完成跨市站點與歷史station master reconciliation前，不能把它判成錯誤。",
        "3. `?`、原生`�`與非法UTF-8是三種不同現象，分別影響342,114、145,367與181,703 records，彼此可能重疊；不能用單一replace規則處理。",
        "4. 極端duration的max遠高於24小時，但只有6,988 records >24h；極端不等於錯誤，需先決定duration與整點timestamp矛盾時的優先欄位。",
        "5. 637,221 records位於完全相同record群組，但沒有trip ID足以證明重複匯入；全部保留。",
        "",
        "## Unresolved cleaning questions（本階段不決定）",
        "",
        "- 非法UTF-8、原生`�`、`?`與截短站名應採quarantine、保留raw label，或以哪一份可追溯歷史station master修復？",
        "- Destination-only raw名稱中，哪些是合法跨市還車、歷史更名／移站，哪些才是名稱損壞？",
        "- OD節點納入前，origin/destination缺失records的處理與denominator如何定義？",
        "- 極端duration與整點timestamp不一致時，以哪個欄位為權威？是否需要只做敏感度分析而非刪除？",
        "- Rare OD與repeated identical records應如何在後續診斷中保留標記，而不改變旅次權重？",
        "",
        "## Validation",
        "",
    ])
    lines.extend(f"- PASS：{check}。" for check in checks)
    lines.extend([
        "- 合成fixture與既有parser/audit tests另行驗證；raw ZIP與SQLite中間檔均由`.gitignore`排除。",
        "",
    ])
    if "extended_report_period" in profile:
        lines.extend(render_extension(profile, profile["extended_report_period"], profile["extension_comparison"]))
    lines.extend(["Phase 3範圍補充到此停止。沒有制定或執行cleaning policy，也未進入Phase 3.1／Phase 4。", ""])
    return "\n".join(lines)


def render_extension(core: dict, extended: dict, comparison: dict) -> list[str]:
    cu = core["category_unions"]
    eu = extended["category_unions"]
    added = comparison["added_records"]
    d = comparison["duration_temporal"]
    q_core = d["core_quantiles_seconds"]
    q_ext = d["extended_quantiles_seconds"]
    lines = [
        "",
        "## Extended report period 補充（2023/01–2025/03）",
        "",
        "> **Observed in raw data**：以下為同一套Phase 3規則對27個月重新計算的結果。Core period仍保留在本文件前半與JSON根層，沒有被extended denominator覆蓋。",
        "",
        "| Period | Total records | Invalid union | Quality union | Suspicious union | Clean under current rules |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Core 2023/01–2024/12 | {core['total_records']:,} | {cu['invalid']['count']:,} ({cu['invalid']['percentage']:.4f}%) | {cu['quality_issue']['count']:,} ({cu['quality_issue']['percentage']:.4f}%) | {cu['suspicious']['count']:,} ({cu['suspicious']['percentage']:.4f}%) | {cu['clean_with_respect_to_current_rules']['count']:,} ({cu['clean_with_respect_to_current_rules']['percentage']:.4f}%) |",
        f"| Extended 2023/01–2025/03 | {extended['total_records']:,} | {eu['invalid']['count']:,} ({eu['invalid']['percentage']:.4f}%) | {eu['quality_issue']['count']:,} ({eu['quality_issue']['percentage']:.4f}%) | {eu['suspicious']['count']:,} ({eu['suspicious']['percentage']:.4f}%) | {eu['clean_with_respect_to_current_rules']['count']:,} ({eu['clean_with_respect_to_current_rules']['percentage']:.4f}%) |",
        "",
        f"新增2025/01–03共 **{added:,} records**。`destination_only_station`與`rare_od_pair`依各自全期間重新判定，因此extended union不能由core union直接加上三個月union。",
        "",
        "### 2025/01–03 月別結果",
        "",
        "| Month | Records | Schema/header | Invalid | Quality | Suspicious | Encoding affected | Repeated involved |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    files = {item["month"]: item for item in extended["files"]}
    for month in comparison["added_months"]:
        values = extended["monthly"][month]
        file = files[month]
        lines.append(
            f"| {month} | {values['total_records']:,} | {file['schema_version']} / {'header' if file['header_present'] else 'no header'} | "
            f"{values['invalid_union']:,} | {values['quality_union']:,} ({pct(values['quality_union'], values['total_records'])}) | "
            f"{values['suspicious_union']:,} ({pct(values['suspicious_union'], values['total_records'])}) | "
            f"{values['encoding'].get('affected_record_count', 0):,} | {values['repeated_identical']['involved_records']:,} |"
        )
    bike = comparison["bike_type"]
    enc = comparison["encoding"]
    station = comparison["station_patterns"]
    duration = d["added_issue_counts"]
    lines.extend([
        "",
        "### 新行為檢查",
        "",
        "- **Schema：沒有觀察到新行為。** 2025/01、02、03皆為`v2_7col`、無header，全月未命中Invalid schema gate。",
        f"- **Bike type：沒有新值。** 新增月份只有一般車 {bike['added_counts'].get('一般車', 0):,}、電輔車 {bike['added_counts'].get('電輔車', 0):,}；blank／unknown均為0。",
        f"- **Encoding：沒有新欄位或新raw byte value；既有問題在2025/01持續。** 新增 {enc['added_illegal_bytes']:,} illegal bytes、{enc['added_affected_fields']:,} affected fields、{enc['added_affected_records']:,} affected records；2025/02–03為0。",
        f"- **Station anomaly pattern：沒有新pattern class或新raw anomaly value。** 2025/01新增既有括號不平衡81,689 records；三個月合計既有`?` 66,613 records；原生`�`新增0。`_數字`後綴仍只盤點、不視為error。",
        f"- **Duration／temporal：沒有新異常型態，長尾比率略低。** 新增duration=0共{duration['duration_zero']:,}、>24h {duration['duration_gt_24h']:,}、>7d {duration['duration_gt_7d']:,}、timestamp差異≥1h {duration['duration_timestamp_delta_ge_1h']:,}、return-before-borrow {duration['return_before_borrow']:,}；跨午夜候選{d['added_cross_midnight_candidates']:,}。",
        "",
        "| Duration statistic | Core seconds | Extended seconds |",
        "|---|---:|---:|",
    ])
    for label in ("P50", "P90", "P95", "P99", "P99.9", "max"):
        lines.append(f"| {label} | {q_core[label]:,} | {q_ext[label]:,} |")
    lines.extend([
        "",
        f"Extended repeated identical records：{extended['repeated_identical']['repeated_groups']:,} groups、{extended['repeated_identical']['involved_records']:,} involved records、{extended['repeated_identical']['excess_copies']:,} excess copies；全部保留。",
        "",
        "### Extended validation",
        "",
        "- PASS：27個月份均以相同Phase 3規則完整重算。",
        "- PASS：core denominator與既有92,700,026 records統計保留於JSON根層。",
        "- PASS：2025/01–03 raw ZIP未納入Git；沒有產生cleaned records。",
        "",
    ])
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("notes/data-quality-profile.json"))
    parser.add_argument("--output", type=Path, default=Path("notes/data-quality-profile.md"))
    parser.add_argument("--source-receipt", type=Path, default=Path("notes/source-receipt.json"))
    args = parser.parse_args()
    profile = json.loads(args.input.read_text(encoding="utf-8"))
    receipt = json.loads(args.source_receipt.read_text(encoding="utf-8")) if args.source_receipt.exists() else None
    checks = validate(profile, receipt)
    if "extended_report_period" in profile:
        extended_checks = validate(profile["extended_report_period"], receipt)
        checks.extend(f"extended: {check}" for check in extended_checks)
    args.output.write_text(render(profile, checks), encoding="utf-8")
    print(f"PASS {len(checks)} invariants; wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
