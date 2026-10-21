"""Focused retained-source and malformed-input normalization checks; offline only."""

from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from normalization import normalize as n

RUN = Path(__file__).resolve().parent.parent / 'artifacts/runs/omega4-live-20261020-attempt002'


class NormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, cls.report = n.build(RUN)

    def claim(self, ident, revision):
        return next(c for c in self.doc['claims'] if c['claim_id'] == ident and c['revision'] == revision)

    def rows(self, tab):
        return self.doc['workbook'][tab]['rows']

    def test_complete_source_inventory(self):
        counts = self.doc['source_counts']
        self.assertEqual((counts['initial-claims']['pages'], counts['initial-claims']['records']), (120, 120))
        self.assertEqual((counts['claim-updates']['pages'], counts['claim-updates']['records']), (7, 7))
        self.assertEqual((counts['receipts']['pages'], counts['receipts']['records']), (102, 203))
        self.assertEqual(tuple(self.doc['workbook']), n.TABS)
        self.assertEqual(counts['travel-registers'], dict(zip(n.TABS, [14, 123, 201, 2, 2, 3, 307, 307, 220, 9])))
        self.assertEqual(self.report['expense_occurrences'], 208)

    def test_c03_c24_shared_cost_preserved(self):
        old = self.claim('C03', 1)
        new = self.claim('C24', 1)
        self.assertEqual(new['related_claim_ids'], ['C03'])
        self.assertEqual([e['expense_id'] for e in new['expenses']], ['COST-03', 'COST-24'])
        self.assertEqual(old['expenses'][0]['original_amount'], '200.00')
        occurrences = self.doc['expense_identity_occurrences']['COST-03']
        self.assertEqual([(o['claim_id'], o['revision']) for o in occurrences], [('C03', 1), ('C24', 1)])
        checks = [c for c in self.doc['cross_source_checks'] if c['expense_id'] == 'COST-03']
        self.assertTrue(all(c['merchant_statuses_observed'] == ['settled'] for c in checks))
        self.assertEqual(checks[0]['merchant_identity_matches'], checks[1]['merchant_identity_matches'])

    def test_c09_replacement_keeps_original(self):
        self.assertEqual(self.claim('C09', 1)['trip_id'], 'T09')
        self.assertEqual(self.claim('C09', 2)['trip_id'], 'T09B')
        self.assertEqual(self.claim('C09', 2)['expenses'][0]['expense_id'], 'COST-09B')
        self.assertEqual(self.claim('C09', 2)['trip_revision'], 1)

    def test_c18_no_stale_revision_link_and_late_transfer_visible(self):
        self.assertEqual(self.claim('C18', 2)['trip_id'], 'T18B')
        checks = [c for c in self.doc['cross_source_checks'] if c['claim_id'] == 'C18' and c['claim_revision'] == 2]
        self.assertEqual(checks[0]['review_exact_subject_revision_matches'], [])
        events = [r['values'] for r in self.rows('Finance activity') if r['values']['Claim reference'] == 'C18']
        self.assertEqual({r['Request reference'] for r in events}, {'REQ-C18'})
        late = next(r for r in events if r['Activity reference'] == 'F-C18-3')
        self.assertEqual((late['Activity type'], late['Amount (EUR)'], late['Arrival batch']), ('settled', '100.0', 4))
        self.assertTrue(all('claim_revision' not in r for r in events))
        cancellation = next(r['values'] for r in self.rows('Travel cancellations') if r['values']['Cancellation activity reference'] == 'TC018-confirmed')
        self.assertEqual(cancellation['Trip reference'], 'T18')

    def test_c19_revisions_exceptions_and_refund_link(self):
        self.assertEqual([self.claim('C19', r)['expenses'][0]['original_amount'] for r in [1, 2, 3]], ['100.00']*3)
        self.assertEqual(self.claim('C19', 2)['finance_exception']['allowed_original_amount_observed'], '80.00')
        self.assertEqual(self.claim('C19', 3)['finance_exception']['cancellation_id'], 'TC019')
        refund = next(r['values'] for r in self.rows('Finance activity') if r['values']['Activity reference'] == 'F-C19-3')
        self.assertEqual((refund['Original activity reference'], refund['Amount (EUR)']), ('F-C19-1', '20.0'))

    def test_c121_scoped_exception_and_independent_revisions(self):
        claim = self.claim('C121', 2)
        self.assertEqual((claim['trip_revision'], claim['finance_exception']['cancellation_id']), (1, 'TC121'))
        self.assertEqual(claim['finance_exception']['allowed_original_amount_observed'], '20.00')
        event = next(r['values'] for r in self.rows('Travel cancellations') if r['values']['Cancellation activity reference'] == 'TC121-confirmed')
        self.assertEqual((event['Cancelled subject'], event['Trip revision'], event['Permit revision']), ('permit', 1, 1))
        self.assertEqual(event['Activity time (UTC)'], '2026-09-12T10:00:00Z')

    def test_repeated_deliveries_not_distinct_transactions(self):
        for ident, sheet, rows in [('F-C01-1', 'Finance activity', [6, 31]),
                                   ('TC122-confirmed', 'Travel cancellations', [7, 14])]:
            group = next(e for e in self.doc['event_delivery_groups'] if e['event_id'] == ident)
            self.assertEqual(group['classification'], 'repeated_delivery')
            self.assertEqual(group['delivery_count'], 2)
            self.assertEqual(group['delivery_record_ids'], [f'travel-registers:{sheet}:row:{row}' for row in rows])

    def test_conflicting_delivery_visible_without_discarding(self):
        tabs = deepcopy(self.doc['workbook'])
        row = next(r for r in tabs['Finance activity']['rows'] if r['source']['row'] == 31)
        row['raw_cells']['I']['value'] = '999.0'
        issues = []
        groups = n.repeated_deliveries(tabs, issues)
        group = next(g for g in groups if g['event_id'] == 'F-C01-1')
        self.assertEqual((group['classification'], group['delivery_count']), ('conflicting_delivery', 2))
        self.assertEqual(len(issues), 1)

    def test_missing_payment_links_reported(self):
        checks = self.doc['cross_source_checks']
        gaps = {c['expense_id'] for c in checks if not c['merchant_identity_matches']}
        self.assertEqual(gaps, {'COST-08', 'COST-114-2'})
        self.assertTrue(any('No review-ledger row' in i['reason'] for i in self.report['issues']))

    def test_raw_numeric_and_multiline_values_preserved(self):
        row = self.rows('Trips')[0]
        self.assertEqual(row['raw_cells']['E']['value'], '46267.0')
        self.assertEqual(row['values']['Start date'], '2026-09-02')
        ledger = self.rows('Review ledger')[0]
        self.assertIn('POL-2026.2', ledger['values']['Source revisions'])
        self.assertIn('\n', ledger['raw_cells']['K']['value'])
        self.assertIsNone(self.rows('Travel cancellations')[0]['values']['Effective time (UTC)'])

    def test_ambiguous_date_and_nonintegral_revision_flagged(self):
        issues = []
        self.assertIsNone(n.typed('1.5', 'integer', 'r', 'revision', issues))
        self.assertIsNone(n.typed('46266.5', 'date', 'r', 'date', issues))
        self.assertIsNone(n.typed('60', 'date', 'r', 'date', issues))
        self.assertEqual(len(issues), 3)

    def test_corruption_stops_before_pdf_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)/'run'
            shutil.copytree(RUN, run)
            (run/'sources/initial-claims.pdf').write_bytes(b'changed')
            with patch.object(n, 'PdfReader') as reader, self.assertRaises(ValueError):
                n.build(run)
            reader.assert_not_called()

    def test_deterministic_outputs_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory)/'first', Path(directory)/'second'
            n.normalize(RUN, first)
            n.normalize(RUN, second)
            for p in first.iterdir():
                self.assertEqual(p.read_bytes(), (second/p.name).read_bytes())
            with self.assertRaises(FileExistsError):
                n.normalize(RUN, first)

    def test_missing_expense_cells_stay_unparsed(self):
        text = self.claim('C03', 1)['raw_text'].replace('200.00\nEUR', 'EUR')
        issues = []
        claim = n.parse_claim(text, self.claim('C03', 1)['source'], issues)
        self.assertEqual(claim['expenses'], [])
        self.assertIn('unparsed_expense_text', claim)
        self.assertTrue(issues)


if __name__ == '__main__':
    unittest.main()
