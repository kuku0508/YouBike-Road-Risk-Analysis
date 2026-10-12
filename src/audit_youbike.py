"""Read-only index and historical six-column YouBike audit; standard library only."""
import argparse
import base64
import calendar
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timezone
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import zipfile


def fingerprint(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return dict(filename=Path(path).name, bytes=Path(path).stat().st_size, sha256=h.hexdigest())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def expected_dates(month):
    y, m = map(int, month.split('-'))
    return [date(y, m, d).isoformat() for d in range(1, calendar.monthrange(y, m)[1]+1)]


def inspect_index(path):
    before = fingerprint(path)
    raw = Path(path).read_bytes()
    try:
        raw.decode('utf-8-sig', errors='strict')
        encoding = 'utf-8-sig'
    except UnicodeDecodeError:
        raw.decode('cp950', errors='strict')
        encoding = 'cp950'
    with Path(path).open(encoding=encoding, newline='') as f:
        all_rows = list(csv.reader(f, strict=True))
    nonblank = [r for r in all_rows if r]
    header = nonblank[0]
    if len(set(header)) != len(header) or any(len(r) != len(header) for r in nonblank[1:]):
        raise ValueError('Invalid index header or field count')
    rows = [dict(zip(header, r)) for r in nonblank[1:]]
    months, patterns, formats = Counter(), Counter(), Counter()
    for row in rows:
        dt = datetime.strptime(row['fileinfo'], '%Y/%m/%d')
        month = dt.strftime('%Y-%m')
        months[month] += 1
        u = urlsplit(row['fileURL'])
        valid = u.scheme in ('https', 'http') and bool(u.hostname) and not any(c.isspace() for c in row['fileURL'])
        expected = f'/dotapp/youbike_second_ticket_opendata/{dt.year}/{month}/{dt:%Y%m}_YouBike2.0票證刷卡資料.zip'
        row.update(month=month, year=dt.year, month_number=dt.month, url_syntax_valid=valid,
                   url_matches_month=u.path == expected, url_extension=Path(u.path).suffix, host=u.hostname)
        pattern = re.sub(r'20\d{2}', 'YYYY', u.path)
        pattern = re.sub(r'-\d{2}/', '-MM/', pattern)
        pattern = re.sub(r'YYYY\d{2}_', 'YYYYMM_', pattern)
        patterns[u.scheme + '://' + (u.netloc or '') + pattern] += 1
        formats[str(dt.year) + ':' + Path(u.path).suffix] += 1
    first, last = min(months), max(months)
    y, m = map(int, first.split('-'))
    expected = []
    while f'{y:04}-{m:02}' <= last:
        expected.append(f'{y:04}-{m:02}')
        m += 1
        if m == 13:
            y, m = y+1, 1
    assert before == fingerprint(path)
    return {**before, 'format': 'CSV', 'worksheets': None, 'encoding': encoding,
            'encoding_note': 'Strict decode compatibility, not proof of original writer encoding',
            'row_count': len(rows), 'column_count': len(header), 'columns': header,
            'blank_csv_records': sum(not r for r in all_rows), 'crcrlf_count': raw.count(b'\r\r\n'),
            'missing_cells': {h: sum(not r[h].strip() for r in rows) for h in header},
            'first_month': first, 'last_month': last, 'missing_months': [x for x in expected if x not in months],
            'duplicate_months': {k: v for k, v in months.items() if v > 1},
            'invalid_urls': sum(not r['url_syntax_valid'] for r in rows),
            'month_url_mismatches': sum(not r['url_matches_month'] for r in rows),
            'url_patterns': dict(patterns), 'year_extensions': dict(formats),
            'update_time_formats': dict(Counter('ISO8601' if 'T' in r['UpdateTime'] else 'slash_datetime' for r in rows)),
            'rows': rows}


def head_links(index):
    def check(row):
        result = {'month': row['month'], 'url': row['fileURL']}
        try:
            with urlopen(Request(quote(row['fileURL'], safe=':/'), method='HEAD'), timeout=20) as response:
                result.update(status=response.status, bytes=response.headers.get('Content-Length'),
                              content_type=response.headers.get('Content-Type'), final_url=response.url)
        except HTTPError as exc:
            result.update(status=exc.code, error=str(exc))
        except (URLError, TimeoutError, OSError) as exc:
            result.update(status=None, error=str(exc))
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(check, index['rows']))
    return {'checked_utc': datetime.now(timezone.utc).isoformat(),
            'method': 'HEAD only; no monthly file bodies downloaded', 'rows': rows}


