"""Connected CLI examples with explicitly synthetic native-format documents.

No fixture grants real employee, reviewer or Finance authority.
"""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path

from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
import pytest

from travel_claim.cli import main
from travel_claim.parsing import parse_retained_run, _pdf_pages, _receipt_records
from travel_claim.policy_evidence import create_policy_replay
from travel_claim.receipt_continuation import verify_continuation
from travel_claim.sources import SOURCES, WORKBOOK_TABS, capture_sources

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'snapshot.schema.json'
POLICY = ROOT / 'tests/fixtures/POL-2026.2-browser-copy.txt'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pdf(texts):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        commands = ['BT /F1 10 Tf 20 770 Td']
        for line in text.splitlines():
            line = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            commands.append(f'({line}) Tj 0 -14 Td')
        commands.append('ET')
        stream = DecodedStreamObject(); stream.set_data('\n'.join(commands).encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    buffer = io.BytesIO(); writer.write(buffer)
    return buffer.getvalue()


def receipt(cid='A', amount='100.00'):
    return f'''SYNTHETIC employee receipt
Receipt reference: R-COST-{cid}
Expense reference: COST-{cid}
Employee: EMP-01
Trip reference: T-{cid}
Category: transport
Gross amount: {amount}
Currency: EUR
Documented units: 1'''


def base_run(tmp_path, *, unpaid=False):
    # Retained schema examples supply field names, not source authority.
    sample = json.loads((ROOT / 'tests/fixtures/ordinary_claim_c01.json').read_text())
    workbook = Workbook(); workbook.remove(workbook.active)
    flat = lambda row: {k: v['value'] for k, v in row['values'].items()}
    sheets = {s['name']: [flat(r) for r in s['records']] for s in sample['workbook_sheets']}
    sheets['Trips'] = []
    sheets['Merchant payments'] = []
    for cid in 'ABC':
        trip = flat(sample['records']['trips'][0]); trip['Trip reference'] = 'T-' + cid
        sheets['Trips'].append(trip)
        merchant = flat(sample['workbook_sheets'][1]['records'][0])
        merchant.update({'Transaction reference': 'M-' + cid, 'Expense reference': 'COST-' + cid,
                         'Trip reference': 'T-' + cid, 'Receipt reference': 'R-COST-' + cid})
        if unpaid and cid == 'A':
            merchant['Payment status'] = 'pending'
        sheets['Merchant payments'].append(merchant)
    sheets['Review ledger'] = []; sheets['Review packets'] = []; sheets['Travel cancellations'] = []
    for name in WORKBOOK_TABS:
        sheets.setdefault(name, [])
    sheets['Finance activity'] = []
    for cid, accepted_batch, paid_batch in [('A', 1, 2), ('C', 3, 4)]:
        common = {'Request reference': 'REQ-' + cid, 'Claim reference': 'SYN-' + cid,
                  'Finance officer': 'FIN-01', 'Payee ID': 'EMP-01', 'Currency': 'EUR',
                  'Reason': 'SYNTHETIC supplied Finance observation'}
        sheets['Finance activity'] += [dict(common, **{'Activity reference': 'F-' + cid + '-accepted',
            'Arrival batch': accepted_batch, 'Activity type': 'accepted', 'Obligation (EUR)': 100,
            'Activity time (UTC)': '2026-09-11T12:00:00'}),
            dict(common, **{'Activity reference': 'F-' + cid + '-settled', 'Arrival batch': paid_batch,
            'Activity type': 'settled', 'Amount (EUR)': 100, 'Activity time (UTC)': '2026-09-12T12:00:00'})]
    duplicate = deepcopy(sheets['Finance activity'][1]); duplicate['Arrival batch'] = 4
    sheets['Finance activity'].append(duplicate)
    for name, rows in sheets.items():
        tab = workbook.create_sheet(name)
        tab.append(['SYNTHETIC DW-D-2; fictional test evidence'])
        if rows:
            headers = list(dict.fromkeys(k for row in rows for k in row))
            tab.append(headers)
            for row in rows: tab.append([row.get(k) for k in headers])
    buffer = io.BytesIO(); workbook.save(buffer)
    claims = [f'''SYNTHETIC claim
Claim reference: SYN-{cid}
Revision: 1
Arrival batch: 1
Employee: EMP-01
Trip reference: T-{cid}
Trip revision: 1
Submitted date: 2026-09-01
Status: submitted
Claim reason: Synthetic missing-receipt continuation
Related earlier claims: None
1 COST-{cid} R-COST-{cid} 2026-09-01 100.00 EUR
Finance exception: Not supplied''' for cid in 'ABC']
    bodies = {'policy-pol-2026-2': b'generic policy shell',
        'initial-claim-binder': pdf(claims), 'claim-updates-binder': pdf(['SYNTHETIC no corrections']),
        'receipt-binder': pdf([receipt('C')]), 'travel-registers-workbook': buffer.getvalue()}
    def fetch(url, timeout):
        source = next(s for s in SOURCES if (s.export_url or s.url) == url)
        return bodies[source.source_id], {}, url
    source = tmp_path / 'synthetic-source'
    capture_sources(source, run_id=source.name, case_clock=None, fetch=fetch,
                    observed_at=lambda: '2026-10-01T12:00:00Z')
    parse_retained_run(source)
    parent = tmp_path / 'synthetic-parent'
    create_policy_replay(source, parent, run_id=parent.name, browser_policy=POLICY, schema_path=SCHEMA)
    return parent


def response_bundle(tmp_path, parent, *, amount='100.00'):
    evidence = tmp_path / 'incoming'; evidence.mkdir()
    path = evidence / 'receipt.pdf'; path.write_bytes(pdf([receipt(amount=amount)]))
    receipt_ref = f"employee-receipt@{sha(path)}#PDF page 1, receipt 1"
    a = 'ordinary:SYN-A:r1:supporting_evidence'; b = 'ordinary:SYN-B:r1:supporting_evidence'
    assessment = dict(item_id=a, subject_type='claim', subject_id='SYN-A', revision=1, actor_id='EMP-01',
        response_id='SYN-REPLY-1', sufficient=True, reason='SYNTHETIC employee supplied matching receipt',
        provenance='SYNTHETIC employee response retained for connected test', evidence_refs=[receipt_ref])
    proof = evidence / 'assessment.json'; proof.write_text(json.dumps({'assessment': assessment}))
    manifest = {'files': [dict(source_id=sid, path=f.name, sha256=sha(f), status='read',
        missing_scope=[], observed_at='2026-10-02T12:00:00Z', version=sha(f), error=None)
        for sid, f in [('employee-receipt', path), ('employee-assessment', proof)]]}
    (evidence / 'sources.json').write_text(json.dumps(manifest))
    response = tmp_path / 'response.json'
    response.write_text(json.dumps(dict(response_version='missing-receipt-response/1', response_id='SYN-REPLY-1',
        actor_id='EMP-01', item_outcomes={a: dict(outcome='supported', note='A receipt supplied',
            source_refs=[receipt_ref], receipt_ref=receipt_ref,
            assessment_ref=f"employee-assessment@{sha(proof)}#/assessment"),
            b: dict(outcome='insufficient', note='B receipt still missing', source_refs=[])})))
    return response, evidence


def command(parent, response, evidence, output):
    return ['continue-receipt', str(parent), str(response), str(output), '--evidence-dir', str(evidence),
            '--run-id', output.name]


def hashes(root):
    return {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file()}


def test_connected_receipt_continuation_and_persisted_replay(tmp_path):
    parent = base_run(tmp_path)
    before = hashes(parent)
    old = json.loads((parent / 'offline-replay-state.json').read_text())
    response, evidence = response_bundle(tmp_path, parent)
    output = tmp_path / 'receipt-result'
    assert main(command(parent, response, evidence, output)) == 0
    verify_continuation(output)
    state = json.loads((output / 'continuation-state.json').read_text())
    a = state['ordinary_workflows']['SYN-A']; b = state['ordinary_workflows']['SYN-B']
    assert next(s for s in a['stages'] if s['stage']=='supporting_evidence')['status'] == 'PASS'
    assert a['lines'][0]['evidence_status'] == 'PASS' and a['lines'][0]['original_cents'] == 10000
    assert a['status'] == 'pending' and a['request'] is None and a['balance_cents'] is None
    assert a['financial_basis']['latest_change'] and not a['claim_approval']['approved']
    assert next(s for s in a['stages'] if s['stage']=='required_approvals')['status'] == 'BLOCKED'
    assert b == old['ordinary_workflows']['SYN-B']
    assert state['ordinary_workflows']['SYN-C'] == old['ordinary_workflows']['SYN-C']
    assert state['finance_reconciliations'] == old['finance_reconciliations']
    assert state['decision_history'] == old['decision_history']
    assert state['cancellation_state'] == old['cancellation_state']
    queue = state['repair_queue']; aid='ordinary:SYN-A:r1:supporting_evidence'; bid='ordinary:SYN-B:r1:supporting_evidence'
    assert queue['items'][aid]['status'] == 'resolved'
    assert queue['items'][bid]['status'] == 'open'
    assert [e['note'] for e in queue['events'] if e['event']=='response-recorded'] == ['A receipt supplied', 'B receipt still missing']
    for key, item in old['repair_queue']['items'].items():
        if item['subject_id'] != 'SYN-A' and key != bid: assert queue['items'][key] == item
    drafts=(output/'follow-up-drafts.md').read_text()
    assert f'Item `{aid}`' not in drafts and f'Item `{bid}`' in drafts
    assert aid in (output/'report.md').read_text() and 'supporting_evidence=PASS' in (output/'report.md').read_text()
    assert len(state['parent_snapshot_hashes']) == 4
    assert not (output/'batches').exists()
    after=hashes(output)
    assert main(command(parent,response,evidence,output)) == 0
    assert hashes(output)==after and hashes(parent)==before


@pytest.mark.parametrize('fault',['hash','stale','actor','receipt','assessment','assessment-actor','assessment-revision',
                                'future','same-day','unknown-item','existing-receipt','missing-payment','forged-parsed'])
def test_bad_responses_do_not_create_results_or_change_history(tmp_path,fault):
    parent=base_run(tmp_path,unpaid=fault=='missing-payment'); before=hashes(parent)
    response,evidence=response_bundle(tmp_path,parent,amount='99.00' if fault=='receipt' else '100.00')
    obj=json.loads(response.read_text());aid='ordinary:SYN-A:r1:supporting_evidence'
    if fault=='hash': (evidence/'receipt.pdf').write_bytes((evidence/'receipt.pdf').read_bytes()+b'tampered')
    elif fault=='stale': obj['item_outcomes'][aid.replace(':r1:',':r2:')]=obj['item_outcomes'].pop(aid)
    elif fault=='actor':obj['actor_id']='UNAUTHORIZED'
    elif fault=='assessment':obj['item_outcomes'][aid]['assessment_ref']='employee-assessment@'+'0'*64+'#/assessment'
    elif fault in {'future','same-day'}:
        m=json.loads((evidence/'sources.json').read_text());m['files'][0]['observed_at']=('2026-11-16' if fault=='future' else '2026-11-15')+'T12:00:00Z';(evidence/'sources.json').write_text(json.dumps(m))
    elif fault in {'assessment-actor','assessment-revision'}:
        proof=evidence/'assessment.json';p=json.loads(proof.read_text())
        p['assessment']['actor_id' if fault=='assessment-actor' else 'revision']='UNAUTHORIZED' if fault=='assessment-actor' else 2
        proof.write_text(json.dumps(p));m=json.loads((evidence/'sources.json').read_text());m['files'][1]['sha256']=sha(proof)
        (evidence/'sources.json').write_text(json.dumps(m))
        obj['item_outcomes'][aid]['assessment_ref']=f"employee-assessment@{sha(proof)}#/assessment"
    elif fault=='forged-parsed':
        # A caller's fabricated transcription must not replace actual PDF facts.
        (evidence/'receipt.pdf').write_bytes(pdf([receipt(amount='99.00')]))
        (evidence/'parsed-records.json').write_text(json.dumps({'records':{'receipts':[{'Gross amount':'100.00'}]}}))
        m=json.loads((evidence/'sources.json').read_text());m['files'][0]['sha256']=sha(evidence/'receipt.pdf')
        (evidence/'sources.json').write_text(json.dumps(m))
        rr=f"employee-receipt@{sha(evidence/'receipt.pdf')}#PDF page 1, receipt 1"
        obj['item_outcomes'][aid].update(source_refs=[rr],receipt_ref=rr)
        proof=evidence/'assessment.json';p=json.loads(proof.read_text());p['assessment']['evidence_refs']=[rr];proof.write_text(json.dumps(p))
        m['files'][1]['sha256']=sha(proof);(evidence/'sources.json').write_text(json.dumps(m))
        obj['item_outcomes'][aid]['assessment_ref']=f"employee-assessment@{sha(proof)}#/assessment"
    elif fault=='unknown-item':obj['item_outcomes']['unknown']=dict(outcome='unanswered')
    elif fault=='existing-receipt':
        obj['item_outcomes']['ordinary:SYN-C:r1:supporting_evidence']=obj['item_outcomes'].pop(aid)
    response.write_text(json.dumps(obj));out=tmp_path/'rejected'
    assert main(command(parent,response,evidence,out)) == 1
    assert not out.exists() and hashes(parent)==before


def test_existing_result_tamper_and_conflicting_replay_are_rejected(tmp_path):
    parent=base_run(tmp_path);response,evidence=response_bundle(tmp_path,parent);out=tmp_path/'result'
    assert main(command(parent,response,evidence,out))==0
    before=hashes(out);obj=json.loads(response.read_text());obj['item_outcomes']['ordinary:SYN-B:r1:supporting_evidence']['note']='different delivery'
    response.write_text(json.dumps(obj))
    assert main(command(parent,response,evidence,out))==1 and hashes(out)==before
    (out/'claims.csv').write_text('corrupted')
    assert main(command(parent,response,evidence,out))==1
