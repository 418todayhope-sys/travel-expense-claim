"""Read-only repository-relative checks for the retained v3 evidence package."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OPERATOR = ROOT / 'artifacts/runs/omega4-attempt002-ordinary-closure-operator-v3'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bound(base, item):
    path = (base / item['path']).resolve()
    if not path.is_relative_to(base.resolve()) or digest(path) != item['sha256']:
        raise ValueError('Hash/path binding mismatch: ' + item['path'])
    return path


def check():
    manifest = json.loads((HERE / 'manifest.json').read_text())
    for item in manifest['files'] + manifest['input_bindings']:
        bound(ROOT, item)
    operator = json.loads((OPERATOR / 'operator-manifest.v1.json').read_text())
    if len(operator['files']) != 22:
        raise ValueError('Unexpected bound operator inventory')
    for item in operator['files']:
        bound(OPERATOR, item)
    for item in operator['input_bindings']:
        bound(ROOT, item)
    previous = None
    for batch in range(1, 5):
        path = OPERATOR / f'batches/{batch:03}.json'
        snapshot = json.loads(path.read_text())
        if snapshot['predecessor'] != previous:
            raise ValueError('Broken predecessor link')
        for name in ('source_binding', 'queue_binding'):
            bound(OPERATOR, snapshot[name])
        closed = {c['claim_id']: c for c in snapshot['claims'] if c['status'] == 'closed-reimbursed'}
        expected = {} if batch == 1 else {'C01': 10000, 'C04': 10000, 'C05': 100000, 'C06': 100001}
        if set(closed) != set(expected):
            raise ValueError('Unexpected closure selection')
        for ident, amount in expected.items():
            claim = closed[ident]
            if (claim['allowed_cents'], claim['known_paid_cents'], claim['balance_cents']) != (amount, amount, 0):
                raise ValueError('Unexpected attributed money')
        previous = {'path': f'batches/{batch:03}.json', 'sha256': digest(path)}
    if len(snapshot['claims']) != 121 or sum(c['status'] == 'held' for c in snapshot['claims']) != 117:
        raise ValueError('Unexpected final claim counts')
    if sum(c['known_paid_cents'] for c in closed.values()) != 220001:
        raise ValueError('Unexpected selected closure total')
    for name, total in [('existing-tests.json', 39), ('supplemental-tests.json', 49)]:
        tests = json.loads((HERE / 'step2' / name).read_text())
        if tests['total'] != total or tests['passed'] != total or tests['failures'] or tests['errors'] or tests['skipped']:
            raise ValueError('Preserved test result differs')
    print(json.dumps({'checks': 'passed', 'snapshots': 4, 'bound_operator_files': 22,
                      'closures': 4, 'held_claims': 117, 'closed_total_cents': 220001,
                      'preserved_targeted_tests': 88, 'tests_rerun': False}, sort_keys=True))


if __name__ == '__main__':
    check()
