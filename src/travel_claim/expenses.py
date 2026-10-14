"""POL-2026.2 expense arithmetic and local-calendar filing checks.

The policy is explicitly bound by its original bytes; this does not convert the
user's browser copy into a successful native Notion capture or grant approval.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
from pathlib import Path

POLICY_SHA256 = 'f547ee77729be8ad431a5ddf2e2907f94f29ad50092231191abd2f72c04f54d2'


def load_expense_policy(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != POLICY_SHA256:
        raise ValueError('POL-2026.2 browser copy hash mismatch')
    return dict(text=raw.decode('utf-8'), sha256=POLICY_SHA256, path=str(path),
                provenance='user-provided browser-visible copy; not native HTTP/API retrieval')


def policy_valid(binding):
    return (isinstance(binding, dict) and isinstance(binding.get('text'), str)
            and hashlib.sha256(binding['text'].encode('utf-8')).hexdigest() == POLICY_SHA256
            and binding.get('sha256') == POLICY_SHA256)


def local_date(value):
    """Accept native local dates and Excel's naive midnight date serialization."""
    text = str(value)
    if len(text) == 19 and text.endswith('T00:00:00'):
        text = text[:10]
    result = date.fromisoformat(text)
    if result.isoformat() != text:
        raise ValueError('Not a local calendar date')
    return result


def filing_deadline(trip_end):
    end = local_date(trip_end)
    month = end.year * 12 + end.month - 1 + 2
    year, zero_month = divmod(month, 12)
    return date(year, zero_month + 1, min(end.day, monthrange(year, zero_month + 1)[1]))


def number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('Missing or invalid number')
    result = Decimal(str(value).replace(',', ''))
    if not result.is_finite() or result < 0:
        raise ValueError('Invalid amount')
    return result


