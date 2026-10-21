"""Business disposition is evidenced per revision, independently of financial holds."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import unittest

from validation import validate as v
from reconciliation import reconcile as r
from operator_delivery import build as b

ROOT = Path(__file__).resolve().parent.parent
A = ROOT / 'artifacts/runs/omega4-live-20261020-attempt002'
N = ROOT / 'artifacts/normalizations/omega4-attempt002-normalization-v1'
LATEST = ROOT / 'artifacts/runs/omega4-attempt002-business-disposition-shared-blockers-v1'


class BusinessDispositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, cls.report = v.load_verified(A, N)
        cls.validation = v.evaluate(cls.doc, cls.report)

    def claim(self, result, ident, revision=1):
        return next(c for c in result['claims'] if (c['claim_id'], c['revision']) == (ident, revision))

    def test_c13_explicit_withdrawal_reason_and_exact_evidence(self):
        d = self.claim(self.validation, 'C13')['business_disposition']
        self.assertEqual((d['value'], d['evidence_status'], d['reason']),
                         ('withdrawn', 'supported', 'Employee withdrew before review.'))
        self.assertEqual(d['source_refs'], ['initial-claims:page:13:claim'])
        self.assertEqual(d['decision_ids'], [])

    def test_c14_admitted_current_budget_owner_rejection(self):
        d = self.claim(self.validation, 'C14')['business_disposition']
        self.assertEqual((d['value'], d['reason']), ('rejected', 'Client work was cancelled.'))
        self.assertEqual(d['decision_ids'], ['D-C14-1-claim-budget_owner-1'])
        for ref in ['travel-registers:Review ledger:row:40', 'travel-registers:Review packets:row:40',
                    'travel-registers:People:row:6', 'initial-claims:page:14:claim']:
            self.assertIn(ref, d['source_refs'])

    def test_no_disposition_inferred_from_absence_or_missing_reason(self):
        self.assertIsNone(self.claim(self.validation, 'C08')['business_disposition']['value'])
        doc = deepcopy(self.doc)
        next(c for c in doc['claims'] if c['claim_id'] == 'C13')['raw_fields']['Claim reason'] = ''
        self.assertIsNone(self.claim(v.evaluate(doc, self.report), 'C13')['business_disposition']['value'])

    def test_later_revisions_do_not_inherit_withdrawal_or_rejection(self):
        doc = deepcopy(self.doc)
        for ident in ['C13', 'C14']:
            c = deepcopy(next(c for c in doc['claims'] if c['claim_id'] == ident))
            c.update(revision=2, arrival_batch=4, record_id=c['record_id'] + ':isolated-r2', status_observed='submitted')
            c['raw_fields'].update(Status='submitted', **{'Claim reason': 'Isolated later revision'})
            doc['claims'].append(c)
        result = v.evaluate(doc, self.report)
        for ident, value in [('C13', 'withdrawn'), ('C14', 'rejected')]:
            self.assertEqual(self.claim(result, ident)['business_disposition']['value'], value)
            self.assertIsNone(self.claim(result, ident, 2)['business_disposition']['value'])
            self.assertFalse(self.claim(result, ident)['current_at_batch'])
        self.assertEqual(self.claim(v.evaluate(doc, self.report, 3), 'C14')['business_disposition']['value'], 'rejected')

    def test_wrong_role_rejection_supplies_no_disposition(self):
        doc = deepcopy(self.doc)
        row = next(x for x in v.rows(doc, 'Review ledger') if x['record_id'].endswith(':40'))
        row['values']['Reviewer'] = 'SUP-01'
        result = v.evaluate(doc, self.report)
        self.assertIsNone(self.claim(result, 'C14')['business_disposition']['value'])

    def test_equal_time_conflicting_role_replies_unresolved(self):
        doc = deepcopy(self.doc)
        row = deepcopy(next(x for x in v.rows(doc, 'Review ledger') if x['record_id'].endswith(':40')))
        old = row['values']['Decision reference']; new = 'isolated-conflict'
        row['record_id'] += ':isolated'; row['values'].update({'Decision reference': new, 'Outcome': 'approve'})
        doc['workbook']['Review ledger']['rows'].append(row)
        packet = deepcopy(next(x for x in v.rows(doc, 'Review packets') if x['values']['Decision reference'] == old))
        packet['record_id'] += ':isolated'; packet['values']['Decision reference'] = new
        doc['workbook']['Review packets']['rows'].append(packet)
        d = self.claim(v.evaluate(doc, self.report), 'C14')['business_disposition']
        self.assertEqual((d['value'], d['evidence_status']), (None, 'unresolved'))
        self.assertIn('ambiguous', d['reason'])

    def test_return_does_not_imply_rejection_or_approval(self):
        doc = deepcopy(self.doc)
        row = next(x for x in v.rows(doc, 'Review ledger') if x['record_id'].endswith(':40'))
        row['values'].update({'Outcome': 'return', 'Reason': 'Clarify purpose', 'Repair requested': 'Supply purpose'})
        d = self.claim(v.evaluate(doc, self.report), 'C14')['business_disposition']
        self.assertIsNone(d['value'])

    def test_later_valid_response_supersedes_only_at_its_arrival(self):
        doc = deepcopy(self.doc)
        row = deepcopy(next(x for x in v.rows(doc, 'Review ledger') if x['record_id'].endswith(':40')))
        old = row['values']['Decision reference']; new = 'isolated-later-response'
        row['record_id'] += ':isolated-later'
        row['values'].update({'Decision reference': new, 'Outcome': 'approve',
                              'Reason': 'Isolated supplied later response', 'Arrival batch': 2,
                              'Decision time (UTC)': '2026-09-04T12:00:00Z'})
        doc['workbook']['Review ledger']['rows'].append(row)
        packet = deepcopy(next(x for x in v.rows(doc, 'Review packets') if x['values']['Decision reference'] == old))
        packet['record_id'] += ':isolated-later'; packet['values']['Decision reference'] = new
        doc['workbook']['Review packets']['rows'].append(packet)
        self.assertEqual(self.claim(v.evaluate(doc, self.report, 1), 'C14')['business_disposition']['value'], 'rejected')
        self.assertIsNone(self.claim(v.evaluate(doc, self.report, 2), 'C14')['business_disposition']['value'])

    def test_conflicting_withdrawal_and_admitted_rejection_requires_clarification(self):
        doc = deepcopy(self.doc)
        next(c for c in doc['claims'] if c['claim_id'] == 'C14')['status_observed'] = 'withdrawn'
        d = self.claim(v.evaluate(doc, self.report), 'C14')['business_disposition']
        self.assertEqual((d['value'], d['evidence_status']), (None, 'unresolved'))

    def test_financial_claim_facts_identical_to_prior_reconciliation(self):
        old = json.loads((ROOT / 'artifacts/reconciliations/omega4-attempt002-finance-reconciliation-v1/reconciliation.v1.json').read_bytes())
        new = r.evaluate(self.doc, self.report, self.validation)
        for before, after in zip(old['claims'], new['claims']):
            self.assertEqual(before, {k: val for k, val in after.items() if k != 'business_disposition'})
        for key in ['requests', 'finance_events', 'finance_deliveries', 'travel_cancellations', 'unresolved_items']:
            self.assertEqual(old[key], new[key])

    def test_all_batches_csv_case_views_keep_financial_holds(self):
        for batch in range(1, 5):
            snap = json.loads((LATEST / f'batches/{batch:03}.json').read_bytes())
            cases = json.loads((LATEST / f'case-views/{batch:03}.json').read_bytes())['cases']
            b.check_snapshot(snap)
            for ident, value in [('C13', 'withdrawn'), ('C14', 'rejected')]:
                c = self.claim(snap, ident)
                self.assertEqual(c['business_disposition']['value'], value)
                self.assertEqual(next(x for x in cases if x['claim_id'] == ident)['business_disposition'], c['business_disposition'])
            self.assertTrue(all(c['status'] == 'held' and c['financial_closure_status'] == 'unresolved'
                                and c['known_paid_cents'] is None and c['balance_cents'] is None for c in snap['claims']))
        with (LATEST / 'claims.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(list(rows[0]), b.CSV_FIELDS)
        for ident, value in [('C13', 'withdrawn'), ('C14', 'rejected')]:
            c = next(c for c in rows if c['claim_id'] == ident)
            self.assertIn('Business disposition: ' + value, c['reason'])
            self.assertEqual((c['status'], c['paid_cents'], c['balance_cents']), ('held', '', ''))

    def test_snapshot_guard_rejects_disposition_mutation(self):
        snap = json.loads((LATEST / 'batches/004.json').read_bytes())
        self.claim(snap, 'C13')['business_disposition']['value'] = 'rejected'
        with self.assertRaises(ValueError):
            b.check_snapshot(snap)
