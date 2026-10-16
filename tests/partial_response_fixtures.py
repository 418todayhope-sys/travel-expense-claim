"""Explicitly synthetic retained evidence and human sufficiency assessments."""
import hashlib
import json


def retained_response(root, queue, response_id, outcomes):
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for item_id, outcome in outcomes.items():
        if outcome['outcome'] != 'supported' or item_id not in queue['items']:
            continue
        item = queue['items'][item_id]
        records.append(dict(item_id=item_id, response_id=response_id,
            subject_type=item['subject_type'], subject_id=item['subject_id'], revision=item['revision'],
            sufficient=True, reason='SYNTHETIC human assessment: requested receipt matches the cost',
            evidence_refs=['SYNTHETIC-EVIDENCE'], provenance='synthetic human response fixture'))
    # Evidence and assessments use separate source identities to avoid circular hashes.
    evidence = root / 'evidence.json'
    evidence.write_text(json.dumps({'receipt': {'label': 'SYNTHETIC receipt'}}))
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    ref = f'synthetic-evidence@{digest}#/receipt'
    for row in records:
        row['evidence_refs'] = [ref]
    response = root / 'response.json'
    response.write_text(json.dumps(records))
    digest_response = hashlib.sha256(response.read_bytes()).hexdigest()
    for n, row in enumerate(records):
        outcomes[row['item_id']]['source_refs'] = [ref]
        outcomes[row['item_id']]['assessment_ref'] = f'synthetic-response@{digest_response}#/{n}'
    (root / 'sources.json').write_text(json.dumps({'files': [
        dict(source_id=sid, path=path.name, sha256=sha, status='read', missing_scope=[],
             observed_at='2026-10-16T12:00:00Z', version=sha, provenance='synthetic fixture')
        for sid, path, sha in [('synthetic-evidence', evidence, digest),
                               ('synthetic-response', response, digest_response)]
    ]}))
    return outcomes
