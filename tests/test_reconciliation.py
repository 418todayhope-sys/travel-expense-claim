"""Finance admission/reconciliation regressions over retained and isolated inputs."""
from copy import deepcopy
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from reconciliation import reconcile as r
from validation import validate as v

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / 'artifacts/runs/omega4-live-20261020-attempt002'
NORMALIZED = ROOT / 'artifacts/normalizations/omega4-attempt002-normalization-v1'
VALIDATED = ROOT / 'artifacts/validations/omega4-attempt002-business-disposition-validation-v1'


class ReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, cls.report, cls.validated = r.load_verified(RUN, NORMALIZED, VALIDATED)
        cls.result = r.evaluate(cls.doc, cls.report, cls.validated)

    def request(self, ident, result=None):
        return next(q for q in (result or self.result)['requests'] if q['request_id'] == ident)

    def claim(self, ident, revision=1, result=None):
        return next(c for c in (result or self.result)['claims'] if (c['claim_id'], c['revision']) == (ident, revision))

    def event(self, ident, result=None):
        return next(e for e in (result or self.result)['finance_events'] if e['event_id'] == ident)

    def source_event(self, doc, ident):
        return next(row for row in v.rows(doc, 'Finance activity') if row['values']['Activity reference'] == ident)

    def mutate(self, change, batch=4):
        doc = deepcopy(self.doc)
        change(doc)
        return r.evaluate(doc, self.report, self.validated, batch)

    def append_event(self, doc, template, ident, **fields):
        row = deepcopy(self.source_event(doc, template))
        row['record_id'] = 'test:' + ident
        row['values'].update({'Activity reference': ident}, **fields)
        v.rows(doc, 'Finance activity').append(row)
        return row

    def test_retained_inventory_and_exact_totals(self):
        result = self.result
        self.assertEqual((len(result['finance_deliveries']), len(result['finance_events']), len(result['requests'])), (220, 219, 104))
        self.assertTrue(all(e['admission_status'] == 'admitted' for e in result['finance_events']))
        self.assertEqual(sum(q['admitted_settled_cents'] for q in result['requests']), 1206415)
        self.assertEqual(sum(q['admitted_refund_cents'] for q in result['requests']), 3000)
        self.assertEqual(sum(q['admitted_net_cents'] for q in result['requests']), 1203415)
        self.assertEqual(result['normalization_diagnostics'], self.report['issues'])
        self.assertEqual(len(result['normalization_diagnostics']), 18)
        self.assertEqual(sum(len(c['expenses']) for c in result['claims']), 208)

    def test_f_c01_repeated_delivery_contributes_once(self):
        event = self.event('F-C01-1')
        self.assertEqual(event['delivery_record_ids'], ['travel-registers:Finance activity:row:6', 'travel-registers:Finance activity:row:31'])
        self.assertEqual(len(event['repeated_delivery_record_ids']), 1)
        self.assertEqual(self.request('REQ-C01')['admitted_net_cents'], 10000)
        for batch in [2, 3, 4]:
            request = next(q for q in self.result['batch_views'][batch - 1]['requests'] if q['request_id'] == 'REQ-C01')
            self.assertEqual(request['admitted_net_cents'], 10000)

    def test_c03_c24_distinct_requests_and_conditional_shared_cost_exclusion(self):
        c03, c24 = self.claim('C03'), self.claim('C24')
        self.assertEqual((c03['gross_purchase_cents'], c24['gross_purchase_cents']), (20000, 25000))
        self.assertEqual(c24['policy_allowed_cents'], 25000)
        self.assertEqual(c24['incremental_policy_candidate_cents'], 5000)
        self.assertEqual(c24['prior_cost_candidates'][0]['prior_request_ids'], ['REQ-C03'])
        self.assertEqual(self.request('REQ-C24')['accepted_cents'], 5000)
        self.assertEqual(self.request('REQ-C24')['net_confirmed_settled_cents'], 5000)
        self.assertIsNone(c24['incremental_authorized_cents'])
        self.assertIsNone(c24['revision_net_confirmed_settled_cents'])

    def test_shared_cost_partial_prior_bundle_not_guessed(self):
        def change(doc):
            self.source_event(doc, 'F-C03-1')['values']['Amount (EUR)'] = '100.00'
        c24 = self.claim('C24', result=self.mutate(change))
        self.assertIsNone(c24['prior_cost_candidates'][0]['candidate_excluded_cents'])
        self.assertIsNone(c24['incremental_policy_candidate_cents'])

    def test_c09_correction_has_current_candidates_but_no_fabricated_revision(self):
        request = self.request('REQ-C09')
        self.assertEqual(request['first_acceptance_batch'], 3)
        self.assertEqual(request['basis_links']['candidate_revision'], 2)
        self.assertIsNone(request['basis_links']['attributed_revision'])
        self.assertEqual(request['basis_links']['observed_revision_candidates'], [1, 2])
        c = self.claim('C09', 2)
        self.assertEqual(c['trip_id'], 'T09B')
        self.assertEqual(len(c['selected_current_review_ids']), 3)
        self.assertFalse(any(f['code'] == 'decision_001_original_request_hold' for f in c['diagnostics']))
        self.assertEqual(request['net_confirmed_settled_cents'], 8000)
        self.assertNotEqual(c['payment_readiness'], 'ready')

    def test_c18_late_transfer_preserves_original_request_and_hold(self):
        request, event = self.request('REQ-C18'), self.event('F-C18-3')
        self.assertEqual((event['admission_status'], event['request_id'], event['amount_cents']), ('admitted', 'REQ-C18', 10000))
        self.assertEqual((request['original_accepted_cents'], request['accepted_cents'], request['admitted_net_cents']), (10000, 0, 10000))
        self.assertEqual(request['reconciliation_state'], 'overpaid_against_request')
        self.assertEqual(request['resolution_event_ids'], [])
        current = self.claim('C18', 2)
        self.assertEqual((current['payment_readiness'], current['selected_current_review_ids']), ('blocked', {}))
        self.assertEqual(current['cancellation_ids'], [])
        self.assertIsNone(current['revision_net_confirmed_settled_cents'])
        self.assertTrue(any(f['code'] == 'decision_001_original_request_hold' for f in current['diagnostics']))
        self.assertTrue(any(i['record_id'] == 'claim-updates:page:4:claim' for i in current['normalization_diagnostics']))

    def test_c19_adjustment_refund_resolution_separate_from_current_authority(self):
        request, current = self.request('REQ-C19'), self.claim('C19', 3)
        self.assertEqual((current['gross_purchase_cents'], current['policy_allowed_cents']), (10000, 8000))
        self.assertEqual((request['original_accepted_cents'], request['accepted_cents'], request['admitted_refund_cents'], request['net_confirmed_settled_cents']), (10000, 8000, 2000, 8000))
        self.assertEqual(self.event('F-C19-3')['original_event_id'], 'F-C19-1')
        self.assertEqual(request['resolution_assessment']['event_id'], 'F-C19-4')
        self.assertTrue(request['resolution_assessment']['request_amounts_agree'])
        self.assertEqual(current['payment_readiness'], 'blocked')
        self.assertEqual((current['expenses'][0]['gross_original'], current['expenses'][0]['policy_allowed_cents']), ('100.00', 8000))
        self.assertIsNone(current['expenses'][0]['net_confirmed_settled_cents'])
        self.assertIn('unresolved', request['resolution_assessment']['current_claim_scope'])

    def test_c121_preacceptance_permit_cancellation_not_new_finance_resolution(self):
        request, c = self.request('REQ-C121'), self.claim('C121', 2)
        self.assertEqual((c['gross_purchase_cents'], c['policy_allowed_cents'], request['accepted_cents'], request['net_confirmed_settled_cents']), (3000, 2000, 2000, 2000))
        self.assertEqual(c['travel_cancellation_scope'], 'retired_permit_trip_active')
        process = next(p for p in self.result['travel_cancellations'] if p['cancellation_id'] == 'TC121')
        self.assertEqual(process['separate_finance_resolution_requirement'], 'not_imposed_by_business_cancellation_before_observed_acceptance')
        self.assertFalse(any(f['code'] == 'decision_001_original_request_hold' for f in c['diagnostics']))

    def test_tc122_confirmed_is_independent_and_never_finance_money(self):
        process = next(p for p in self.result['travel_cancellations'] if p['cancellation_id'] == 'TC122')
        self.assertEqual((process['delivery_count'], process['event_count']), (3, 2))
        self.assertEqual(process['finance_event_ids'], [])
        self.assertEqual(process['affected_claim_revisions'], [])
        self.assertEqual(process['money_effect_from_business_cancellation_cents'], 0)
        self.assertNotIn('TC122-confirmed', {e['event_id'] for e in self.result['finance_events']})

    def test_conflicting_redelivery_preserves_admitted_money_and_earlier_batch(self):
        def change(doc):
            next(row for row in v.rows(doc, 'Finance activity') if row['source']['row'] == 31)['values']['Amount (EUR)'] = '999.00'
        result = self.mutate(change)
        self.assertEqual(self.request('REQ-C01', result)['admitted_net_cents'], 10000)
        self.assertIsNone(self.request('REQ-C01', result)['net_confirmed_settled_cents'])
        self.assertEqual(self.event('F-C01-1', result)['admission_status'], 'admitted')
        earlier = next(q for q in result['batch_views'][1]['requests'] if q['request_id'] == 'REQ-C01')
        self.assertEqual(earlier['net_confirmed_settled_cents'], 10000)

    def test_same_batch_conflict_has_no_arbitrary_first_payload(self):
        def change(doc):
            self.append_event(doc, 'F-C02-1', 'F-C02-1', **{'Amount (EUR)': '999.00'})
        result = self.mutate(change)
        self.assertEqual(self.event('F-C02-1', result)['admission_status'], 'unresolved')
        self.assertEqual(self.request('REQ-C02', result)['admitted_net_cents'], 0)
        self.assertIsNone(self.request('REQ-C02', result)['net_confirmed_settled_cents'])

    def test_invalid_actor_payee_currency_amount_and_time_not_admitted(self):
        changes = [('Finance officer', 'SUP-01'), ('Payee ID', 'OTHER'), ('Currency', 'USD'),
                   ('Amount (EUR)', '1.001'), ('Amount (EUR)', '0'), ('Amount (EUR)', '-1'),
                   ('Activity time (UTC)', '2027-01-01T00:00:00Z')]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                result = self.mutate(lambda doc: self.source_event(doc, 'F-C02-1')['values'].update({field: value}))
                self.assertEqual(self.event('F-C02-1', result)['admission_status'], 'unresolved')
                self.assertIsNone(self.request('REQ-C02', result)['net_confirmed_settled_cents'])

    def test_missing_acceptance_preserves_unresolved_original_request(self):
        def change(doc):
            doc['workbook']['Finance activity']['rows'] = [row for row in v.rows(doc, 'Finance activity') if row['values']['Activity reference'] != 'F-C02-accepted']
        result = self.mutate(change)
        request = self.request('REQ-C02', result)
        self.assertEqual(request['acceptance_status'], 'unresolved')
        self.assertIsNone(request['accepted_cents'])
        self.assertIsNone(request['net_confirmed_settled_cents'])
        self.assertEqual(self.event('F-C02-1', result)['admission_status'], 'unresolved')

    def test_late_acceptance_dependency_rechecked_without_rewriting_history(self):
        def change(doc):
            self.source_event(doc, 'F-C02-accepted')['values']['Arrival batch'] = 3
        result = self.mutate(change)
        self.assertEqual(self.event('F-C02-1', result)['admitted_in_batch'], 3)
        earlier = next(q for q in result['batch_views'][1]['requests'] if q['request_id'] == 'REQ-C02')
        self.assertIsNone(earlier['net_confirmed_settled_cents'])
        self.assertEqual(self.request('REQ-C02', result)['net_confirmed_settled_cents'], 54000)

    def test_request_identity_mismatch_and_outcome_before_acceptance(self):
        for field, value in [('Claim reference', 'C03'), ('Activity time (UTC)', '2026-09-10T12:00:00Z')]:
            result = self.mutate(lambda doc: self.source_event(doc, 'F-C02-1')['values'].update({field: value}))
            self.assertEqual(self.event('F-C02-1', result)['admission_status'], 'unresolved')

    def test_refund_requires_real_original_transfer_and_limits(self):
        for field, value in [('Original activity reference', 'F-C19-accepted'), ('Original activity reference', 'F-C20-1'),
                             ('Original activity reference', None), ('Amount (EUR)', '100.01'),
                             ('Activity time (UTC)', '2026-09-11T12:00:00Z')]:
            result = self.mutate(lambda doc: self.source_event(doc, 'F-C19-3')['values'].update({field: value}))
            self.assertEqual(self.event('F-C19-3', result)['admission_status'], 'unresolved')
            request = self.request('REQ-C19', result)
            self.assertEqual(request['admitted_net_cents'], 10000)
            self.assertIsNone(request['net_confirmed_settled_cents'])
            self.assertFalse(request['resolution_assessment']['request_amounts_agree'])

    def test_equal_time_excess_refunds_are_all_held(self):
        def change(doc):
            self.append_event(doc, 'F-C19-3', 'REFUND-EXCESS', **{'Amount (EUR)': '90.00'})
        result = self.mutate(change)
        self.assertEqual(self.event('F-C19-3', result)['admission_status'], 'unresolved')
        self.assertEqual(self.event('REFUND-EXCESS', result)['admission_status'], 'unresolved')
        self.assertEqual(self.request('REQ-C19', result)['admitted_refund_cents'], 0)

    def test_partial_failure_and_authorized_retry(self):
        partial = next(q for q in self.result['batch_views'][1]['requests'] if q['request_id'] == 'REQ-C16')
        self.assertEqual((partial['net_confirmed_settled_cents'], partial['accepted_minus_net_cents']), (4000, 6000))
        self.assertEqual(partial['reconciliation_state'], 'partial_settlement')
        failed = next(q for q in self.result['batch_views'][1]['requests'] if q['request_id'] == 'REQ-C17')
        self.assertEqual(failed['admitted_net_cents'], 0)
        self.assertIsNone(failed['net_confirmed_settled_cents'])
        self.assertEqual(self.request('REQ-C17')['net_confirmed_settled_cents'], 10000)

    def test_missing_retry_permission_does_not_erase_reported_transfer(self):
        def change(doc):
            doc['workbook']['Finance activity']['rows'] = [row for row in v.rows(doc, 'Finance activity') if row['values']['Activity reference'] != 'F-C17-2']
        request = self.request('REQ-C17', self.mutate(change))
        self.assertEqual(request['admitted_net_cents'], 10000)
        self.assertTrue(any(d['code'] == 'retry_authority' for d in request['diagnostics']))

    def test_missing_finance_and_payment_evidence_remain_unknown(self):
        for ident in ['C08', 'C114']:
            claim = self.claim(ident)
            self.assertIsNone(claim['policy_allowed_cents'])
            self.assertIsNone(claim['revision_accepted_cents'])
            self.assertIsNone(claim['revision_net_confirmed_settled_cents'])
            self.assertTrue(any(d['code'] == 'missing_finance_request' for d in claim['diagnostics']))

    def test_wrong_current_reviews_never_authorize_after_finance_settlement(self):
        def change(doc):
            for row in v.rows(doc, 'Review ledger'):
                if row['values']['Subject reference'] == 'C09' and row['values']['Revision'] == 2:
                    row['values']['Reviewer'] = 'FIN-01'
        claim = self.claim('C09', 2, self.mutate(change))
        self.assertEqual(claim['selected_current_review_ids'], {})
        self.assertIsNone(claim['incremental_authorized_cents'])
        self.assertNotEqual(claim['payment_readiness'], 'ready')

    def test_finance_resolution_never_changes_accepted_commitment_by_itself(self):
        result = self.mutate(lambda doc: self.source_event(doc, 'F-C19-4')['values'].update({'Obligation (EUR)': '70.00'}))
        self.assertEqual(self.request('REQ-C19', result)['accepted_cents'], 8000)
        self.assertFalse(self.request('REQ-C19', result)['resolution_assessment']['request_amounts_agree'])

    def test_equal_time_adjustments_do_not_choose_an_arbitrary_target(self):
        def change(doc):
            for ident, amount in [('ADJ-A', '80.00'), ('ADJ-B', '90.00')]:
                self.append_event(doc, 'F-C19-2', ident, **{'Request reference': 'REQ-C01', 'Claim reference': 'C01', 'Obligation (EUR)': amount})
        request = self.request('REQ-C01', self.mutate(change))
        self.assertIsNone(request['accepted_cents'])
        self.assertEqual(request['admitted_net_cents'], 10000)
        self.assertTrue(any(d['code'] == 'ambiguous_obligation_time' for d in request['diagnostics']))

    def test_late_earlier_adjustment_does_not_restore_cancelled_request(self):
        def change(doc):
            self.append_event(doc, 'F-C19-2', 'EARLIER-ADJUSTMENT', **{'Request reference': 'REQ-C18', 'Claim reference': 'C18', 'Arrival batch': 4, 'Activity time (UTC)': '2026-09-12T13:00:00Z'})
        request = self.request('REQ-C18', self.mutate(change))
        self.assertEqual(request['accepted_cents'], 0)
        self.assertTrue(request['cancelled'])

    def test_later_transfer_reopens_resolution_without_erasing_it(self):
        def change(doc):
            self.append_event(doc, 'F-C19-1', 'LATE-C19', **{'Arrival batch': 4, 'Amount (EUR)': '1.00', 'Activity time (UTC)': '2026-09-15T12:00:00Z'})
        request = self.request('REQ-C19', self.mutate(change))
        self.assertEqual(request['net_confirmed_settled_cents'], 8100)
        self.assertEqual(request['resolution_event_ids'], ['F-C19-4'])
        self.assertFalse(request['resolution_assessment']['request_amounts_agree'])
        self.assertTrue(any(d['code'] == 'resolution_reopened' for d in request['diagnostics']))

    def test_row_order_is_not_finance_authority(self):
        def change(doc):
            random.Random(42).shuffle(doc['workbook']['Finance activity']['rows'])
        shuffled = self.mutate(change)
        self.assertEqual(shuffled, self.result)

    def test_exact_cents_never_rounds_finance_facts(self):
        self.assertEqual(r.exact_cents('1.01', True), 101)
        self.assertEqual(r.exact_cents('0'), 0)
        for val in ['1.001', 'NaN', 'Infinity', '-1', None]:
            self.assertIsNone(r.exact_cents(val))

    def test_source_refs_resolve_and_no_final_submission_outputs(self):
        def walk(value):
            if isinstance(value, dict):
                for key, val in value.items():
                    if key in ('source_refs', 'rule_refs'):
                        for ref in val:
                            self.assertIn(ref, self.result['source_index'])
                    else:
                        walk(val)
            elif isinstance(value, list):
                for val in value:
                    walk(val)
        walk(self.result)
        self.assertTrue(all(c['payment_readiness'] != 'ready' for c in self.result['claims']))

    def test_tampered_validation_and_binding_rejected(self):
        for mode in ['core', 'summary', 'binding']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                saved = deepcopy(self.validated)
                if mode == 'core':
                    saved['claims'][0]['calculated_allowed_cents'] = 999
                elif mode == 'summary':
                    saved['summary']['current_claims'] = 1
                else:
                    saved['input_bindings'] = saved['input_bindings'][:2]
                target = Path(directory)
                (target / 'findings.v1.json').write_bytes(v.encoded(saved))
                with self.assertRaises(ValueError):
                    r.load_verified(RUN, NORMALIZED, target)

    def test_versioned_replay_deterministic_and_no_overwrite_or_evidence_child(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'first', Path(directory) / 'second'
            r.reconcile(RUN, NORMALIZED, VALIDATED, first)
            r.reconcile(RUN, NORMALIZED, VALIDATED, second)
            self.assertEqual((first / 'reconciliation.v1.json').read_bytes(), (second / 'reconciliation.v1.json').read_bytes())
            self.assertEqual([p.name for p in first.iterdir()], ['reconciliation.v1.json'])
            with patch.object(r, 'load_verified') as loader, self.assertRaises(FileExistsError):
                r.reconcile(RUN, NORMALIZED, VALIDATED, first)
            loader.assert_not_called()
        with patch.object(r, 'load_verified') as loader, self.assertRaises(ValueError):
            r.reconcile(RUN, NORMALIZED, VALIDATED, RUN / 'must-not-write')
        loader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
