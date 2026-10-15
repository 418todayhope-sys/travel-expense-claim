"""POL-2026.2 review authority and business transitions, without financial closure."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from .exceptions import source_bound
from .expenses import policy_valid, local_date
from .workflow import _revision, row_values

ROLES = {'administration': 'Administration reviewer', 'budget_owner': 'Budget owner',
         'supervisor': 'Supervisor', 'director': 'Director'}


def fields(row):
    return {f['label'].strip(): f['value'] for f in row.get('fields', [])} if 'fields' in row else row_values(row)


def ref(row):
    return f"{row.get('source_id')}@{row.get('source_sha256')}#{row.get('locator')}"


def table(parsed, key, name):
    return parsed.get('records', {}).get(key, next((s['records'] for s in parsed.get('workbook_sheets', []) if s['name'] == name), []))


def utc_time(value):
    if not isinstance(value, str) or 'T' not in value:
        raise ValueError('Missing decision UTC time')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    # Native workbook column explicitly specifies UTC.
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


def versions(row):
    return set(re.findall(r'\b(?:SRC-D-\d+|POL-\d{4}\.\d+)\b', row.get('text', '')))


def evidence_digest(rows, amount):
    """Compare material facts, retaining source versions but ignoring arrival metadata."""
    content=[]
    for row in rows:
        value=fields(row)
        content.append(dict(source_id=row.get('source_id'), sha256=row.get('source_sha256'),
                            values={k:v for k,v in value.items() if k not in {'Arrival batch', 'Status', 'Claim reason'}}))
    return hashlib.sha256(json.dumps(dict(rows=content, amount=amount), sort_keys=True, default=str).encode()).hexdigest()


def evaluate_reviews(*, parsed, kind, subject_id, revision, trip_record, employee,
                     subject_record, amount_cents, decisions, arrival_batch, observations,
                     cost_ids=(), prior=None, dependency_rows=(), withdrawn=False, cancellation_ids=(), budget_context=None):
    """Evaluate supplied replies only. Invalid/stale imports stay in deliveries."""
    trip=fields(trip_record); policy=policy_valid(parsed.get('expense_policy'))
    people=[r for r in table(parsed,'people','People') if fields(r).get('Employee ID')==employee]
    person=fields(people[0]) if len(people)==1 else {}
    packets=table(parsed,'review_packets','Review packets')
    required=['administration','budget_owner','supervisor']
    amount_known=isinstance(amount_cents,int) and not isinstance(amount_cents,bool) and amount_cents>=0
    if amount_known and amount_cents>100000: required.append('director')
    basis_rows=[subject_record,trip_record]+people+list(dependency_rows)
    digest=evidence_digest(basis_rows,dict(amount_cents=amount_cents,cost_ids=sorted(cost_ids) if kind=='claim' else [],cancellation_ids=sorted(cancellation_ids)))
    material_same_revision=bool(prior and prior.get('revision')==revision and
        (prior.get('evidence_digest')!=digest or prior.get('material_same_revision')))
    invalidated_batch=(prior.get('invalidated_batch') if prior and prior.get('material_same_revision') and prior.get('revision')==revision else arrival_batch) if material_same_revision else None
    deliveries=[]; identities={}; conflicts=set()
    budget_ids={fields(r).get('Ledger reference') for r in table(parsed,'budget','Budget')}
    for decision in decisions:
        dv=fields(decision); identity=dv.get('Decision reference')
        ps=[p for p in packets if fields(p).get('Decision reference')==identity]
        relevant=(dv.get('Subject reference')==subject_id or any(fields(p).get('Trip reference')==trip.get('Trip reference')
                  and fields(p).get('Employee ID')==employee for p in ps))
        if not relevant: continue
        item=dict(decision_id=identity, outcome=dv.get('Outcome'), roles=str(dv.get('Review roles') or '').splitlines(),
                  reason=dv.get('Reason'), repair_requested=dv.get('Repair requested'), evidence_valid=False,
                  active=False, import_status='rejected-import', source_refs=[ref(decision)]+[ref(p) for p in ps],
                  raw_record=deepcopy(decision), rejection_reasons=[])
        deliveries.append(item)
        try:
            batch=_revision(dv.get('Arrival batch'))
            if batch is None or batch>arrival_batch: raise ValueError('Reply outside consumed arrival batches')
            if not subject_id or _revision(revision) is None or not source_bound(subject_record,observations) or not source_bound(trip_record,observations):
                raise ValueError('Missing verified subject/trip identity or revision')
            if dv.get('Subject type')!=kind or dv.get('Subject reference')!=subject_id or _revision(dv.get('Revision'))!=revision:
                raise ValueError('Wrong or stale subject type/ID/revision')
            if not identity or not source_bound(decision,observations): raise ValueError('Missing decision identity/source binding')
            if len(people)!=1 or not source_bound(people[0],observations): raise ValueError('Missing verified directory authority')
            roles=item['roles']
            if not roles or len(set(roles))!=len(roles) or not set(roles)<=set(ROLES): raise ValueError('Unknown or repeated role')
            if len(roles)>1 and not (set(roles)=={'budget_owner','supervisor'} and person.get('Budget owner')==person.get('Supervisor')):
                raise ValueError('Only directory-identical budget owner/supervisor may combine explicit roles')
            if any(not person.get(ROLES[r]) or dv.get('Reviewer')!=person[ROLES[r]] or dv.get('Reviewer')==employee for r in roles):
                raise ValueError('Wrong-role, self-review or unauthorized stable actor')
            if not isinstance(dv.get('Reason'),str) or not dv['Reason'].strip(): raise ValueError('Missing review reason')
            if item['outcome'] not in {'approve','return','reject'}: raise ValueError('Unknown decision outcome')
            if item['outcome']=='return' and (not isinstance(dv.get('Repair requested'),str) or not dv['Repair requested'].strip()):
                raise ValueError('Return requires a concrete repair request')
            if len(ps)!=1 or not source_bound(ps[0],observations): raise ValueError('Missing, conflicting or unbound review packet')
            pv=fields(ps[0]); supplied=str(dv.get('Source revisions') or '').splitlines()
            policy_versions={v for v in supplied if v.startswith('POL-')}
            if not supplied or pv.get('Policy revision')!='POL-2026.2' or policy_versions!={'POL-2026.2'}:
                raise ValueError('Missing/stale policy source version')
            exact=ref(subject_record) in supplied or subject_record.get('source_sha256') in supplied
            printed=versions(subject_record)
            declared={v for v in supplied if v.startswith('SRC-D-')}
            if printed and declared-printed:
                raise ValueError('Reply contains a stale printed source version')
            if material_same_revision and batch<invalidated_batch:
                raise ValueError('Reply predates material evidence revalidation')
            if not exact and (material_same_revision or not printed.intersection(supplied)):
                raise ValueError('Reply does not bind current subject source version')
            if (pv.get('Employee ID')!=employee or pv.get('Trip reference')!=trip.get('Trip reference')
                    or _revision(pv.get('Trip revision'))!=_revision(trip.get('Trip revision'))
                    or any(pv.get(k)!=trip.get(k) for k in ('Business purpose','Client','Schedule coverage','Alternatives considered','Permit reference','Permit revision'))):
                raise ValueError('Packet does not match current trip/permit evidence')
            if kind=='claim' and set(str(pv.get('Expense references') or '').splitlines())!=set(cost_ids):
                raise ValueError('Packet expense list does not match review subject')
            if kind=='permit':
                from .finance import _cents
                if not amount_known or _cents(pv.get('Reviewed estimate (EUR)'))!=amount_cents:
                    raise ValueError('Missing/mismatched reviewed permit estimate')
            if not set(cancellation_ids)<=set(str(pv.get('Travel cancellation references') or '').splitlines()):
                raise ValueError('Packet lacks current cancellation context')
            budget_refs=set(str(pv.get('Budget record references') or '').splitlines())
            if not budget_refs or not budget_refs<=budget_ids: raise ValueError('Missing referenced budget records; no budget decision inferred')
            stamp=utc_time(dv.get('Decision time (UTC)'))
            payload={k:v for k,v in dv.items() if k!='Arrival batch'}
            if identity in identities and identities[identity][0]!=payload:
                conflicts.add(identity)
            elif identity not in identities: identities[identity]=(payload,item)
            else:
                item.update(import_status='exact-replay',replayed_decision_id=identity)
                continue
            from .budget import budget_reply_error
            budget_error=budget_reply_error(budget_context,decision,ps[0]) if 'budget_owner' in roles else None
            item['budget_evidence_valid']=not budget_error
            item['budget_revalidation_reason']=budget_error
            item.update(evidence_valid=True,import_status='valid',order=stamp.isoformat(),decision_time=stamp.isoformat())
        except (ValueError,TypeError,InvalidOperation) as exc:
            item['rejection_reasons'].append(str(exc))
    # Conflicting redelivery must hold an identity even when its later payload fails validation.
    all_payloads={}
    for item in deliveries:
        dv=fields(item['raw_record']); identity=item['decision_id']
        if (identity and dv.get('Subject reference')==subject_id and _revision(dv.get('Revision'))==revision
                and _revision(dv.get('Arrival batch')) is not None and _revision(dv.get('Arrival batch'))<=arrival_batch):
            payload={k:v for k,v in dv.items() if k!='Arrival batch'}
            if identity in all_payloads and all_payloads[identity]!=payload: conflicts.add(identity)
            all_payloads[identity]=payload
    for item in deliveries:
        if item['decision_id'] in conflicts:
            item.update(evidence_valid=False,import_status='conflicting-replay')
            item['rejection_reasons'].append('Immutable decision identity has conflicting deliveries')
    role_states={}; selected=[]
    for role in required:
        candidates=[d for d in deliveries if d['evidence_valid'] and role in d['roles'] and (role!='budget_owner' or d.get('budget_evidence_valid',True))]
        if not candidates: role_states[role]='missing'; continue
        latest=max(d['order'] for d in candidates)
        matches=[d for d in candidates if d['order']==latest]
        if len(matches)!=1:
            role_states[role]='conflicting';continue
        chosen=matches[0];chosen['active']=True;role_states[role]=chosen['outcome']
        if chosen not in selected: selected.append(chosen)
    withdrawal_valid=bool(withdrawn and source_bound(subject_record,observations) and source_bound(trip_record,observations)
        and trip.get('Employee ID')==employee and len(people)==1 and source_bound(people[0],observations)
        and isinstance(fields(subject_record).get('Claim reason'),str) and fields(subject_record)['Claim reason'].strip())
    states=set(role_states.values())
    state=('withdrawn' if withdrawal_valid else 'rejected' if 'reject' in states else 'returned' if 'return' in states
           else 'approved' if states=={'approve'} and policy and amount_known else 'pending')
    if not policy or conflicts and not withdrawal_valid: state='pending'
    policy_binding=parsed.get('expense_policy') or {}
    policy_refs=[f"{policy_binding.get('path')}@{policy_binding.get('sha256')}#line {n}" for n in (9,13,15,17)] if policy else []
    return dict(policy_source_refs=policy_refs,subject_type=kind,subject_id=subject_id,revision=revision,state=state,required_roles=required,
                amount_cents=amount_cents,amount_known=amount_known,evidence_digest=digest,withdrawal_requested=withdrawn,withdrawal_valid=withdrawal_valid,
                material_same_revision=material_same_revision,invalidated_batch=invalidated_batch,policy_verified=policy,role_states=role_states,
                deliveries=deliveries,active_decision_ids=[d['decision_id'] for d in selected],
                source_refs=list(dict.fromkeys([ref(r) for r in basis_rows]+[r for d in deliveries for r in d['source_refs']])),
                approved=state=='approved',repair_requests=[d['repair_requested'] for d in selected if d['outcome']=='return'])


def evaluate_permit(*, parsed, trip_record, decisions, arrival_batch, observations, prior=None, cost_ids=(), cancellations=(), budget_context=None):
    trip=fields(trip_record)
    if trip.get('International') is False:
        affected=[c for c in cancellations if c.get('trip_id')==trip.get('Trip reference')
            and _revision(c.get('trip_revision'))==_revision(trip.get('Trip revision'))]
        return dict(subject_type='permit',subject_id=None,revision=None,state='not-required',approved=True,
                    arrangement_authorized=policy_valid(parsed.get('expense_policy')) and not affected,
                    arrangements_at_commitment_supported=policy_valid(parsed.get('expense_policy')),
                    cancellation_ids=[c['cancellation_id'] for c in affected], source_refs=[ref(trip_record)],deliveries=[])
    from .finance import _cents
    subject=deepcopy(trip_record)
    # Newly parsed workbooks retain the printed source version in their preamble.
    subject['text']='\n'.join(str(c.get('value','')) for s in parsed.get('workbook_sheets',[])
        if s.get('source_id')==trip_record.get('source_id') for c in s.get('preamble',[]))
    result=evaluate_reviews(parsed=parsed,kind='permit',subject_id=trip.get('Permit reference'),revision=_revision(trip.get('Permit revision')),
        trip_record=trip_record,employee=trip.get('Employee ID'),subject_record=subject,amount_cents=_cents(trip.get('Estimate (EUR)')),
        decisions=decisions,arrival_batch=arrival_batch,observations=observations,cost_ids=cost_ids,prior=prior,budget_context=budget_context)
    result['budget_context']=budget_context
    result['arrangement_authorized']=False
    if result['approved'] and trip.get('International') is True:
        commitment=trip.get('First commitment date')
        if commitment in (None,''):
            result['arrangement_authorized']=True
        else:
            try:
                day=local_date(commitment)
                active=[d for d in result['deliveries'] if d['active']]
                latest=max(utc_time(d['decision_time']) for d in active).astimezone(ZoneInfo('Europe/Amsterdam')).date()
                result['arrangement_authorized']=latest<day
                result['timing_finding']=None if latest<day else 'late_permit' if latest>day else 'same-day-order-unconfirmed'
            except (ValueError,TypeError): result['timing_finding']='missing-commitment-evidence'
    result['arrangements_at_commitment_supported']=result['arrangement_authorized']
    affected=[c for c in cancellations if c.get('trip_id')==trip.get('Trip reference')
        and _revision(c.get('trip_revision'))==_revision(trip.get('Trip revision'))
        and (c.get('target_type')=='trip' or (c.get('permit_id')==trip.get('Permit reference')
             and _revision(c.get('permit_revision'))==_revision(trip.get('Permit revision'))))]
    result['cancellation_ids']=[c['cancellation_id'] for c in affected]
    if affected: result['arrangement_authorized']=False
    return result