def download(index, month, output):
    selected = [r for r in index['rows'] if r['month'] == month]
    if len(selected) != 1 or not selected[0]['url_syntax_valid']:
        raise ValueError('Month must have exactly one valid URL')
    output = Path(output)
    if output.exists():
        raise FileExistsError('Never overwrite raw data')
    output.parent.mkdir(parents=True, exist_ok=True)
    url = selected[0]['fileURL']
    md5 = hashlib.md5()
    with urlopen(quote(url, safe=':/'), timeout=60) as response, output.open('xb') as f:
        headers, final_url = dict(response.headers), response.url
        for chunk in iter(lambda: response.read(1048576), b''):
            f.write(chunk)
            md5.update(chunk)
    if headers.get('Content-Length'):
        assert output.stat().st_size == int(headers['Content-Length'])
    if headers.get('Content-MD5'):
        assert base64.b64encode(md5.digest()).decode() == headers['Content-MD5']
    return {**fingerprint(output), 'url': url, 'final_url': final_url,
            'retrieved_utc': datetime.now(timezone.utc).isoformat(), 'headers': headers,
            'source_index_sha256': index['sha256']}


@lru_cache(maxsize=20000)
def parse_time(value):
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
            return None
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@lru_cache(maxsize=100000)
def duration_seconds(value):
    match = re.fullmatch(r'(\d+):([0-5]\d):([0-5]\d)', value)
    return sum(int(x)*scale for x, scale in zip(match.groups(), (3600, 60, 1))) if match else None


