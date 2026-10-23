"""Synthetic adversarial fixtures; retained source files are never rewritten."""
from copy import deepcopy
import unittest
import test_ordinary_closure as base
from validation import validate as v
from reconciliation import reconcile as r


class OrdinaryClosureSafeguardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, cls.report = v.load_verified(base.A, base.N)
        cls.validation = v.evaluate(cls.doc, cls.report, ordinary_claim_ids=['C01'])
        cls.result = r.evaluate(cls.doc, cls.report, cls.validation)

    claim = base.OrdinaryClosureTests.claim
    snapshot = base.OrdinaryClosureTests.snapshot
    mutated = base.OrdinaryClosureTests.mutated
    assert_held = base.OrdinaryClosureTests.assert_held

    def conflict(self, doc, batch):
        row = next(x for x in v.rows(doc, 'Finance activity')
                   if x['record_id'] == 'travel-registers:Finance activity:row:31')
        row['values'].update({'Arrival batch': batch, 'Amount (EUR)': '101.00'})
        for column, cell in row['raw_cells'].items():
            field = doc['workbook']['Finance activity']['headers'][column]
            if field in ('Arrival batch', 'Amount (EUR)'):
                cell.update(value=str(row['values'][field]), raw_xml_value=str(row['values'][field]))
        return row

    def later_receipt(self, doc):
        receipt = next(x for x in doc['receipts'] if x['receipt_id'] == 'R-COST-01')
        receipt['issued_date'] = '2026-09-04'
        receipt['raw_fields']['Issued date'] = '2026-09-04'
        receipt['raw_text'] = receipt['raw_text'].replace('2026-09-01', '2026-09-04')

    def re_review(self, doc, time='2026-09-05T12:00:00Z'):
        reviews = [x for x in v.rows(doc, 'Review ledger') if x['values']['Subject reference'] == 'C01']
        for old in reviews:
            new = deepcopy(old)
            ident = old['values']['Decision reference']
            new['record_id'] = 'synthetic:subsequent:' + ident
            new['values'].update({'Decision reference': ident + '-subsequent', 'Decision time (UTC)': time})
            packet = deepcopy(next(x for x in v.rows(doc, 'Review packets') if x['values']['Decision reference'] == ident))
            packet['record_id'] = 'synthetic:packet:' + ident
            packet['values']['Decision reference'] = ident + '-subsequent'
            v.rows(doc, 'Review ledger').append(new)
            v.rows(doc, 'Review packets').append(packet)

    def test_original_c01_still_closes_for_100_eur(self):
        claim = self.claim(self.snapshot(self.result))
        self.assertEqual((claim['status'], claim['known_paid_cents'], claim['balance_cents']),
                         ('closed-reimbursed', 10000, 0))

    def test_invalid_arrival_conflict_is_held_and_visible(self):
        for batch in (0, -1, True, 'batch-4', 1.5, None):
            with self.subTest(batch=batch):
                result = self.assert_held(lambda doc: self.conflict(doc, batch))
                claim = self.claim(result)
                self.assertIn('finance_arrival_dependency', [x['code'] for x in claim['diagnostics']])
                self.assertTrue(any(x['classification'] == 'invalid_arrival' for x in result['finance_deliveries']))
                self.assertTrue(any(x['code'] == 'finance_arrival' for x in result['unresolved_items']))
                self.assertNotIn('ordinary_closure', next(x for x in result['requests'] if x['request_id'] == 'REQ-C01')['basis_links'])

    def test_valid_batch_conflict_remains_held(self):
        self.assert_held(lambda doc: self.conflict(doc, 4))

    def test_request_link_without_claim_is_held(self):
        def change(doc):
            self.conflict(doc, 0)['values']['Claim reference'] = None
        self.assert_held(change)

    def test_event_link_with_conflicting_claim_is_held(self):
        def change(doc):
            self.conflict(doc, 0)['values'].update({'Claim reference': 'C02', 'Request reference': 'synthetic-other'})
        self.assert_held(change)

    def test_original_payment_link_is_held(self):
        def change(doc):
            self.conflict(doc, 0)['values'].update({'Claim reference': None, 'Request reference': 'synthetic-refund',
                'Activity reference': 'synthetic-refund', 'Original activity reference': 'F-C01-1', 'Activity type': 'refund'})
        self.assert_held(change)

    def test_unrelated_invalid_delivery_does_not_block_c01(self):
        def change(doc):
            row = deepcopy(v.rows(doc, 'Finance activity')[0])
            row['record_id'] = 'synthetic:unrelated-invalid-arrival'
            row['values'].update({'Arrival batch': 0, 'Claim reference': 'C02', 'Request reference': 'REQ-C02',
                'Activity reference': 'synthetic-unrelated', 'Original activity reference': None})
            v.rows(doc, 'Finance activity').append(row)
        doc, result = self.mutated(change)
        self.assertEqual(self.claim(self.snapshot(result, doc))['status'], 'closed-reimbursed')
        self.assertEqual(self.claim(result), self.claim(self.result))

    def test_related_invalid_delivery_leaves_unrelated_claims_unchanged(self):
        result = self.assert_held(lambda doc: self.conflict(doc, 0))
        self.assertEqual([x for x in result['claims'] if x['claim_id'] != 'C01'],
                         [x for x in self.result['claims'] if x['claim_id'] != 'C01'])

    def test_same_revision_receipt_after_approval_is_held(self):
        self.assert_held(self.later_receipt)

    def test_merchant_payment_after_approval_is_held(self):
        def change(doc):
            next(x for x in v.rows(doc, 'Merchant payments') if x['values']['Expense reference'] == 'COST-01')['values']['Paid date'] = '2026-09-04'
        self.assert_held(change)

    def test_valid_subsequent_reviews_restore_eligibility_before_acceptance(self):
        def change(doc):
            self.later_receipt(doc)
            self.re_review(doc)
        doc, result = self.mutated(change)
        self.assertEqual(self.claim(self.snapshot(result, doc))['status'], 'closed-reimbursed')
        self.assertEqual(len(self.claim(result)['ordinary_closure']['decision_ids']), 3)
        policy = v.evaluate(doc, self.report, ordinary_claim_ids=['C01'])
        review = self.claim(policy)['claim_review']
        self.assertEqual(len(review['imports']), 6)
        self.assertTrue(all(x.endswith('-subsequent') for x in review['selected_decisions'].values()))

    def test_reviews_after_acceptance_do_not_retroactively_authorize(self):
        def change(doc):
            self.later_receipt(doc)
            self.re_review(doc, '2026-09-13T12:00:00Z')
        self.assert_held(change)

    def test_partial_subsequent_reviews_are_insufficient(self):
        def change(doc):
            self.later_receipt(doc)
            self.re_review(doc)
            v.rows(doc, 'Review ledger')[:] = [x for x in v.rows(doc, 'Review ledger') if
                not (x['values']['Decision reference'].endswith('-subsequent') and 'supervisor' in x['values']['Review roles'])]
        self.assert_held(change)

    def test_default_path_remains_unchanged(self):
        doc = deepcopy(self.doc)
        self.later_receipt(doc)
        baseline = v.evaluate(self.doc, self.report)
        changed = v.evaluate(doc, self.report)
        self.assertEqual(baseline, changed)


if __name__ == '__main__':
    unittest.main()
