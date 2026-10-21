"""Retained-source integration and isolated adversarial policy checks; offline."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from validation import validate as v

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / 'artifacts/runs/omega4-live-20261020-attempt002'
NORMALIZED = ROOT / 'artifacts/normalizations/omega4-attempt002-normalization-v1'


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, cls.report = v.load_verified(RUN, NORMALIZED)
        cls.result = v.evaluate(cls.doc, cls.report)

    def claim(self, ident, revision=1, result=None):
        return next(c for c in (result or self.result)['claims'] if (c['claim_id'], c['revision']) == (ident, revision))

    def source_claim(self, doc, ident, revision=1):
        return next(c for c in doc['claims'] if (c['claim_id'], c['revision']) == (ident, revision))

    def findings(self, claim, code):
        return [f for f in claim['findings'] + [f for e in claim['expenses'] for f in e['findings']] if f['code'] == code]

    def mutate(self, change, batch=4):
        doc = deepcopy(self.doc)
        change(doc)
        return v.evaluate(doc, self.report, batch)

    def test_inventory_and_diagnostics_preserved(self):
        self.assertEqual((len(self.result['claims']), sum(len(c['expenses']) for c in self.result['claims'])), (127, 208))
        self.assertEqual(self.result['normalization_diagnostics'], self.report['issues'])
        self.assertEqual(len(self.result['normalization_diagnostics']), 18)
        self.assertEqual(len(self.result['cancellations']), 4)
        self.assertTrue(all(c['business_state'] == 'confirmed' for c in self.result['cancellations']))

    def test_c03_c24_shared_gross_not_silently_deducted_or_paid_twice(self):
        first, final = self.claim('C03'), self.claim('C24')
        self.assertEqual(first['expenses'][0]['gross_original'], '200.00')
        self.assertEqual(final['calculated_allowed_cents'], 25000)
        self.assertEqual([e['expense_id'] for e in final['expenses']], ['COST-03', 'COST-24'])
        self.assertEqual([e['filing_deadline'] for e in final['expenses']], ['2027-02-10'] * 2)
        self.assertEqual([e['first_submitted_date'] for e in final['expenses']], ['2026-09-01', '2026-09-08'])
        self.assertEqual(self.findings(final, 'prior_cost_obligation')[0]['status'], 'unresolved')
        self.assertNotIn('paid_cents', final)

    def test_c09_return_and_replacement_reviews(self):
        old, new = self.claim('C09'), self.claim('C09', 2)
        self.assertFalse(old['current_at_batch'])
        self.assertEqual(next(f for f in old['claim_review']['findings'] if f['code'] == 'review_budget_owner')['status'], 'blocked')
        self.assertEqual(new['trip_id'], 'T09B')
        self.assertEqual(new['calculated_allowed_cents'], 8000)
        self.assertEqual(len(new['claim_review']['selected_decisions']), 3)
        self.assertTrue(all('-2-claim-' in d for d in new['claim_review']['selected_decisions'].values()))
        stale = [e for e in new['claim_review']['imports'] if e['revision'] == 1]
        self.assertTrue(stale)
        self.assertTrue(all(e['status'] == 'blocked' for e in stale))

    def test_c18_original_cancellation_not_replacement_and_no_invented_finance(self):
        old, new = self.claim('C18'), self.claim('C18', 2)
        self.assertEqual(old['cancellation_ids'], ['TC018'])
        self.assertEqual(new['cancellation_ids'], [])
        self.assertEqual(new['claim_review']['selected_decisions'], {})
        self.assertTrue(any(i['severity'] == 'observation' for i in new['normalization_diagnostics']))
        hold = self.findings(new, 'original_request_finance_hold')[0]
        self.assertEqual((new['status'], hold['status']), ('blocked', 'blocked'))
        self.assertIn('travel-registers:Finance activity:row:21', hold['source_refs'])
        self.assertEqual(new['expenses'][0]['calculated_allowed_cents'], 10000)
        self.assertEqual(self.findings(new, 'travel_cancellation'), [])

    def test_c19_replacement_does_not_overwrite_gross_and_waiver_is_scoped(self):
        r1, r2, r3 = [self.claim('C19', i) for i in [1, 2, 3]]
        self.assertEqual([c['expenses'][0]['gross_original'] for c in [r1, r2, r3]], ['100.00'] * 3)
        self.assertEqual([c['calculated_allowed_cents'] for c in [r1, r2, r3]], [10000, 8000, 8000])
        self.assertEqual(self.findings(r2, 'travel_cancellation')[0]['status'], 'blocked')
        waiver = self.findings(r3, 'travel_cancellation')[0]
        self.assertEqual((waiver['status'], waiver['original_status'], waiver['cancellation_id']), ('supported', 'blocked', 'TC019'))
        self.assertEqual(len(r3['claim_review']['selected_decisions']), 3)
        self.assertEqual(r3['status'], 'blocked')  # Deferred Finance validation still holds.

    def test_c121_permit_only_cancellation_keeps_timely_original_permission(self):
        c = self.claim('C121', 2)
        self.assertEqual((c['trip_revision'], c['expenses'][0]['gross_original'], c['calculated_allowed_cents']), (1, '30.00', 2000))
        process = next(p for p in self.result['cancellations'] if p['cancellation_id'] == 'TC121')
        self.assertEqual(process['target_type'], 'permit')
        self.assertEqual(c['travel_cancellation_scope'], 'retired_permit_trip_active')
        self.assertEqual(self.findings(c, 'permit_timing')[0]['status'], 'supported')
        self.assertFalse(self.findings(c, 'permit_unapproved'))
        self.assertEqual(self.findings(c, 'travel_cancellation')[0]['status'], 'supported')
        self.assertEqual(len(c['claim_review']['selected_decisions']), 3)

    def test_missing_payment_c08_and_c114_never_becomes_zero(self):
        for ident, cost in [('C08', 'COST-08'), ('C114', 'COST-114-2')]:
            c = self.claim(ident)
            e = next(e for e in c['expenses'] if e['expense_id'] == cost)
            self.assertEqual(e['status'], 'unresolved')
            self.assertIsNone(e['allowed_original'])
            self.assertIsNone(e['calculated_allowed_cents'])
            self.assertIsNone(c['calculated_allowed_cents'])
        self.assertEqual(self.claim('C114')['expenses'][0]['calculated_allowed_cents'], 2000)

    def test_finance_exception_cannot_supply_missing_payment(self):
        def change(d):
            c = self.source_claim(d, 'C08')
            ex = deepcopy(self.source_claim(d, 'C19', 2)['finance_exception'])
            ex.update(claim_id='C08', revision=1, expense_id='COST-08', allowed_original_amount_observed='120.00')
            c['finance_exception'] = ex
        c = self.claim('C08', result=self.mutate(change))
        self.assertIsNone(c['calculated_allowed_cents'])
        self.assertEqual(self.findings(c, 'merchant_payment')[0]['status'], 'unresolved')

    def test_wrong_finance_actor_revision_cost_and_cancellation_not_waived(self):
        for field, value in [('actor', 'SUP-01'), ('revision', 1), ('expense_id', 'OTHER'), ('cancellation_id', 'TC018')]:
            with self.subTest(field=field):
                def change(d):
                    self.source_claim(d, 'C121', 2)['finance_exception'][field] = value
                c = self.claim('C121', 2, self.mutate(change))
                self.assertEqual(self.findings(c, 'travel_cancellation')[0]['status'], 'blocked')

    def test_correction_same_amount_invalidates_prior_reviews(self):
        def change(d):
            d['workbook']['Review ledger']['rows'] = [r for r in v.rows(d, 'Review ledger') if not
                (r['values']['Subject reference'] == 'C09' and r['values']['Revision'] == 2)]
        new = self.claim('C09', 2, self.mutate(change))
        self.assertEqual(new['calculated_allowed_cents'], 8000)
        self.assertEqual(new['claim_review']['selected_decisions'], {})

    def test_current_revision_with_old_packet_trip_is_invalid(self):
        def change(d):
            for r in v.rows(d, 'Review packets'):
                if r['values']['Decision reference'].startswith('D-C09-2-'):
                    r['values']['Trip reference'] = 'T09'
        self.assertEqual(self.claim('C09', 2, self.mutate(change))['claim_review']['selected_decisions'], {})

    def test_old_cancellation_context_and_preconfirmation_time_invalidates_reviews(self):
        for mode in ['packet', 'time']:
            def change(d):
                if mode == 'packet':
                    for r in v.rows(d, 'Review packets'):
                        if r['values']['Decision reference'].startswith('D-C121-2-'):
                            r['values']['Travel cancellation references'] = None
                else:
                    for r in v.rows(d, 'Review ledger'):
                        if r['values']['Subject reference'] == 'C121' and r['values']['Revision'] == 2:
                            r['values']['Decision time (UTC)'] = '2026-09-11T10:00:00Z'
            self.assertEqual(self.claim('C121', 2, self.mutate(change))['claim_review']['selected_decisions'], {})

    def test_wrong_role_stale_policy_and_future_decisions_not_authorization(self):
        for field, val in [('Reviewer', 'FIN-01'), ('Source revisions', ['POL-2026.1', 'SRC-D-3']), ('Decision time (UTC)', '2027-01-01T00:00:00Z')]:
            def change(d):
                for r in v.rows(d, 'Review ledger'):
                    if r['values']['Subject reference'] == 'C01':
                        r['values'][field] = val
            self.assertEqual(self.claim('C01', result=self.mutate(change))['claim_review']['selected_decisions'], {})

    def test_only_budget_and_supervisor_roles_may_collapse(self):
        c = self.claim('C04')
        selections = c['claim_review']['selected_decisions']
        self.assertEqual(selections['budget_owner'], selections['supervisor'])
        def change(d):
            for r in v.rows(d, 'Review ledger'):
                if r['values']['Subject reference'] == 'C04' and 'administration' in r['values']['Review roles']:
                    r['values']['Review roles'].append('supervisor')
        self.assertNotIn('administration', self.claim('C04', result=self.mutate(change))['claim_review']['selected_decisions'])

    def test_caps_units_and_unknown_category(self):
        capped = self.claim('C07')['expenses'][0]
        self.assertEqual((capped['gross_original'], capped['allowed_original'], capped['calculated_allowed_cents']), ('360.00', '300.0', 30000))
        self.assertEqual(self.claim('C15')['calculated_allowed_cents'], 0)
        lodging = next(c for c in self.result['claims'] if any(e['category'] == 'lodging' for e in c['expenses']))
        self.assertTrue(any(f['code'] == 'category_cap' and f['status'] == 'supported' for e in lodging['expenses'] for f in e['findings']))
        def change(d):
            receipt = next(r for r in d['receipts'] if r['receipt_id'] == self.source_claim(d, 'C01')['expenses'][0]['receipt_id'])
            receipt['category'] = 'unknown'
        c = self.claim('C01', result=self.mutate(change))
        self.assertIsNone(c['calculated_allowed_cents'])
        self.assertEqual(self.findings(c, 'category')[0]['status'], 'unresolved')
        def bad_units(d):
            next(r for r in d['receipts'] if r['receipt_id'] == self.source_claim(d, 'C01')['expenses'][0]['receipt_id'])['units'] = 0
        self.assertIsNone(self.claim('C01', result=self.mutate(bad_units))['calculated_allowed_cents'])

    def test_exact_fx_date_missing_rate_and_decimal_half_up(self):
        self.assertEqual(self.claim('C02')['calculated_allowed_cents'], 54000)
        self.assertEqual(v.cents(Decimal('1.005'), Decimal(1)), 101)
        def change(d):
            for r in v.rows(d, 'FX'):
                if r['values']['Currency'] == 'USD':
                    r['values']['Rate date'] = '2026-09-02'
        self.assertIsNone(self.claim('C02', result=self.mutate(change))['calculated_allowed_cents'])

    def test_deadline_clamps_inclusive_and_early_filing(self):
        self.assertEqual(str(v.deadline('2026-08-31')), '2026-10-31')
        self.assertEqual(str(v.deadline('2026-12-31')), '2027-02-28')
        self.assertEqual(self.findings(self.claim('C18', 2), 'late_filing')[0]['status'], 'supported')
        self.assertEqual(self.findings(self.claim('C12'), 'late_filing')[0]['status'], 'blocked')
        f = self.findings(self.claim('C12', 2), 'late_filing')[0]
        self.assertEqual((f['original_status'], f['status']), ('blocked', 'supported'))

    def test_correction_cannot_reset_unchanged_cost_filing_date(self):
        def change(d):
            c = self.source_claim(d, 'C19', 2)
            c['expenses'][0]['first_submitted_date'] = '2026-09-02'
            c['expenses'][0]['original_amount'] = '100.0'  # Formatting alone is not a new cost.
            c['submitted_date'] = '2026-09-02'
        c = self.claim('C19', 2, self.mutate(change))
        self.assertEqual(self.findings(c, 'initial_filing_preserved')[0]['status'], 'blocked')

    def test_unsupplied_batch_and_evidence_child_output_refused(self):
        with self.assertRaises(ValueError):
            v.evaluate(self.doc, self.report, 5)
        with patch.object(v, 'load_verified') as loader, self.assertRaises(ValueError):
            v.validate(RUN, NORMALIZED, RUN / 'validation-must-not-be-created')
        loader.assert_not_called()
        self.assertFalse((RUN / 'validation-must-not-be-created').exists())

    def test_director_strict_threshold_and_domestic_permits(self):
        def threshold(total):
            c = self.source_claim(self.doc, 'C01')
            t = next(r for r in v.rows(self.doc, 'Trips') if r['values']['Trip reference'] == 'T01')
            p = v.rows(self.doc, 'People')[0]
            return v.review(self.doc, c, t, p, 4, 'claim', Decimal(total))['required_roles']
        self.assertNotIn('director', threshold('1000.00'))
        self.assertIn('director', threshold('1000.01'))
        self.assertIsNone(self.claim('C01')['permit_review'])
        self.assertEqual(self.findings(self.claim('C01'), 'domestic_permit')[0]['status'], 'supported')
        self.assertIn('director', self.claim('C02')['permit_review']['required_roles'])
        self.assertNotIn('director', self.claim('C02')['claim_review']['required_roles'])

    def test_cancellation_batches_and_repeated_deliveries(self):
        early = v.evaluate(self.doc, self.report, 1)
        self.assertFalse(any(c['revision'] == 2 for c in early['claims']))
        self.assertEqual({c['business_state'] for c in early['cancellations']}, {'requested'})
        repeated = next(c for c in self.result['cancellations'] if c['cancellation_id'] == 'TC122')
        self.assertEqual((repeated['delivery_count'], repeated['event_count']), (3, 2))
        self.assertFalse(any(c['trip_id'] == 'T122' for c in self.result['claims']))
        permit = next(p for p in self.result['standalone_permit_reviews'] if p['subject_id'] == 'P122')
        self.assertEqual(len(permit['selected_decisions']), 3)

    def test_cancellation_wrong_actor_backdate_orphan_conflict_visible(self):
        for field, val in [('Acting employee or supervisor', 'FIN-01'), ('Effective time (UTC)', '2026-09-11T10:00:00Z'), ('Initiation activity reference', 'missing')]:
            def change(d):
                next(r for r in v.rows(d, 'Travel cancellations') if r['values']['Cancellation activity reference'] == 'TC121-confirmed')['values'][field] = val
            process = next(p for p in self.mutate(change)['cancellations'] if p['cancellation_id'] == 'TC121')
            self.assertEqual(process['business_state'], 'unresolved')
        def conflict(d):
            row = next(r for r in v.rows(d, 'Travel cancellations') if r['source']['row'] == 14)
            row['values']['Business reason'] = 'changed'
        process = next(p for p in self.mutate(conflict)['cancellations'] if p['cancellation_id'] == 'TC122')
        self.assertEqual(process['business_state'], 'unresolved')

    def test_same_day_permit_order_uncertain_and_late_permit_not_approved(self):
        for when, expected in [('2026-09-01T01:00:00Z', 'unresolved'), ('2026-09-02T01:00:00Z', 'blocked')]:
            def change(d):
                for r in v.rows(d, 'Review ledger'):
                    if r['values']['Subject reference'] == 'P02':
                        r['values']['Decision time (UTC)'] = when
            c = self.claim('C02', result=self.mutate(change))
            f = next(f for f in c['findings'] if f['code'] in ['permit_timing', 'late_permit'])
            self.assertEqual(f['status'], expected)

    def test_budget_supplied_only_no_double_subtraction(self):
        self.assertEqual(self.result['supplied_budget_context'][0]['supplied_ledger_available_cents'], 1500000)
        self.assertTrue(any(f['code'] == 'budget_completeness' and f['status'] == 'unresolved' for f in self.result['global_findings']))

    def test_source_references_resolve_and_no_finance_outputs(self):
        def walk(value):
            if isinstance(value, dict):
                for k, val in value.items():
                    if k == 'source_refs':
                        for ref in val:
                            self.assertIn(ref, self.result['source_index'])
                    elif k == 'rule_ref':
                        self.assertIn(val, self.result['source_index'])
                    else:
                        walk(val)
            elif isinstance(value, list):
                for val in value:
                    walk(val)
        walk(self.result)
        self.assertFalse({'requests', 'admitted_event_ids', 'paid_cents', 'balance_cents'} & self.result.keys())
        self.assertTrue(all(c['status'] in ('supported', 'blocked', 'unresolved') for c in self.result['claims']))

    def test_verified_input_rejects_changed_normalized_records(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            doc = deepcopy(self.doc); doc['claims'][0]['employee_id'] = 'OTHER'
            (p / 'records.v1.json').write_bytes(v.encoded(doc))
            (p / 'parsing-report.v1.json').write_bytes(v.encoded(self.report))
            with self.assertRaises(ValueError):
                v.load_verified(RUN, p)

    def test_versioned_output_deterministic_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / 'a', Path(directory) / 'b'
            v.validate(RUN, NORMALIZED, a)
            v.validate(RUN, NORMALIZED, b)
            self.assertEqual((a / 'findings.v1.json').read_bytes(), (b / 'findings.v1.json').read_bytes())
            with patch.object(v, 'load_verified') as loader, self.assertRaises(FileExistsError):
                v.validate(RUN, NORMALIZED, a)
            loader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