def inspect_trips(path, month):
    """All CSV records count as data. Compare exact parsed strings using disk SQLite.
    No names normalized, no records removed; unsupported widths counted explicitly.
    """
    before = fingerprint(path)
    widths, daily, return_daily, date_daily, hourly = (Counter() for _ in range(5))
    origin, dest = Counter(), Counter()
    missing, whitespace = [0]*6, [0]*6
    sentinels = [Counter() for _ in range(6)]
    valid_time, time_min, time_max = [0, 0], [None, None], [None, None]
    anomalies = Counter()
    duration_min = duration_max = None
    rows, member_meta, invalid_examples = 0, [], []
    with tempfile.TemporaryDirectory(prefix='youbike-audit-') as tmp:
        con = sqlite3.connect(str(Path(tmp)/'audit.sqlite'))
        con.execute('PRAGMA temp_store=FILE')
        con.execute('PRAGMA cache_size=-65536')
        con.execute('CREATE TABLE raw_rows (value TEXT NOT NULL)')
        batch = []
        with zipfile.ZipFile(path) as z:
            members = [i for i in z.infolist() if not i.is_dir()]
            if not members or any(not i.filename.lower().endswith('.csv') for i in members):
                raise ValueError('Expected CSV-only ZIP; inspect unsupported members manually')
            for info in members:
                readable = info.filename
                if not info.flag_bits & 0x800:
                    try:
                        readable = info.filename.encode('cp437').decode('cp950')
                    except UnicodeError:
                        pass
                member_meta.append({'zip_filename': info.filename, 'cp950_filename_candidate': readable,
                                    'bytes': info.file_size, 'crc32': f'{info.CRC:08x}',
                                    'utf8_filename_flag': bool(info.flag_bits & 0x800)})
                # Full strict UTF-8 stream read also validates ZIP CRC at EOF.
                with z.open(info) as f, io.TextIOWrapper(f, encoding='utf-8-sig', newline='') as text:
                    for row in csv.reader(text, strict=True):
                        rows += 1
                        widths[len(row)] += 1
                        batch.append((json.dumps(row, ensure_ascii=False, separators=(',', ':')),))
                        if len(batch) >= 20000:
                            con.executemany('INSERT INTO raw_rows VALUES (?)', batch)
                            batch.clear()
                        if len(row) != 6:
                            if len(invalid_examples) < 5:
                                invalid_examples.append({'record': rows, 'width': len(row)})
                            continue
                        for i, value in enumerate(row):
                            missing[i] += not value.strip()
                            whitespace[i] += value != value.strip()
                            if value.strip().lower() in ('null', 'none', 'na', 'n/a', 'nan', '-', 'unknown'):
                                sentinels[i][value] += 1
                        origin[row[1]] += 1
                        dest[row[3]] += 1
                        anomalies['both_station_names_missing'] += not row[1].strip() and not row[3].strip()
                        anomalies['either_station_name_missing'] += not row[1].strip() or not row[3].strip()
                        anomalies['station_name_contains_replacement_character'] += '\ufffd' in row[1] or '\ufffd' in row[3]
                        anomalies['station_name_contains_question_mark'] += '?' in row[1] or '?' in row[3]
                        anomalies['same_origin_destination_name'] += row[1] == row[3]
                        ts = [parse_time(row[0]), parse_time(row[2])]
                        for j, value in enumerate(ts):
                            if value is not None:
                                valid_time[j] += 1
                                time_min[j] = value if time_min[j] is None else min(time_min[j], value)
                                time_max[j] = value if time_max[j] is None else max(time_max[j], value)
                                anomalies[f'c{1 if j == 0 else 3}_nonzero_minute_second'] += bool(value.minute or value.second)
                        if ts[0]:
                            daily[ts[0].date().isoformat()] += 1
                            hourly[ts[0].strftime('%Y-%m-%d %H')] += 1
                        if ts[1]:
                            return_daily[ts[1].date().isoformat()] += 1
                        try:
                            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', row[5]):
                                raise ValueError()
                            day_col = date.fromisoformat(row[5]).isoformat()
                            date_daily[day_col] += 1
                            if ts[0]:
                                anomalies['c6_differs_from_c1_date'] += day_col != ts[0].date().isoformat()
                        except ValueError:
                            anomalies['c6_invalid_date'] += 1
                        seconds = duration_seconds(row[4])
                        if seconds is None:
                            anomalies['duration_invalid'] += 1
                        else:
                            duration_min = seconds if duration_min is None else min(duration_min, seconds)
                            duration_max = seconds if duration_max is None else max(duration_max, seconds)
                            anomalies['duration_zero'] += seconds == 0
                            anomalies['duration_gt_24h'] += seconds > 86400
                        if all(t is not None for t in ts):
                            delta = int((ts[1]-ts[0]).total_seconds())
                            anomalies['return_before_borrow'] += delta < 0
                            anomalies['equal_hour_timestamps'] += delta == 0
                            anomalies['cross_calendar_day'] += ts[1].date() != ts[0].date()
                            if seconds is not None:
                                anomalies['duration_not_equal_timestamp_delta'] += delta != seconds
                                anomalies['abs_duration_delta_difference_ge_3600'] += abs(seconds-delta) >= 3600
                        if rows % 500000 == 0:
                            print(f'Audited {rows:,} records', flush=True)
        if batch:
            con.executemany('INSERT INTO raw_rows VALUES (?)', batch)
        con.commit()
        assert con.execute('SELECT COUNT(*) FROM raw_rows').fetchone()[0] == rows
        groups, affected, excess = con.execute(
            'SELECT COUNT(*), COALESCE(SUM(n),0), COALESCE(SUM(n-1),0) '
            'FROM (SELECT COUNT(*) n FROM raw_rows GROUP BY value HAVING COUNT(*)>1)').fetchone()
        con.close()
    origin_names = {n for n in origin if n.strip()}
    dest_names = {n for n in dest if n.strip()}
    names = origin_names | dest_names
    trim_groups = {}
    for name in names:
        trim_groups.setdefault(name.strip(), []).append(name)
    expected = expected_dates(month)
    missing_days = [d for d in expected if d not in daily]
    extra_days = sorted(set(daily)-set(expected))
    absent_hours = [f'{d} {h:02}' for d in expected for h in range(24) if not hourly[f'{d} {h:02}']]
    assert fingerprint(path) == before, 'Raw ZIP changed'
    n6 = widths[6]
    assert sum(daily.values()) == valid_time[0]
    assert sum(return_daily.values()) == valid_time[1]
    assert sum(widths.values()) == rows
    return {**before, 'members': member_meta, 'encoding': 'UTF-8 (strict full CSV stream decode)',
            'header_present': False, 'header_note': 'Explicit six-column historical audit; first row counted as data',
            'month': month, 'row_count': rows, 'width_counts': dict(widths),
            'malformed_width_examples': invalid_examples, 'column_count': 6,
            'columns': [{'position': i+1, 'raw_name': None, 'audit_label': f'c{i+1}',
                         'inferred_type': ['datetime (hour precision)', 'string', 'datetime (hour precision)',
                                           'string', 'duration H+:MM:SS', 'date'][i],
                         'missing_count': missing[i], 'missing_fraction': missing[i]/n6 if n6 else None,
                         'surrounding_whitespace_count': whitespace[i], 'sentinel_counts': dict(sentinels[i])} for i in range(6)],
            'exact_duplicates': {'groups': groups, 'affected_rows': affected, 'excess_rows': excess,
                                 'excess_fraction': excess/rows if rows else None,
                                 'definition': 'All parsed fields identical; excess=sum(n-1); no deduplication'},
            'timestamps': {f'c{i}': {'valid': valid_time[j], 'invalid_or_missing': n6-valid_time[j],
                            'min': time_min[j].isoformat(' ') if time_min[j] else None,
                            'max': time_max[j].isoformat(' ') if time_max[j] else None} for j,i in enumerate([1,3])},
            'daily_borrow_counts': dict(sorted(daily.items())), 'daily_return_counts': dict(sorted(return_daily.items())),
            'c6_date_counts': dict(sorted(date_daily.items())),
            'missing_borrow_dates': missing_days, 'borrow_dates_outside_month': extra_days,
            'missing_borrow_date_hours': absent_hours, 'all_calendar_dates_present': not missing_days and not extra_days,
            'transaction_completeness_proven': False,
            'duration_seconds_min': duration_min, 'duration_seconds_max': duration_max, 'anomalies': dict(anomalies),
            'station_names': {'origin_unique': len(origin_names), 'destination_unique': len(dest_names), 'union_unique': len(names),
                'unique_count_excludes_blank': True,
                'only_origin': sorted(origin_names-dest_names), 'only_destination': sorted(dest_names-origin_names),
                'numeric_suffix_names': sorted(n for n in names if re.search(r'_\d+$', n)),
                'suffix_and_base_both_present': sorted(n for n in names if re.search(r'_\d+$', n) and re.sub(r'_\d+$', '', n) in names),
                'replacement_character_names': sorted(n for n in names if '\ufffd' in n),
                'question_mark_names': sorted(n for n in names if '?' in n),
                'unbalanced_parentheses_names': sorted(n for n in names if n.count('(') != n.count(')')),
                'destination_only_name_records': sum(dest[n] for n in dest_names-origin_names),
                'trim_collisions': sorted([sorted(v) for v in trim_groups.values() if len(v)>1]),
                'id_name_consistency': 'Not assessable: no station ID field', 'coordinates': 'Absent',
                'station_master_join_performed': False}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--month', default='2023-11')
    parser.add_argument('--raw', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--probe-links', type=Path, help='Optional HEAD-only snapshot')
    parser.add_argument('--download', action='store_true', help='Download one month to nonexistent --raw')
    args = parser.parse_args()
    inputs = {args.index.resolve()}
    if args.raw:
        inputs.add(args.raw.resolve())
    outputs = [args.output]
    if args.probe_links:
        outputs.append(args.probe_links)
    if args.download:
        outputs.append(args.output.with_suffix('.download.json'))
    if any(p.resolve() in inputs for p in outputs):
        parser.error('Audit outputs must not overwrite source inputs')
    index = inspect_index(args.index)
    output = {'source_index': index}
    if args.probe_links:
        save(args.probe_links, head_links(index))
    if args.download:
        if args.raw is None:
            parser.error('--download requires --raw')
        save(args.output.with_suffix('.download.json'), download(index, args.month, args.raw))
    if args.raw:
        output['trips'] = inspect_trips(args.raw, args.month)
    save(args.output, output)
    print(f'Audit saved to {args.output}', flush=True)


if __name__ == '__main__':
    main()
