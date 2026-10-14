"""Native source-shaped evidence; all mutations below are synthetic probes.

The policy fixture preserves the user's complete browser copy byte for byte,
SHA-256 f547ee77729be8ad431a5ddf2e2907f94f29ad50092231191abd2f72c04f54d2.
It is not a fresh native Notion retrieval.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from travel_claim.expenses import evaluate_expenses, filing_deadline, load_expense_policy
from travel_claim.ordinary import expense_lines, fields, ref, table

FIXTURES = Path(__file__).parent / 'fixtures'


def setup():
    parsed = json.loads((FIXTURES / 'ordinary_claim_c01.json').read_text())
    parsed['expense_policy'] = load_expense_policy(FIXTURES / 'POL-2026.2-browser-copy.txt')
    record = parsed['records']['claim_revisions'][0]
    trip = fields(table(parsed, 'trips', 'Trips')[0])
    return parsed, record, trip


def setfield(row, key, value):
    if 'fields' in row:
        for f in row['fields']:
            if f['label'] == key:
                f['value'] = value
                return
        row['fields'].append(dict(label=key, value=value))
    else:
        row['values'][key] = dict(value=value)


def evaluate(parsed, record, trip, history=()):
    lines = expense_lines(record)
    result = evaluate_expenses(lines=lines, parsed=parsed, employee='EMP-01', trip_id='T01',
        trip=trip, record=record, history=history, fields=fields, ref=ref, table=table)
    return result, lines


def merchant(parsed):
    return next(r for r in table(parsed, 'merchant_payments', 'Merchant payments') if fields(r)['Expense reference'] == 'COST-01')


def test_retained_c01_actual_paid_expense_preserves_source_and_conversion():
    parsed, record, trip = setup()
    result, lines = evaluate(parsed, record, trip)
    assert result['status'] == 'PASS' and result['calculated_cents'] == 10000
    line = lines[0]
    assert line['conversion']['eur_rate'] == '1'
    assert line['conversion']['original_amount'] == '100.00'
    assert line['filing']['first_submission_date'] == '2026-09-01'
    assert any('#PDF page 1, receipt 1' in r for r in line['source_refs'])
    assert any("#tab 'Merchant payments', row 6" in r for r in line['source_refs'])
    assert all('line ' in r for r in result['policy_source_refs'])


@pytest.mark.parametrize('end,expected', [('2026-08-31','2026-10-31'), ('2023-12-31','2024-02-29'),
    ('2024-12-31','2025-02-28'), ('2026-07-31','2026-09-30'), ('2024-02-29','2024-04-29')])
def test_calendar_deadline(end, expected):
    assert filing_deadline(end).isoformat() == expected


@pytest.mark.parametrize('category,units,amount', [('transport','0',10000),('conference','0',10000),
    ('personal','1',0),('lodging','2',8000),('meals','1',4000)])
def test_categories_and_caps(category, units, amount):
    parsed, record, trip = setup()
    receipt = parsed['records']['receipts'][0]
    setfield(receipt, 'Category', category); setfield(receipt, 'Documented units', units)
    parsed['records']['caps'] = [dict(source_id='synthetic-cap', source_sha256='a'*64, locator='synthetic cap',
        values={k:dict(value=v) for k,v in {'Destination':trip['Destination'], 'Category':category,
        'Currency':'EUR','Effective from':'2026-09-01','Effective to':'2026-09-01','Amount per unit':'40.00'}.items()})]
    result, lines = evaluate(parsed, record, trip)
    assert result['calculated_cents'] == amount
    if category in {'lodging','meals'}:
        assert lines[0]['conversion']['cap']['units'] == units


@pytest.mark.parametrize('units', ['0','-1','1.5','NaN',True,None])
def test_fractional_or_invalid_units_unresolved(units):
    parsed, record, trip = setup()
    setfield(parsed['records']['receipts'][0], 'Category', 'lodging')
    setfield(parsed['records']['receipts'][0], 'Documented units', units)
    result, lines = evaluate(parsed, record, trip)
    assert result['status'] == 'BLOCKED' and lines[0]['calculated_cents'] is None


@pytest.mark.parametrize('field,value', [('Employee ID','OTHER'),('Trip reference','OTHER'),
    ('Currency','USD'),('Gross amount','99.99'),('Payment status','pending'),('Paid date',None),
    ('Transaction reference',None),('Receipt reference','OTHER')])
def test_missing_or_mismatched_merchant_is_not_zero(field, value):
    parsed, record, trip = setup(); setfield(merchant(parsed),field,value)
    result, lines = evaluate(parsed, record, trip)
    assert result['status'] == 'BLOCKED' and lines[0]['calculated_cents'] is None


@pytest.mark.parametrize('field,value', [('Employee','OTHER'),('Trip reference','OTHER'),('Expense reference','OTHER'),
    ('Currency','USD'),('Gross amount','99.99')])
def test_mismatched_receipt(field, value):
    parsed, record, trip = setup(); setfield(parsed['records']['receipts'][0],field,value)
    assert evaluate(parsed,record,trip)[1][0]['evidence_status'] == 'BLOCKED'


def test_duplicate_merchant_does_not_double_count_but_conflict_blocks():
    parsed, record, trip = setup()
    duplicate = deepcopy(merchant(parsed)); parsed['records']['merchant_payments'] = [merchant(parsed), duplicate]
    assert evaluate(parsed,record,trip)[0]['calculated_cents'] == 10000
    setfield(duplicate,'Gross amount','200.00')
    assert evaluate(parsed,record,trip)[1][0]['calculated_cents'] is None


@pytest.mark.parametrize('rate,expected', [('0.90005',9001),('0.900049',9000),('0.90015',9002)])
def test_exact_payment_date_fx_half_up(rate, expected):
    parsed, record, trip = setup()
    record['text'] = record['text'].replace('EUR','USD')
    setfield(parsed['records']['receipts'][0],'Currency','USD'); setfield(merchant(parsed),'Currency','USD')
    parsed['records']['fx_rates'] = [dict(source_id='synthetic-fx',source_sha256='b'*64,locator='exact FX',
        values={k:dict(value=v) for k,v in {'Currency':'USD','Rate date':'2026-09-01','EUR per currency unit':rate}.items()})]
    result, lines = evaluate(parsed, record, trip)
    assert result['calculated_cents'] == expected
    assert lines[0]['conversion']['eur_rate'] == rate
    assert lines[0]['conversion']['rounding'] == 'ROUND_HALF_UP'


@pytest.mark.parametrize('missing', ['policy','tampered-policy','receipt','merchant','rate','cap','category'])
def test_missing_inputs_stay_unresolved(missing):
    parsed, record, trip = setup()
    if missing == 'policy': parsed.pop('expense_policy')
    if missing == 'tampered-policy': parsed['expense_policy']['text'] += '\n'
    if missing == 'receipt': parsed['records']['receipts'] = []
    if missing == 'merchant': parsed['records']['merchant_payments'] = []
    if missing == 'category': setfield(parsed['records']['receipts'][0],'Category','entertainment')
    if missing == 'cap':
        setfield(parsed['records']['receipts'][0],'Category','lodging'); parsed['records']['caps'] = []
    if missing == 'rate':
        record['text'] = record['text'].replace('EUR','USD')
        setfield(parsed['records']['receipts'][0],'Currency','USD'); setfield(merchant(parsed),'Currency','USD')
        parsed['records']['fx_rates'] = []
    result, lines = evaluate(parsed,record,trip)
    assert result['status'] == 'BLOCKED' and lines[0]['calculated_cents'] is None


@pytest.mark.parametrize('submitted,status', [('2026-10-31','PASS'),('2026-11-01','BLOCKED'),('2026-08-31','BLOCKED')])
def test_inclusive_deadline_and_paid_before_submission(submitted,status):
    parsed, record, trip = setup(); trip['End date'] = '2026-08-31'
    record['text'] = record['text'].replace('2026-09-01',submitted); setfield(record,'Submitted date',submitted)
    result, lines = evaluate(parsed,record,trip)
    assert result['status'] == status
    if submitted > '2026-10-31': assert 'Late filing' in lines[0]['reason']


def test_paid_pretravel_submission_is_allowed_and_import_date_is_ignored():
    parsed, record, trip = setup(); trip.update({'Start date':'2026-10-01','End date':'2026-10-10'})
    parsed['import_date'] = '2099-01-01'
    assert evaluate(parsed,record,trip)[0]['status'] == 'PASS'


def test_unchanged_cost_keeps_submission_date_but_new_cost_does_not_inherit_it():
    parsed, record, trip = setup(); old = deepcopy(record)
    record['text'] = record['text'].replace('2026-09-01','2026-11-01'); setfield(record,'Submitted date','2026-11-01')
    trip['End date'] = '2026-08-31'
    history = [dict(record=old)]
    result, lines = evaluate(parsed,record,trip,history)
    assert result['status'] == 'PASS' and lines[0]['filing']['first_submission_date'] == '2026-09-01'
    record['text'] = record['text'].replace('COST-01','COST-NEW')
    for row in [parsed['records']['receipts'][0],merchant(parsed)]:
        setfield(row,'Expense reference','COST-NEW'); setfield(row,'Receipt reference','R-COST-NEW')
    result, lines = evaluate(parsed,record,trip,history)
    assert lines[0]['filing']['first_submission_date'] == '2026-11-01'
    assert result['status'] == 'BLOCKED'


def test_late_exception_requires_exact_finance_actor_revision_cost_and_covered_issue():
    parsed, record, trip = setup(); trip['End date'] = '2026-06-01'
    person = fields(table(parsed,'people','People')[0])
    exception = {'Authorizing Finance officer':person['Finance officer'],'Applies to claim':'C01',
        'Applies to revision':'1','Expense reference':'COST-01','Allowed original amount':'100.00',
        'Covered issues':'Late filing','Exception reason':'SYNTHETIC explicit exception'}
    for key,value in exception.items(): setfield(record,key,value)
    result, lines = evaluate(parsed,record,trip)
    assert result['status'] == 'PASS'
    assert 'Late filing' in lines[0]['filing']['original_finding']
    for key in ('Authorizing Finance officer','Applies to claim','Applies to revision','Expense reference','Covered issues'):
        changed = deepcopy(record); setfield(changed,key,'WRONG')
        assert evaluate(parsed,changed,trip)[0]['status'] == 'BLOCKED'


def test_malformed_extra_line_blocks_total_without_losing_valid_line():
    parsed, record, trip = setup()
    record['text'] += '\n 2 COST-BAD malformed\n'
    result, lines = evaluate(parsed,record,trip)
    assert result['calculated_cents'] is None and len(lines) == 2
    assert lines[0]['calculated_cents'] == 10000
    assert lines[1]['calculated_cents'] is None


def test_round_each_line_then_sum_and_independent_missing_evidence():
    parsed, record, trip = setup()
    first_receipt = parsed['records']['receipts'][0]
    first_merchant = merchant(parsed)
    record['text'] = record['text'].replace('EUR','USD')
    setfield(first_receipt,'Currency','USD'); setfield(first_merchant,'Currency','USD')
    second_receipt=deepcopy(first_receipt); second_merchant=deepcopy(first_merchant)
    for row in (second_receipt,second_merchant):
        setfield(row,'Expense reference','COST-NEW'); setfield(row,'Receipt reference','R-COST-NEW')
    setfield(second_merchant,'Transaction reference','SYNTHETIC-SECOND')
    parsed['records']['receipts'].append(second_receipt)
    parsed['records']['merchant_payments'] = [first_merchant,second_merchant]
    record['text'] += '\n2 COST-NEW R-COST-NEW 2026-09-01 100.00 USD\n'
    parsed['records']['fx_rates'] = [dict(source_id='synthetic-fx',source_sha256='b'*64,locator='FX half cent',
        values={k:dict(value=v) for k,v in {'Currency':'USD','Rate date':'2026-09-01','EUR per currency unit':'0.90005'}.items()})]
    result, lines = evaluate(parsed,record,trip)
    assert result['calculated_cents'] == 18002
    assert [l['calculated_cents'] for l in lines] == [9001,9001]
    parsed['records']['receipts'].remove(second_receipt)
    result, lines = evaluate(parsed,record,trip)
    assert result['calculated_cents'] is None and lines[0]['calculated_cents'] == 9001


def test_correction_cannot_backdate_unchanged_cost():
    parsed, record, trip = setup(); old=deepcopy(record)
    record['text'] = record['text'].replace('2026-09-01','2026-08-01')
    result, lines = evaluate(parsed,record,trip,[dict(revision=1,record=old)])
    assert lines[0]['filing']['first_submission_date'] == '2026-09-01'


@pytest.mark.parametrize('field,value', [('Destination','WRONG'),('Currency','USD'),
    ('Effective from','2026-09-02'),('Effective to','2026-08-31')])
def test_cap_must_match_destination_currency_and_payment_date(field,value):
    parsed, record, trip = setup()
    setfield(parsed['records']['receipts'][0],'Category','lodging')
    cap=dict(source_id='synthetic-cap',source_sha256='a'*64,locator='synthetic cap',values={k:dict(value=v)
        for k,v in {'Destination':trip['Destination'],'Category':'lodging','Currency':'EUR',
        'Effective from':'2026-01-01','Effective to':'2026-12-31','Amount per unit':'40.00'}.items()})
    setfield(cap,field,value); parsed['records']['caps']=[cap]
    assert evaluate(parsed,record,trip)[1][0]['calculated_cents'] is None


def test_eur_does_not_require_or_use_a_supplied_fx_row():
    parsed, record, trip = setup()
    parsed['records']['fx_rates'] = [dict(values={'Currency':dict(value='EUR'),'Rate date':dict(value='bad'),
        'EUR per currency unit':dict(value='2')})]
    assert evaluate(parsed,record,trip)[0]['calculated_cents'] == 10000


def test_multiple_payment_dates_are_held_without_choosing_rate_or_cap():
    parsed, record, trip = setup(); first=merchant(parsed); second=deepcopy(first)
    setfield(first,'Gross amount','50.00'); setfield(second,'Gross amount','50.00')
    setfield(second,'Transaction reference','SYNTHETIC-SECOND'); setfield(second,'Paid date','2026-08-31')
    parsed['records']['merchant_payments']=[first,second]
    result, lines=evaluate(parsed,record,trip)
    assert result['status']=='BLOCKED' and lines[0]['evidence_status']=='PASS'
    assert 'allocation' in lines[0]['reason']
