"""POL-2026.2 budget facts and cross-claim cost attribution.

Recorded Finance commitments are encumbrances, not human entitlement approval.
Cash is read only from the protected Finance admission ledger. Native Budget
headers explicitly specify EUR; absent row revision/batch fields remain null.
"""
from copy import deepcopy
from collections import defaultdict
import hashlib
import json

from .approvals import fields, ref, table
from .event_validation import utc_time, text_id
from .exceptions import source_bound, finding
from .expenses import evaluate_expenses, policy_valid
from .finance import _cents
from .workflow import _revision

SCOPE=('Department','Project','Budget period')


def scope_of(value):
    parts=[value.get(k) for k in SCOPE]
    return tuple(str(v) for v in parts) if all(isinstance(v,(str,int,float)) and not isinstance(v,bool) and str(v).strip() and str(v)==str(v).strip() for v in parts) else None


def scope_id(scope):
    return json.dumps(list(scope),separators=(',',':')) if scope else 'unassigned'


def payload(row):
    return {k:v for k,v in fields(row).items() if k!='Arrival batch'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


def reconcile_budgets(*, parsed, history, finances, arrival_batch, observations, cancellations=(), prior=None, raw_finance=()):
    """Rebuild scope ledgers from opening rows plus admitted request/cash history."""
    prior=prior or {}; scopes={}; issues=[]; people=table(parsed,'people','People')
    def ledger(scope):
        key=scope_id(scope)
        if key not in scopes:
            scopes[key]=dict(scope=dict(zip(SCOPE,scope)) if scope else None,currency='EUR',
                allocations={},opening_obligations={},requests={},issues=[],source_refs=[],status='BLOCKED')
        return scopes[key]
    def issue(scope,code,reason,refs,owner='Finance',action='Verify exact source-bound budget/request facts; do not invent amounts'):
        item=dict(record_id=f'budget:{scope_id(scope)}:{code}',reason=reason,source_refs=list(dict.fromkeys(refs)),
                  owner=owner,next_action=action,scope_id=scope_id(scope))
        issues.append(item);ledger(scope)['issues'].append(item)
    def directory(employee):
        matches=[r for r in people if fields(r).get('Employee ID')==employee and source_bound(r,observations)]
        return matches[0] if len(matches)==1 else None
    for rows in history.get('claim',{}).values():
        current=next(r for r in reversed(rows['revisions']) if r['revision']==rows['current_revision'])
        person=directory(fields(current['record']).get('Employee'));ledger(scope_of(fields(person)) if person else None)
    grouped=defaultdict(list)
    seen_identities={fields(r).get('Ledger reference') for r in table(parsed,'budget','Budget') if isinstance(fields(r).get('Ledger reference'),(str,int,float,bool,type(None)))}
    for row in table(parsed,'budget','Budget'):
        value=fields(row);scope=scope_of(value);entry=ledger(scope)
        batch=value.get('Arrival batch')
        if batch is not None and (_revision(batch) is None or _revision(batch)>arrival_batch):
            if _revision(batch) is None:issue(scope,'bad-arrival:'+str(value.get('Ledger reference')),'Invalid budget arrival membership',[ref(row)])
            continue
        identity=value.get('Ledger reference')
        key=identity if isinstance(identity,(str,int,float,bool,type(None))) else ('invalid',repr(identity))
        grouped[key].append(row)
    admitted=deepcopy(prior.get('admitted_budget_entries',{}))
    for identity,rows in grouped.items():
        scope=scope_of(fields(rows[0]));refs=[ref(r) for r in rows];value=fields(rows[0])
        valid=bool(text_id(identity) and scope and all(source_bound(r,observations) for r in rows))
        for r in rows:
            v=fields(r)
            valid=valid and v.get('Entry type') in {'allocation','obligation'} and all(_cents(v.get(k)) is not None for k in (
                'Allocation or commitment (EUR)','Settled (EUR)','Refunded (EUR)'))
            valid=valid and v.get('Currency','EUR')=='EUR' and (v.get('Revision') is None or _revision(v['Revision']) is not None)
            valid=valid and _cents(v.get('Refunded (EUR)'))<=_cents(v.get('Settled (EUR)')) if valid else False
            if v.get('Entry type')=='obligation':valid=valid and text_id(v.get('Obligation reference'))
            if v.get('Entry type')=='allocation':valid=valid and _cents(v.get('Settled (EUR)'))==_cents(v.get('Refunded (EUR)'))==0
        conflict=any(payload(r)!=payload(rows[0]) for r in rows[1:])
        previous=admitted.get(identity)
        # A changed authoritative source version can update an opening record;
        # conflicting payloads under the same retained version cannot.
        if previous and payload(previous)!=payload(rows[0]) and previous.get('source_sha256')==rows[0].get('source_sha256'):
            conflict=True
        if not valid or conflict:
            for affected in {scope_of(fields(r)) for r in rows}:
                issue(affected,'ledger-conflict:'+str(identity),'Invalid/unbound or conflicting budget ledger identity; admitted facts retained',refs)
            continue
        if not previous or payload(previous)!=payload(rows[0]) or previous.get('source_sha256')!=rows[0].get('source_sha256'):
            admitted[identity]=deepcopy(rows[0])
    for identity,row in admitted.items():
        value=fields(row);scope=scope_of(value);entry=ledger(scope)
        # Entries absent from a new input are not silently deleted.
        if identity not in seen_identities:
            issue(scope,'missing-ledger:'+str(identity),'Previously observed opening entry is absent; confirm explicit replacement/disposition',[ref(row)])
        amount=_cents(value['Allocation or commitment (EUR)']);settled=_cents(value['Settled (EUR)']);refund=_cents(value['Refunded (EUR)'])
        fact=dict(ledger_id=identity,amount_cents=amount,settled_cents=settled,refunded_cents=refund,
                  revision=value.get('Revision'),arrival_batch=value.get('Arrival batch'),source_version=row['source_sha256'],
                  source_refs=[ref(row)],source_record=deepcopy(row))
        key='allocations' if value['Entry type']=='allocation' else 'opening_obligations'
        target=identity if key=='allocations' else value['Obligation reference']
        if target in entry[key]:
            if {k:v for k,v in entry[key][target].items() if k not in {'source_record','source_refs','ledger_id'}}!={k:v for k,v in fact.items() if k not in {'source_record','source_refs','ledger_id'}}:
                issue(scope,'duplicate-obligation:'+target,'Multiple ledger identities disagree about one historical obligation',[ref(row)]+entry[key][target]['source_refs'])
            else:entry[key][target]['source_refs'].append(ref(row))
        else:entry[key][target]=fact
        entry['source_refs'].append(ref(row))
    request_scopes={};event_seen={}
    def event_scope(value):
        if value.get('Request reference') in request_scopes:return request_scopes[value['Request reference']]
        matches=[r for r in people if fields(r).get('Payee ID')==value.get('Payee ID') and source_bound(r,observations)]
        return scope_of(fields(matches[0])) if len(matches)==1 else None
    for claim_id,finance in finances.items():
        revisions=history.get('claim',{}).get(claim_id,{}).get('revisions',[])
        for event in sorted(finance.get('admitted_events',{}).values(),key=lambda e:(e['classification']!='obligation_accepted',utc_time(e['source_record']['Activity time (UTC)']))):
            value=event['source_record'];request=value.get('Request reference');batch=_revision(value.get('Arrival batch'))
            available=[r for r in revisions if _revision(r.get('arrival_batch')) and _revision(r['arrival_batch'])<=batch] if batch else []
            explicit=_revision(value.get('Claim revision'))
            candidates=[r for r in available if r['revision']==explicit] if explicit else [r for r in available if r['revision']==max((x['revision'] for x in available),default=None)]
            person=directory(fields(candidates[0]['record']).get('Employee')) if len(candidates)==1 else None
            scope=scope_of(fields(person)) if person else None
            original_scope=scope
            if request in request_scopes:scope=request_scopes[request]
            if event['classification']=='obligation_accepted':
                if request in request_scopes and request_scopes[request]!=original_scope:
                    issue(scope,'request-scope:'+request,'Request ownership conflicts across budget scopes',[ref(event['source_ref'])])
                request_scopes.setdefault(request,scope)
            entry=ledger(scope);entry['source_refs'].append(ref(event['source_ref']))
            if scope is None:issue(None,'event-scope:'+event['event_id'],'Admitted Finance event lacks an unambiguous historical budget scope',[ref(event['source_ref'])])
            if event['event_id'] in event_seen:
                if event_seen[event['event_id']]!=event:issue(scope,'event-identity:'+event['event_id'],'Finance identity disagrees across admitted histories',[ref(event['source_ref'])])
                continue
            event_seen[event['event_id']]=deepcopy(event)
            if not source_bound(event['source_ref'],observations):
                issue(scope,'event-source:'+event['event_id'],'Admitted Finance fact lacks a verified retained source binding for budget use',[ref(event['source_ref'])])
            req=entry['requests'].setdefault(request,dict(request_id=request,claim_id=claim_id,events=[],source_refs=[],
                commitment_cents=None,confirmed_payment_cents=0,confirmed_refund_cents=0,authorized_obligation_cents=None))
            if req['claim_id']!=claim_id:issue(scope,'request-owner:'+request,'Stable request ID is used by different claims',req['source_refs']+[ref(event['source_ref'])])
            req['events'].append(deepcopy(event));req['source_refs'].append(ref(event['source_ref']))
            if finance.get('authorized_obligation') is not None:
                req['authorized_obligation_cents']=finance['authorized_obligation']['amount_cents']
        for conflict in finance.get('conflicting_events',[]):
            value=next((e['source_record'] for e in finance.get('event_history',[]) if e['event_id']==conflict['event_id']),{})
            scope=event_scope(value)
            issue(scope,'finance-conflict:'+conflict['event_id'],'Conflicting Finance replay holds the scope without erasing admitted commitments/cash',
                  [ref(r) for r in conflict.get('source_refs',[])])
        for unresolved in [e for e in finance.get('event_history',[]) if e['event_id'] not in finance.get('admitted_events',{})]:
            value=unresolved.get('source_record',{});scope=event_scope(value)
            issue(scope,'finance-unresolved:'+str(unresolved.get('event_id')),'Unresolved Finance event may affect available budget',[ref(unresolved['source_ref'])])
    for key,entry in list(scopes.items()):
        for request,req in entry['requests'].items():
            controls=[]
            for event in req['events']:
                category=event['classification']
                if category=='finance_cancelled' and event.get('original_activity_id'):
                    issue(tuple(entry['scope'][k] for k in SCOPE) if entry['scope'] else None,'attempt-cancel:'+event['event_id'],
                          'Finance cancellation names a transfer activity; disposition of the accepted request commitment remains unconfirmed',req['source_refs'])
                elif category in {'obligation_accepted','finance_adjustment','finance_cancelled'}:
                    controls.append(event)
                if category=='confirmed_payment':req['confirmed_payment_cents']+=event['amount_cents']
                if category=='confirmed_refund':req['confirmed_refund_cents']+=event['amount_cents']
            controls.sort(key=lambda e:(utc_time(e['source_record']['Activity time (UTC)']),e['event_id']))
            for left,right in zip(controls,controls[1:]):
                if utc_time(left['source_record']['Activity time (UTC)'])==utc_time(right['source_record']['Activity time (UTC)']) and left['obligation_cents']!=right['obligation_cents']:
                    issue(tuple(entry['scope'][k] for k in SCOPE) if entry['scope'] else None,'control-order:'+request,'Request controls conflict at the same UTC time',req['source_refs'])
            for resolution in (e for e in req['events'] if e['classification']=='finance_resolution'):
                earlier=[e for e in controls if utc_time(e['source_record']['Activity time (UTC)'])<=utc_time(resolution['source_record']['Activity time (UTC)'])]
                amount=(0 if earlier[-1]['classification']=='finance_cancelled' else earlier[-1]['obligation_cents']) if earlier else None
                if amount is None or resolution['obligation_cents'] != amount:
                    issue(tuple(entry['scope'][k] for k in SCOPE) if entry['scope'] else None,'resolution-basis:'+resolution['event_id'],
                          'Finance resolution cannot create/change a commitment without acceptance, adjustment or request cancellation',req['source_refs'])
            accepted=[e for e in controls if e['classification']=='obligation_accepted']
            if accepted:
                req['commitment_cents']=0 if controls[-1]['classification']=='finance_cancelled' else controls[-1]['obligation_cents']
                req['acceptance']=deepcopy(accepted[0])
            else:issue(tuple(entry['scope'][k] for k in SCOPE) if entry['scope'] else None,'missing-acceptance:'+str(request),'Cash/control has no admitted original accepted obligation',req['source_refs'])
            opening=entry['opening_obligations'].get(request)
            if opening:
                # A native opening summary and full event history for the same
                # request must agree; neither is an additional obligation.
                if (opening['amount_cents'],opening['settled_cents'],opening['refunded_cents'])!=(req['commitment_cents'],req['confirmed_payment_cents'],req['confirmed_refund_cents']):
                    issue(tuple(entry['scope'][k] for k in SCOPE) if entry['scope'] else None,'opening-overlap:'+request,'Opening/request overlap lacks an explicit snapshot boundary; totals disagree',opening['source_refs']+req['source_refs'])
                entry['opening_obligations'].pop(request)
            req['net_paid_cents']=req['confirmed_payment_cents']-req['confirmed_refund_cents']
            req['remaining_commitment_cents']=max(0,req['commitment_cents']-req['net_paid_cents']) if req['commitment_cents'] is not None else None
            req['recorded_balance_cents']=req['commitment_cents']-req['net_paid_cents'] if req['commitment_cents'] is not None else None
    # Raw unmatched/held imports remain reviewable and cannot disappear from scope risk.
    represented={e['event_id'] for f in finances.values() for e in f.get('event_history',[])}
    for row in raw_finance:
        v=fields(row)
        if v.get('Activity reference') in represented:continue
        matches=[r for r in people if fields(r).get('Payee ID')==v.get('Payee ID') and source_bound(r,observations)]
        scope=scope_of(fields(matches[0])) if len(matches)==1 else None
        issue(scope,'unmatched:'+str(v.get('Activity reference')),'Unmatched Finance import may affect scope budget; retained without cash admission',[ref(row)])
    global_unknown_risk=bool(scopes.get('unassigned',{}).get('issues'))
    for key,entry in scopes.items():
        opening=list(entry['opening_obligations'].values());requests=list(entry['requests'].values())
        entry['allocation_cents']=sum(v['amount_cents'] for v in entry['allocations'].values()) if entry['allocations'] else None
        entry['historical_net_settled_cents']=sum(v['settled_cents']-v['refunded_cents'] for v in opening)
        entry['confirmed_payment_cents']=sum(v['confirmed_payment_cents'] for v in requests)
        entry['confirmed_refund_cents']=sum(v['confirmed_refund_cents'] for v in requests)
        entry['net_settled_cents']=entry['historical_net_settled_cents']+entry['confirmed_payment_cents']-entry['confirmed_refund_cents']
        entry['remaining_commitment_cents']=sum(max(0,v['amount_cents']-(v['settled_cents']-v['refunded_cents'])) for v in opening)+sum(v['remaining_commitment_cents'] or 0 for v in requests)
        if not entry['allocations']:
            issue(tuple(entry['scope'][k] for k in SCOPE) if entry['scope'] else None,'allocation-missing','No source-backed allocation for this exact department/project/period',entry['source_refs'],owner='Budget owner')
        valid=policy_valid(parsed.get('expense_policy')) and not entry['issues'] and not global_unknown_risk
        entry['available_cents']=entry['allocation_cents']-entry['net_settled_cents']-entry['remaining_commitment_cents'] if valid else None
        entry['known_available_cents']=entry['allocation_cents']-entry['net_settled_cents']-entry['remaining_commitment_cents'] if entry['allocation_cents'] is not None else None
        entry['status']='PASS' if valid else 'BLOCKED'
        entry['fingerprint']=fingerprint(dict(allocations=entry['allocations'],opening=entry['opening_obligations'],requests={k:dict(amount=v['commitment_cents'],claim=v['claim_id']) for k,v in entry['requests'].items()}))
        entry['source_refs']=list(dict.fromkeys(entry['source_refs']))
    return dict(scopes=scopes,issues=issues,admitted_budget_entries=admitted,arrival_batch=arrival_batch,
                budget_deliveries=deepcopy(table(parsed,'budget','Budget')),
                policy_verified=policy_valid(parsed.get('expense_policy')),
                policy_source_refs=[f"{(parsed.get('expense_policy') or {}).get('path')}@{(parsed.get('expense_policy') or {}).get('sha256')}#line {n}" for n in (13,17,19)] if policy_valid(parsed.get('expense_policy')) else [])


def cost_signature(record,line):
    v=fields(record)
    return (v.get('Employee'),v.get('Trip reference'),line['cost_id'],line['receipt_id'],line['currency'],line['original_amount'])


def attribute_costs(*,parsed,history,budgets,arrival_batch,observations,cancellations=()):
    """Map discrete supported lines to stable requests; never prorate an aggregate."""
    from .ordinary import expense_lines
    index=defaultdict(list);unknown=defaultdict(list);requests={}
    for scope in budgets['scopes'].values():
        for request,row in scope['requests'].items():requests[request]=row
    ordered=sorted((r for r in requests.values() if r.get('acceptance')),
                   key=lambda r:(utc_time(r['acceptance']['source_record']['Activity time (UTC)']),r['request_id']))
    for request in ordered:
        claim_id=request['claim_id'];accept=request['acceptance'];v=accept['source_record']
        revisions=history.get('claim',{}).get(claim_id,{}).get('revisions',[])
        explicit=_revision(v.get('Claim revision'));batch=_revision(v.get('Arrival batch'))
        eligible=[r for r in revisions if _revision(r.get('arrival_batch')) and _revision(r['arrival_batch'])<=batch]
        selected=[r for r in eligible if r['revision']==explicit] if explicit else [r for r in eligible if r['revision']==max((x['revision'] for x in eligible),default=None)]
        if len(selected)!=1:continue
        source=selected[0];record=source['record'];value=fields(record);lines=expense_lines(record)
        trips=[r for r in table(parsed,'trips','Trips') if fields(r).get('Trip reference')==value.get('Trip reference')
               and _revision(fields(r).get('Trip revision'))==_revision(value.get('Trip revision'))]
        context=[finding('travel_cancellation','Retained cancellation disposition context',c.get('source_refs',[]),c['cancellation_id'])
                 for c in cancellations if c['cancellation_id']==value.get('Travel cancellation reference')]
        evaluate_expenses(lines=lines,parsed=parsed,employee=value.get('Employee'),trip_id=value.get('Trip reference'),
            trip=fields(trips[0]) if len(trips)==1 else {},record=record,history=eligible,fields=fields,ref=ref,table=table,
            observations=observations,eligibility_findings=context)
        related=set(str(value.get('Related earlier claims') or '').splitlines())-{'None'}
        new=[];valid=bool(lines) and len({l['cost_id'] for l in lines})==len(lines)
        for line in lines:
            previous=[x for x in index[line['cost_id']] if x['claim_id'] in related and x['signature']==list(cost_signature(record,line))]
            if index[line['cost_id']] and not previous:valid=False
            if previous:continue
            if line.get('calculated_cents') is None:valid=False
            new.append(line)
        total=sum(l['calculated_cents'] or 0 for l in new)
        # Original acceptance must match the supported new-cost lines. Later
        # control amounts remain aggregate unless one cost makes allocation exact.
        if not valid or total!=accept['obligation_cents']:
            for line in new:unknown[line['cost_id']].append(dict(claim_id=claim_id,request_id=request['request_id'],source_refs=request['source_refs']+[ref(record)]))
            continue
        current=request['commitment_cents']
        if current is None:continue
        if current!=total and len(new)>1:
            for line in new:unknown[line['cost_id']].append(dict(claim_id=claim_id,request_id=request['request_id'],source_refs=request['source_refs']+[ref(record)]))
            continue
        for line in new:
            committed=current if len(new)==1 else line['calculated_cents']
            paid=request['net_paid_cents'] if len(new)==1 else line['calculated_cents'] if request['net_paid_cents']==total else 0 if request['net_paid_cents']==0 else None
            index[line['cost_id']].append(dict(cost_id=line['cost_id'],claim_id=claim_id,claim_revision=source['revision'],
                claim_revision_link='explicit' if explicit else 'arrival-context-only; not approval',request_id=request['request_id'],
                signature=list(cost_signature(record,line)),committed_cents=committed,net_paid_cents=paid,
                reserved_cents=max(committed,paid or 0),source_refs=list(dict.fromkeys([ref(record)]+line['source_refs']+request['source_refs'])),
                event_ids=[e['event_id'] for e in request['events']]))
    return dict(costs=dict(index),unallocated_costs=dict(unknown))


def version_context(parsed,ledger,prior):
    from .approvals import versions
    opening=fingerprint(dict(allocations=ledger['allocations'],opening=ledger['opening_obligations']))
    exact=bool(prior and (prior.get('opening_fingerprint')!=opening or prior.get('requires_exact_source')))
    ids={r.split('@',1)[0] for r in ledger['source_refs']}
    printed=set()
    for sheet in parsed.get('workbook_sheets',[]):
        if sheet.get('source_id') in ids:
            printed.update(versions({'text':'\n'.join(str(c.get('value','')) for c in sheet.get('preamble',[]))}))
    return dict(opening_fingerprint=opening,requires_exact_source=exact,printed_source_versions=sorted(printed))


def claim_budget_view(*,parsed,claim,lines,budgets,attribution,prior=None,arrival_batch):
    record=claim['record'];v=fields(record)
    people=[r for r in table(parsed,'people','People') if fields(r).get('Employee ID')==v.get('Employee')]
    person=fields(people[0]) if len(people)==1 else {};scope=scope_id(scope_of(person));ledger=budgets['scopes'].get(scope)
    result=dict(scope_id=scope,owner=person.get('Budget owner') or 'Budget owner',status='BLOCKED',issues=[],source_refs=[ref(record)],
                prior_committed_cents=0,prior_net_paid_cents=0,remaining_request_cents=None,lines=[])
    related=set(str(v.get('Related earlier claims') or '').splitlines())-{'None'}
    for line in lines:
        others=[x for x in attribution['costs'].get(line['cost_id'],[]) if x['claim_id']!=claim['subject_id'] and x['reserved_cents']>0]
        unknown=[x for x in attribution['unallocated_costs'].get(line['cost_id'],[]) if x['claim_id']!=claim['subject_id']]
        valid=[x for x in others if x['claim_id'] in related and x['signature']==list(cost_signature(record,line))]
        reason=None
        if unknown:reason='Shared cost has an aggregate request without supported cost allocation'
        if len(valid)!=len(others) or len(valid)>1:reason='Shared cost needs exact earlier-claim/employee/trip/receipt/amount linkage without duplicate commitments'
        consumed=sum(x['reserved_cents'] for x in valid)
        allowed=line.get('calculated_cents')
        if allowed is not None and consumed>allowed:reason='Prior cost commitments/payments exceed current calculated cost; Finance disposition required'
        remaining=allowed-consumed if allowed is not None and not reason else None
        refs=[r for x in others+unknown for r in x['source_refs']]
        result['source_refs']+=refs
        if reason:result['issues'].append(dict(reason=reason,source_refs=line['source_refs']+refs,owner='Finance',next_action='Resolve exact cost/request attribution and any adjustment; never prorate or repay an existing cost'))
        result['lines'].append(dict(cost_id=line['cost_id'],remaining_request_cents=remaining,prior_reservations=valid,source_refs=line['source_refs']+refs))
        result['prior_committed_cents']+=sum(x['committed_cents'] for x in valid)
        if result['prior_net_paid_cents'] is not None:
            result['prior_net_paid_cents']=None if any(x['net_paid_cents'] is None for x in valid) else result['prior_net_paid_cents']+sum(x['net_paid_cents'] for x in valid)
    complete=bool(lines) and len({l['cost_id'] for l in lines})==len(lines) and all(l.get('calculation_status')=='PASS' and l.get('evidence_status')=='PASS' for l in lines) and all(l['remaining_request_cents'] is not None for l in result['lines'])
    result['remaining_request_cents']=sum(l['remaining_request_cents'] for l in result['lines']) if complete else None
    if ledger:
        result.update(version_context(parsed,ledger,prior))
        result.update(available_cents=ledger['available_cents'],ledger_status=ledger['status'],ledger_refs=list(ledger['allocations'])+[x['ledger_id'] for x in ledger['opening_obligations'].values()])
        own=[r for r in ledger['requests'].values() if r['claim_id']==claim['subject_id']]
        matching_own={x['request_id'] for line in lines for x in attribution['costs'].get(line['cost_id'],[])
            if x['claim_id']==claim['subject_id'] and x['signature']==list(cost_signature(record,line))}
        result['existing_recorded_commitment_cents']=sum(r['commitment_cents'] or 0 for r in own if r['request_id'] in matching_own)
        result['incremental_cents']=max(0,result['remaining_request_cents']-result['existing_recorded_commitment_cents']) if complete else None
        result['source_refs']+=ledger['source_refs'];result['issues']+=ledger['issues']
        context=dict(allocations=ledger['allocations'],opening=ledger['opening_obligations'],others={k:dict(amount=r['commitment_cents'],used=max(r['commitment_cents'] or 0,r['net_paid_cents'])) for k,r in ledger['requests'].items() if r['claim_id']!=claim['subject_id']})
        result['context_fingerprint']=fingerprint(context)
        result['material_batch']=(prior.get('material_batch') or arrival_batch) if prior and (prior.get('context_fingerprint')!=result['context_fingerprint'] or prior.get('material_batch')) else None
        result['scope_source_refs']=ledger['source_refs']
        result['material_event_times']=[e['source_record']['Activity time (UTC)'] for r in ledger['requests'].values() for e in r['events']
            if (r['claim_id']!=claim['subject_id'] and e['classification'] in {'obligation_accepted','finance_adjustment','finance_resolution','finance_cancelled'})
            or (r['claim_id']==claim['subject_id'] and e['classification'] in {'finance_adjustment','finance_resolution','finance_cancelled'})
            or (r['net_paid_cents']>(r['commitment_cents'] or 0) and e['classification'] in {'confirmed_payment','confirmed_refund'})]
        enough=ledger['available_cents'] is not None and result['incremental_cents'] is not None and ledger['available_cents']>=result['incremental_cents']
        if not enough:result['issues'].append(dict(reason='Available budget is missing, exhausted or below the incremental request',owner=result['owner'],source_refs=ledger['source_refs'],next_action='Budget owner to review the complete ledger and supply a current funding decision; no allocation is inferred'))
        result['status']='PASS' if complete and enough and not result['issues'] else 'BLOCKED'
    else:result['issues'].append(dict(reason='No complete budget ledger for employee department/project/period',owner=result['owner'],source_refs=[ref(record)],next_action='Supply the exact scope ledger and allocation'))
    result['source_refs']=list(dict.fromkeys(result['source_refs']))
    return result


def budget_reply_error(context,decision,packet):
    """Additional budget-role dependency only; no other review role is redefined."""
    if not context or fields(decision).get('Outcome')!='approve':return None
    if context['status']!='PASS':return 'Budget context is incomplete or insufficient'
    v=fields(decision);p=fields(packet)
    supplied=set(str(p.get('Budget record references') or '').splitlines())
    if not set(context.get('ledger_refs',[]))<=supplied:return 'Budget owner packet omits scope ledger records'
    try:
        if any(utc_time(t)>utc_time(v.get('Decision time (UTC)')) for t in context.get('material_event_times',[])):
            return 'Budget reply predates an accepted request/material Finance commitment change'
    except (ValueError,TypeError):return 'Unconfirmed budget review/event timing'
    if context.get('material_batch'):
        if (_revision(v.get('Arrival batch')) or 0)<context['material_batch']:return 'Budget reply predates material scope ledger change'
        versions=set(str(v.get('Source revisions') or '').splitlines())
        exact=any(r in versions or r.split('@',1)[1].split('#',1)[0] in versions for r in context.get('scope_source_refs',[]))
        printed=bool(set(context.get('printed_source_versions',[])) & versions)
        if not exact and (context.get('requires_exact_source') or not printed):
            return 'Budget reply lacks current exact scope-source version binding'
    return None


def permit_budget_context(*,parsed,trip_record,budgets,prior=None,arrival_batch):
    """A permit estimate is a forecast, not an invented accepted obligation."""
    v=fields(trip_record);people=[r for r in table(parsed,'people','People') if fields(r).get('Employee ID')==v.get('Employee ID')]
    scope=scope_id(scope_of(fields(people[0]))) if len(people)==1 else 'unassigned'
    ledger=budgets['scopes'].get(scope);amount=_cents(v.get('Estimate (EUR)'))
    result=dict(scope_id=scope,status='BLOCKED',forecast_cents=amount,source_refs=[ref(trip_record)],
                ledger_refs=[],scope_source_refs=[],material_event_times=[])
    if not ledger:return result
    result.update(version_context(parsed,ledger,prior))
    result.update(source_refs=ledger['source_refs']+[ref(trip_record)],scope_source_refs=ledger['source_refs'],
        ledger_refs=list(ledger['allocations'])+[x['ledger_id'] for x in ledger['opening_obligations'].values()],
        context_fingerprint=ledger['fingerprint'],available_cents=ledger['available_cents'])
    result['material_batch']=(prior.get('material_batch') or arrival_batch) if prior and (prior.get('context_fingerprint')!=result['context_fingerprint'] or prior.get('material_batch')) else None
    result['material_event_times']=[e['source_record']['Activity time (UTC)'] for r in ledger['requests'].values() for e in r['events']
        if e['classification'] in {'obligation_accepted','finance_adjustment','finance_resolution','finance_cancelled'}]
    result['status']='PASS' if ledger['status']=='PASS' and amount is not None and ledger['available_cents'] is not None and ledger['available_cents']>=amount else 'BLOCKED'
    return result
