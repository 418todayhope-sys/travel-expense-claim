"""Opt-in ordinary closure over retained C01 evidence; mutations are isolated.

No synthetic mutation is written into retained records or treated as an actual
stakeholder decision. Existing default evaluation remains deliberately unchanged.
"""
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from validation import validate as v
from reconciliation import reconcile as r
from operator_delivery import build as b

ROOT = Path(__file__).resolve().parent.parent
A = ROOT / 'artifacts/runs/omega4-live-20261020-attempt002'
N = ROOT / 'artifacts/normalizations/omega4-attempt002-normalization-v1'


class OrdinaryClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, cls.report = v.load_verified(A, N)
        cls.validation = v.evaluate(cls.doc, cls.report, ordinary_claim_ids=['C01'])
        cls.result = r.evaluate(cls.doc, cls.report, cls.validation)
        cls.before = r.evaluate(cls.doc, cls.report, v.evaluate(cls.doc, cls.report))

    def claim(self, result, ident='C01', revision=1):
        return next(c for c in result['claims'] if (c['claim_id'], c['revision']) == (ident, revision))

    def snapshot(self, result, doc=None):
        doc = doc or self.doc
        projected, cw = b.cancellation_projection(doc, result, [])
        active = b.active_work(doc, result, cw)
        return b.snapshot(result, doc, self.report, 'isolated-ordinary-test',
                          {'path': 'sources.json', 'sha256': '0' * 64}, None,
                          {'path': 'queue/004.json', 'sha256': '0' * 64}, active, projected)

    def mutated(self, change, targets=('C01',), report=None):
        doc = deepcopy(self.doc)
        change(doc)
        report = report or self.report
        validation = v.evaluate(doc, report, ordinary_claim_ids=targets)
        return doc, r.evaluate(doc, report, validation)

    def assert_held(self, change):
        doc, result = self.mutated(change)
        self.assertTrue(all('ordinary_closure' not in c for c in result['claims'] if c['claim_id'] == 'C01'))
        self.assertEqual(self.claim(self.snapshot(result, doc))['status'], 'held')
        return result

    def approval(self, doc, role='supervisor'):
        return next(x for x in v.rows(doc, 'Review ledger') if x['values']['Subject reference'] == 'C01'
                    and role in x['values']['Review roles'])

    def event(self, doc, ident='F-C01-1'):
        return next(x for x in v.rows(doc, 'Finance activity') if x['values']['Activity reference'] == ident)

    def extra_event(self, doc, kind, ident, **fields):
        row = deepcopy(self.event(doc, 'F-C01-accepted'))
        row['record_id'] = 'isolated:' + ident
        row['values'].update({'Activity reference': ident, 'Activity type': kind, 'Arrival batch': 3,
                              'Activity time (UTC)': '2026-09-13T12:00:00Z'}, **fields)
        v.rows(doc, 'Finance activity').append(row)

    def test_c01_source_join_and_snapshot_csv_close_without_new_payment(self):
        before = self.claim(self.snapshot(self.before))
        after = self.claim(self.snapshot(self.result))
        self.assertEqual((before['status'], before['known_paid_cents']), ('held', None))
        self.assertEqual((after['status'], after['allowed_cents'], after['known_paid_cents'], after['balance_cents']),
                         ('closed-reimbursed', 10000, 10000, 0))
        c = self.claim(self.result)
        self.assertEqual(c['payment_readiness'], 'settled_no_new_payment')
        self.assertEqual(c['incremental_authorized_cents'], 0)
        proof = c['ordinary_closure']
        self.assertEqual((proof['revision'], proof['expense_id'], proof['request_id']), (1, 'COST-01', 'REQ-C01'))
        self.assertEqual(len(proof['decision_ids']), 3)
        self.assertIn('travel-registers:Review packets:row:7', proof['source_refs'])
        rows = list(csv.DictReader(io.StringIO(b.claims_csv(self.snapshot(self.result)).decode())))
        row = next(c for c in rows if c['claim_id'] == 'C01')
        self.assertEqual(list(row), b.CSV_FIELDS)
        self.assertEqual((row['paid_cents'], row['balance_cents']), ('10000', '0'))

    def test_no_automatic_closure_or_changes_to_other_claims(self):
        a = [c for c in self.before['claims'] if c['claim_id'] != 'C01']
        z = [c for c in self.result['claims'] if c['claim_id'] != 'C01']
        self.assertEqual(a, z)
        snap = self.snapshot(self.result)
        self.assertEqual(snap['actual_financial_closure_count'], 1)
        self.assertTrue(all(c['status'] == 'held' for c in snap['claims'] if c['claim_id'] != 'C01'))
        self.assertEqual(self.before['finance_events'], self.result['finance_events'])
        self.assertEqual(self.before['finance_deliveries'], self.result['finance_deliveries'])

    def test_default_reconciliation_is_identical_to_preserved_result(self):
        path = ROOT / 'artifacts/reconciliations/omega4-attempt002-business-disposition-reconciliation-v1/reconciliation.v1.json'
        old = json.loads(path.read_bytes())
        self.assertEqual(self.before, {k: x for k, x in old.items() if k not in ('summary', 'input_bindings')})

    def test_package_unknowns_and_normalization_diagnostics_are_not_waived(self):
        self.assertEqual(self.before['validation_global_findings'], self.result['validation_global_findings'])
        self.assertEqual(self.result['normalization_diagnostics'], self.report['issues'])
        self.assertEqual(len(self.report['issues']), 18)
        self.assertEqual(self.claim(self.result)['ordinary_closure']['package_certification'], 'unresolved')
        snap = self.snapshot(self.result)
        self.assertTrue(any(i['subject_type'] == 'package' and i['code'] == 'policy_provenance' for i in snap['issues']))

    def test_exact_duplicate_settlement_deliveries_count_once(self):
        def change(doc):
            row = deepcopy(self.event(doc)); row['record_id'] = 'isolated:repeat'
            row['values']['Arrival batch'] = 4
            v.rows(doc, 'Finance activity').append(row)
        _, result = self.mutated(change)
        self.assertIn('ordinary_closure', self.claim(result))
        self.assertEqual(self.claim(result)['revision_net_confirmed_settled_cents'], 10000)
        event = next(e for e in result['finance_events'] if e['event_id'] == 'F-C01-1')
        self.assertEqual(len(event['delivery_record_ids']), 3)

    def test_no_closure_before_settlement_arrival(self):
        result = r.evaluate(self.doc, self.report, self.validation, 1)
        self.assertNotIn('ordinary_closure', self.claim(result))
        self.assertEqual(self.claim(self.snapshot(result))['status'], 'held')
        self.assertIn('ordinary_closure', self.claim(r.evaluate(self.doc, self.report, self.validation, 2)))

    def test_corrected_claim_and_future_competing_revision_stay_held(self):
        def change(doc):
            c = deepcopy(next(c for c in doc['claims'] if c['claim_id'] == 'C01'))
            c.update(revision=2, arrival_batch=4, record_id='isolated:C01:r2')
            doc['claims'].append(c)
        doc, result = self.mutated(change)
        self.assertFalse(any(c.get('ordinary_closure') for c in result['claims'] if c['claim_id'] == 'C01'))
        self.assertEqual(self.claim(self.snapshot(result, doc), revision=2)['status'], 'held')
        # Even an earlier projection cannot assert uniqueness across a known correction.
        validation = v.evaluate(doc, self.report, ordinary_claim_ids=['C01'])
        self.assertNotIn('ordinary_closure', self.claim(r.evaluate(doc, self.report, validation, 2)))

    def test_multiple_costs_are_outside_narrow_path(self):
        def change(doc):
            c = next(c for c in doc['claims'] if c['claim_id'] == 'C01')
            e = deepcopy(c['expenses'][0]); e.update(expense_id='isolated:second-cost', record_id='isolated:second-cost')
            c['expenses'].append(e)
        self.assert_held(change)

    def test_shared_cost_identity_requires_separate_reconciliation(self):
        def change(doc):
            c = next(c for c in doc['claims'] if c['claim_id'] == 'C01')
            next(c for c in doc['claims'] if c['claim_id'] == 'C08')['expenses'].append(deepcopy(c['expenses'][0]))
        self.assert_held(change)

    def test_missing_approval(self):
        self.assert_held(lambda doc: v.rows(doc, 'Review ledger').remove(self.approval(doc)))

    def test_wrong_actor_is_not_current_authority(self):
        self.assert_held(lambda doc: self.approval(doc)['values'].update(Reviewer='FIN-01'))

    def test_conflicting_current_role_responses(self):
        def change(doc):
            row = deepcopy(self.approval(doc)); old = row['values']['Decision reference']
            row['record_id'] = 'isolated:conflicting-review'
            row['values'].update({'Decision reference': 'isolated:conflicting-review', 'Outcome': 'reject'})
            v.rows(doc, 'Review ledger').append(row)
            p = deepcopy(next(p for p in v.rows(doc, 'Review packets') if p['values']['Decision reference'] == old))
            p['record_id'] = 'isolated:conflicting-packet'; p['values']['Decision reference'] = 'isolated:conflicting-review'
            v.rows(doc, 'Review packets').append(p)
        self.assert_held(change)

    def test_acceptance_cannot_precede_current_approval(self):
        self.assert_held(lambda doc: self.approval(doc)['values'].update({'Decision time (UTC)': '2026-09-13T12:00:00Z'}))

    def test_missing_packet(self):
        def change(doc):
            ident = self.approval(doc)['values']['Decision reference']
            v.rows(doc, 'Review packets')[:] = [p for p in v.rows(doc, 'Review packets') if p['values']['Decision reference'] != ident]
        self.assert_held(change)

    def test_unresolved_competing_original_request(self):
        self.assert_held(lambda doc: self.extra_event(doc, 'accepted', 'isolated:other-original', **{'Request reference': 'isolated:other-request'}))

    def test_adjustment_without_required_finance_resolution(self):
        result = self.assert_held(lambda doc: self.extra_event(doc, 'adjustment', 'isolated:adjustment'))
        self.assertNotIn('ordinary_closure', self.claim(result))

    def test_exception_is_not_an_ordinary_closure_even_if_amount_matches(self):
        def change(doc):
            c = next(c for c in doc['claims'] if c['claim_id'] == 'C01')
            c['finance_exception'] = deepcopy(next(c['finance_exception'] for c in doc['claims'] if c.get('finance_exception')))
            c['finance_exception'].update(expense_id='COST-01', claim_id='C01', revision=1, allowed_original_amount_observed='100.00')
        self.assert_held(change)

    def test_conflicting_settlement_duplicate(self):
        self.assert_held(lambda doc: next(x for x in v.rows(doc, 'Finance activity') if x['record_id'].endswith(':31'))['values'].update({'Amount (EUR)': '101.00'}))

    def test_mismatched_acceptance(self):
        self.assert_held(lambda doc: self.event(doc, 'F-C01-accepted')['values'].update({'Obligation (EUR)': '101.00'}))

    def test_missing_settlement_does_not_mean_known_zero(self):
        def change(doc):
            v.rows(doc, 'Finance activity')[:] = [x for x in v.rows(doc, 'Finance activity') if x['values']['Activity reference'] != 'F-C01-1']
        result = self.assert_held(change)
        self.assertIsNone(self.claim(result)['revision_net_confirmed_settled_cents'])

    def test_missing_merchant_payment(self):
        self.assert_held(lambda doc: v.rows(doc, 'Merchant payments').__setitem__(slice(None), [r for r in v.rows(doc, 'Merchant payments') if r['values']['Expense reference'] != 'COST-01']))

    def test_corrected_cancellation_cases_cannot_opt_in_past_finance_holds(self):
        _, result = self.mutated(lambda doc: None, targets=('C01', 'C09', 'C18', 'C19', 'C121', 'C24'))
        self.assertEqual([c['claim_id'] for c in result['claims'] if c.get('ordinary_closure')], ['C01'])
        for cid in ['C18', 'C19']:
            self.assertTrue(any(d['code'] == 'decision_001_original_request_hold' for c in result['claims'] if c['claim_id'] == cid for d in c['diagnostics']))

    def test_snapshot_guard_rejects_amount_or_proof_tampering(self):
        for field, value in [('known_paid_cents', 20000), ('ordinary_closure', None), ('decision_ids_are_authorization', False)]:
            snap = deepcopy(self.snapshot(self.result)); self.claim(snap)[field] = value
            with self.assertRaises(ValueError):
                b.check_snapshot(snap)

    def test_new_or_blocked_global_requirement_is_not_waived(self):
        original = v.evaluate
        def evaluate(*args, **kwargs):
            result = original(*args, **kwargs)
            result['global_findings'].append(v.finding('isolated_new_requirement', 'blocked',
                'Isolated new global requirement', ['policy:clock'], 'clock'))
            return result
        with patch.object(v, 'evaluate', side_effect=evaluate):
            self.assert_held(lambda doc: None)

    def test_create_only_versioned_stages_and_standalone_operator_verification(self):
        with tempfile.TemporaryDirectory(prefix='omega4-ordinary-integration-') as tmp:
            root = Path(tmp)
            validation, recon, operator = [root / p for p in ('validation', 'reconciliation', 'operator')]
            v.validate(A, N, validation, ordinary_claim_ids=['C01'])
            r.reconcile(A, N, validation, recon)
            b.build(A, N, validation, recon, operator, 'isolated-ordinary-integration')
            checked = b.verify(operator)
            self.assertEqual((checked['verified_snapshots'], checked['actual_financial_closures']), (4, 1))
            snap = json.loads((operator / 'batches/004.json').read_bytes())
            self.assertEqual(self.claim(snap)['status'], 'closed-reimbursed')
            self.assertEqual(self.claim(json.loads((operator / 'batches/001.json').read_bytes()))['status'], 'held')
            old = (operator / 'batches/004.json').read_bytes()
            with self.assertRaises(FileExistsError):
                b.build(A, N, validation, recon, operator, 'isolated-ordinary-integration')
            self.assertEqual((operator / 'batches/004.json').read_bytes(), old)


if __name__ == '__main__':
    unittest.main()