def evaluate_expenses(*, lines, parsed, employee, trip_id, trip, record, history, fields, ref, table):
    """Evaluate each line independently, retaining unresolved evidence and reasons."""
    binding = parsed.get('expense_policy')
    verified = policy_valid(binding)
    policy_refs = [f"{binding.get('path')}@{POLICY_SHA256}#line {n}" for n in (5, 7, 11)] if verified else []
    receipts = parsed.get('records', {}).get('receipts', [])
    merchants = table(parsed, 'merchant_payments', 'Merchant payments')
    rates = table(parsed, 'fx_rates', 'FX')
    caps = table(parsed, 'caps', 'Caps')
    for line in lines:
        line.update(allowed_cents=None, calculated_cents=None, status='unresolved', evidence_status='BLOCKED',
                    filing_status='BLOCKED', calculation_status='BLOCKED', reason='Missing or conflicting evidence')
        rs = [r for r in receipts if fields(r).get('Receipt reference') == line['receipt_id']]
        ms = [r for r in merchants if fields(r).get('Expense reference') == line['cost_id']]
        line['source_refs'] += [ref(r) for r in rs + ms] + policy_refs
        try:
            gross = number(line['original_amount'])
            if not employee or not trip_id or gross <= 0 or len(rs) != 1:
                raise ValueError('Missing receipt or nonpositive purchase')
            rv = fields(rs[0])
            if not (rv.get('Expense reference') == line['cost_id'] and rv.get('Employee') == employee
                    and rv.get('Trip reference') == trip_id and rv.get('Currency') == line['currency']
                    and number(rv.get('Gross amount')) == gross and len(line['currency']) == 3
                    and line['currency'].isalpha() and line['currency'].isupper()):
                raise ValueError('Receipt identity, currency or gross mismatch')
            unique = {}
            for row in ms:
                mv = fields(row); identity = mv.get('Transaction reference')
                # Identity is global: a redelivery under a different cost also conflicts.
                deliveries = [fields(r) for r in merchants if fields(r).get('Transaction reference') == identity]
                if not identity or any(d != mv for d in deliveries):
                    raise ValueError('Conflicting merchant transaction identity')
                unique[identity] = row
            ms = list(unique.values())
            if not ms:
                raise ValueError('Missing settled merchant transaction')
            for row in ms:
                mv = fields(row)
                if not (mv.get('Employee ID') == employee and mv.get('Trip reference') == trip_id
                        and mv.get('Receipt reference') == line['receipt_id'] and mv.get('Currency') == line['currency']
                        and mv.get('Payment status') == 'settled' and number(mv.get('Gross amount')) > 0):
                    raise ValueError('Merchant payment is unsettled or mismatched')
            if sum(number(fields(m).get('Gross amount')) for m in ms) != gross:
                raise ValueError('Merchant payments do not match gross amount')
            dates = sorted({local_date(fields(m).get('Paid date')).isoformat() for m in ms})
            line.update(evidence_status='PASS', category=rv.get('Category'), documented_units=rv.get('Documented units'), paid_dates=dates)
            if not verified:
                raise ValueError('Verified expense policy binding required')
            # Different payment dates require an explicit allocation; do not choose a rate/cap.
            if len(dates) != 1:
                raise ValueError('Multiple payment dates require source-supported allocation')
            paid = local_date(dates[0])
            if paid.year != 2026:
                raise ValueError('Payment outside supplied policy effective year')
            category = rv.get('Category')
            if category not in {'personal', 'transport', 'conference', 'lodging', 'meals'}:
                raise ValueError('Unknown expense category')
            allowed = Decimal(0) if category == 'personal' else gross
            cap_evidence = None
            if category in {'lodging', 'meals'}:
                if not trip.get('Destination'):
                    raise ValueError('Missing destination for applicable cap')
                units = number(rv.get('Documented units'))
                if units <= 0 or units != units.to_integral_value():
                    raise ValueError('Capped units must be positive integers')
                cs = [c for c in caps if fields(c).get('Destination') == trip.get('Destination')
                      and fields(c).get('Category') == category and fields(c).get('Currency') == line['currency']]
                cs = [c for c in cs if local_date(fields(c).get('Effective from')) <= paid <= local_date(fields(c).get('Effective to'))]
                if len(cs) != 1:
                    raise ValueError('Missing or ambiguous applicable cap')
                cap = number(fields(cs[0]).get('Amount per unit'))
                with localcontext() as ctx:
                    ctx.prec = max(50, len(str(cap)) + len(str(units)) + 20)
                    allowed = min(gross, cap * units)
                cap_evidence = dict(amount_per_unit=str(cap), units=str(units), source_ref=ref(cs[0]))
                line['source_refs'].append(ref(cs[0]))
            if line['currency'] == 'EUR':
                rate = Decimal(1); rate_refs = policy_refs
            else:
                fx = [r for r in rates if fields(r).get('Currency') == line['currency']
                      and local_date(fields(r).get('Rate date')) == paid]
                if len(fx) != 1:
                    raise ValueError('Missing or ambiguous payment-date Finance FX rate')
                rate = number(fields(fx[0]).get('EUR per currency unit')); rate_refs = [ref(fx[0])]
                if rate <= 0:
                    raise ValueError('FX rate must be positive')
            with localcontext() as ctx:
                ctx.prec = max(50, len(str(gross)) + len(str(rate)) + 20)
                converted = allowed * rate
                cents = int((converted * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            line['source_refs'] += rate_refs
            line.update(calculated_cents=cents, calculation_status='PASS',
                        conversion=dict(original_amount=str(gross), allowed_original_amount=str(allowed),
                                        currency=line['currency'], payment_date=paid.isoformat(), eur_rate=str(rate),
                                        unrounded_eur=str(converted), rounded_cents=cents, rounding='ROUND_HALF_UP',
                                        rate_source_refs=rate_refs, cap=cap_evidence))
            deadline = filing_deadline(trip.get('End date'))
            submitted = local_date(line['first_submitted_date'])
            # Earlier, unchanged cost submissions remain authoritative after a correction.
            from .ordinary import expense_lines
            first_supported = False
            for prior in sorted(history, key=lambda r: int(r.get('revision', 0))):
                pr = prior.get('record', {})
                for old in expense_lines(pr):
                    if (fields(pr).get('Employee') == employee and fields(pr).get('Trip reference') == trip_id
                            and all(old.get(k) == line.get(k) for k in ('cost_id', 'receipt_id', 'currency'))
                            and number(old['original_amount']) == gross):
                        submitted = local_date(old['first_submitted_date'])
                        line['source_refs'] += old['source_refs']
                        first_supported = True
                        break
                if first_supported:
                    break
            if submitted > local_date(fields(record).get('Submitted date')):
                raise ValueError('Cost submission is later than claim submission')
            if submitted < paid:
                raise ValueError('Submission precedes established employee payment')
            line['filing'] = dict(first_submission_date=submitted.isoformat(), deadline=deadline.isoformat(),
                                  inclusive=True, source_refs=[ref(record)] + policy_refs)
            if submitted > deadline:
                finding = 'Late filing held pending explicit version-bound Finance exception'
                line['filing']['original_finding'] = finding
                ev = fields(record)
                people = [fields(r) for r in table(parsed, 'people', 'People') if fields(r).get('Employee ID') == employee]
                covered = {v.strip() for v in str(ev.get('Covered issues', '')).splitlines()}
                valid_exception = (len(people) == 1 and people[0].get('Finance officer')
                    and ev.get('Authorizing Finance officer') == people[0]['Finance officer']
                    and ev.get('Applies to claim') == ev.get('Claim reference')
                    and str(ev.get('Applies to revision')) == str(ev.get('Revision'))
                    and ev.get('Expense reference') == line['cost_id'] and ev.get('Exception reason')
                    and bool(covered & {'Late filing', 'late_filing'}))
                if not valid_exception:
                    raise ValueError(finding)
                replacement = number(ev.get('Allowed original amount'))
                if replacement != allowed:
                    raise ValueError('Finance exception changes amount; replacement eligibility needs separate review')
                line['filing']['exception'] = dict(source_ref=ref(record), actor=ev['Authorizing Finance officer'],
                    claim_id=ev['Applies to claim'], revision=ev['Applies to revision'], cost_id=line['cost_id'],
                    reason=ev['Exception reason'], covered_issues=sorted(covered), replacement_original_amount=str(replacement))
            line.update(filing_status='PASS', status='supported', reason='Supported paid expense calculation; filing supported by explicit Finance exception'
                        if line.get('filing', {}).get('exception') else 'Supported paid expense calculation and timely filing')
        except (ValueError, TypeError, InvalidOperation, OverflowError) as exc:
            line['reason'] = str(exc)
    complete = bool(lines) and len({l['cost_id'] for l in lines}) == len(lines) and all(
        l['calculation_status'] == l['filing_status'] == 'PASS' for l in lines)
    return dict(status='PASS' if complete else 'BLOCKED',
                calculated_cents=sum(l['calculated_cents'] for l in lines) if complete else None,
                policy_source_refs=policy_refs, policy_verified=verified)
