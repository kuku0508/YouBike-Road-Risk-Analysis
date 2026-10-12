"""Synthetic audit fixtures only; never depend on or modify actual raw data."""
import csv
import io
from pathlib import Path
import tempfile
import unittest
import zipfile
from src.audit_youbike import inspect_trips, inspect_index, fingerprint, duration_seconds


class AuditTests(unittest.TestCase):
    def test_duplicate_missing_malformed_and_temporal_diagnostics(self):
        good = ['2023-11-01 08:00:00', '甲站', '2023-11-01 08:00:00', '乙站', '00:08:36', '2023-11-01']
        rows = [good, good, ['bad', ' ', '2023-11-02 00:00:00', '乙站', '99:99:00', 'invalid'],
                ['2023-11-30 23:00:00', '甲站', '2023-12-01 00:00:00', '甲站', '00:30:00', '2023-11-30'],
                ['short', 'row']]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'fixture.zip'
            text = io.StringIO(newline='')
            csv.writer(text).writerows(rows)
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('fixture.csv', text.getvalue().encode('utf-8'))
            before = fingerprint(p)
            a = inspect_trips(p, '2023-11')
            self.assertEqual(a['row_count'], 5)  # First row must not disappear as header.
            self.assertEqual(a['width_counts'], {6: 4, 2: 1})
            self.assertEqual(a['exact_duplicates']['excess_rows'], 1)
            self.assertEqual(a['exact_duplicates']['affected_rows'], 2)
            self.assertEqual(a['columns'][1]['missing_count'], 1)
            self.assertEqual(a['columns'][1]['missing_fraction'], .25)
            self.assertEqual(a['timestamps']['c1']['invalid_or_missing'], 1)
            self.assertEqual(a['anomalies']['duration_invalid'], 1)
            self.assertEqual(a['anomalies']['cross_calendar_day'], 1)
            self.assertFalse(a['all_calendar_dates_present'])
            self.assertEqual(before, fingerprint(p))

    def test_source_index_missing_duplicate_invalid_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'index.csv'
            with p.open('w', encoding='cp950', newline='') as f:
                w = csv.writer(f)
                w.writerow(['發布機關名稱', '機關代碼', 'UpdateTime', 'SrcUpdateTime', 'fileinfo', 'fileURL'])
                for month, url in [('1',''), ('3','not-a-url'), ('3','https://example.org/file.zip')]:
                    w.writerow(['測試', 'id', '2023-01-01T00:00:00', '', f'2023/{month}/1', url])
            a = inspect_index(p)
            self.assertIsNone(a['worksheets'])
            self.assertEqual(a['missing_months'], ['2023-02'])
            self.assertEqual(a['duplicate_months'], {'2023-03': 2})
            self.assertEqual(a['invalid_urls'], 2)
            self.assertEqual(a['missing_cells']['fileURL'], 1)

    def test_duration_does_not_wrap_at_24_hours(self):
        self.assertEqual(duration_seconds('25:00:00'), 90000)
        self.assertIsNone(duration_seconds('00:60:00'))
        self.assertIsNone(duration_seconds('-01:00:00'))


if __name__ == '__main__':
    unittest.main()
