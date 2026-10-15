"""Supplemental browser policy evidence; never a native Notion acquisition."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .expenses import load_expense_policy, POLICY_SHA256
from .sources import verify_source_manifest, SOURCES

POLICY_PATH = 'supplemental/POL-2026.2-browser-copy.txt'
EVIDENCE_PATH = 'supplemental-policy.json'
CLOCK = {'date': '2026-11-15', 'timezone': 'Europe/Amsterdam'}
PROVENANCE = 'user-provided browser-visible copy; not native HTTP/API retrieval'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata():
    return dict(schema_version='supplemental-policy/1', policy_version='POL-2026.2',
                path=POLICY_PATH, sha256=POLICY_SHA256, provenance=PROVENANCE,
                native_acquisition=False, source_url=SOURCES[0].url,
                attestation='User personally copied the complete visible text from the original Notion page; remote block-tree completeness not independently verified',
                retrieval_time=None, case_clock=dict(CLOCK, precision='calendar-date'),
                source_refs=[f'{POLICY_PATH}@{POLICY_SHA256}#line {n}' for n in range(1, 34)])


def apply_policy(parsed, binding):
    """Bind verified supplemental evidence without supplying business authority."""
    parsed = deepcopy(parsed)
    # Stable relative paths make references independent of the caller's cwd.
    parsed.update(expense_policy=binding, event_clock=deepcopy(CLOCK),
                  supplemental_policy=metadata())
    # Keep the native clock and policy-access observation intact. Only the
    # historical wholly-unknown-clock issue is superseded by explicit evidence.
    parsed['case_clock_issue'] = None
    parsed['unresolved_issues'] = [i for i in parsed.get('unresolved_issues', [])
                                  if i.get('record_id') != 'scenario-case-clock']
    for issue in parsed['unresolved_issues']:
        if issue.get('record_id') == 'reimbursement-policy-pol-2026-2':
            issue.update(reason='Native Notion content remains inaccessible or incomplete; verified supplemental browser policy is separately bound.',
                         affected_scope='fresh native-source compliance; supplemental policy wording is available',
                         evidence_needed='Complete fresh native Notion acquisition; do not substitute browser provenance')
    return parsed


def verify_policy_evidence(run_dir, parsed=None):
    """Return the bound sidecar identity; reject missing/tampered evidence."""
    run_dir = Path(run_dir)
    obj = json.loads((run_dir / EVIDENCE_PATH).read_text(encoding='utf-8'))
    if obj != metadata():
        raise ValueError('Supplemental policy provenance/version/date evidence differs from verified policy')
    binding = load_expense_policy(run_dir / POLICY_PATH)
    binding['path'] = POLICY_PATH
    if parsed is not None:
        if (parsed.get('expense_policy') != binding or parsed.get('event_clock') != CLOCK
                or parsed.get('supplemental_policy') != obj or parsed.get('case_clock_issue')):
            raise ValueError('Parsed supplemental policy/clock binding mismatch')
    verify_lineage(run_dir, parsed)
    return {'path': EVIDENCE_PATH, 'sha256': digest(run_dir / EVIDENCE_PATH)}


def create_policy_replay(source_dir, run_dir, *, run_id, browser_policy, schema_path):
    """Create a new retained-input run, preserving native observation payloads."""
    from .offline_replay import run_offline_replay
    source_dir, run_dir = Path(source_dir).resolve(), Path(run_dir).resolve()
    policy = load_expense_policy(browser_policy)  # Validate before creating anything.
    if not run_id or run_dir.name != run_id:
        raise ValueError('New run directory name must equal the explicit run ID')
    if run_dir == source_dir or run_dir.is_relative_to(source_dir):
        raise ValueError('New retained-input run must be outside the source run')
    errors = verify_source_manifest(source_dir)
    if errors:
        raise ValueError('; '.join(errors))
    manifest = json.loads((source_dir / 'sources.json').read_text(encoding='utf-8'))
    parsed = json.loads((source_dir / 'parsed-records.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or not isinstance(parsed, dict):
        raise ValueError('Native manifest and parsed evidence must be objects')
    if run_id == manifest['run_id']:
        raise ValueError('New retained-input replay needs a distinct run ID')
    if parsed.get('run_id') != manifest['run_id'] or parsed.get('source_manifest') != {'path':'sources.json','sha256':digest(source_dir / 'sources.json')}:
        raise ValueError('Original parsed records do not bind retained native manifest')
    if parsed.get('expense_policy') or parsed.get('supplemental_policy'):
        raise ValueError('Use original native parsed inputs, not an already supplemented run')
    paths = set()
    for row in manifest['files']:
        paths.update(p for p in (row.get('path'), row.get('observation', {}).get('response_path')) if p)
    for relative in paths:
        if not (source_dir / relative).resolve().is_relative_to(source_dir):
            raise ValueError('Native evidence path escapes source run')
    run_dir.mkdir(parents=True, exist_ok=False)
    for relative in paths:
        target = run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write((source_dir / relative).read_bytes())
    (run_dir / 'supplemental').mkdir(exist_ok=True)
    (run_dir / POLICY_PATH).write_bytes(policy['text'].encode('utf-8'))
    for name in ('sources.json', 'parsed-records.json'):
        (run_dir / 'supplemental' / ('original-' + name)).write_bytes((source_dir / name).read_bytes())
    manifest['run_id'] = run_id  # All five original observation entries remain identical.
    (run_dir / 'sources.json').write_text(json.dumps(manifest, indent=2) + '\n')
    policy['path'] = POLICY_PATH
    parsed = apply_policy(parsed, policy)
    parsed.update(run_id=run_id, expense_policy=policy,
                  source_manifest={'path':'sources.json','sha256':digest(run_dir / 'sources.json')})
    (run_dir / EVIDENCE_PATH).write_text(json.dumps(metadata(), indent=2) + '\n')
    (run_dir / 'retained-input-lineage.json').write_text(json.dumps(dict(
        mode='offline-replay', fresh_native_reads_performed=False, original_run_id=json.loads((source_dir / 'sources.json').read_text(encoding='utf-8'))['run_id'],
        original_inputs={name: {'path':'supplemental/original-'+name, 'sha256':digest(source_dir/name)} for name in ('sources.json','parsed-records.json')}), indent=2) + '\n')
    (run_dir / 'parsed-records.json').write_text(json.dumps(parsed, indent=2, ensure_ascii=False) + '\n')
    verify_policy_evidence(run_dir, parsed)
    return run_offline_replay(run_dir, schema_path=schema_path)


def verify_lineage(run_dir, parsed=None):
    lineage = json.loads((run_dir / 'retained-input-lineage.json').read_text(encoding='utf-8'))
    if not isinstance(lineage, dict):
        raise ValueError('Supplemental lineage must be an object')
    if lineage.get('mode') != 'offline-replay' or lineage.get('fresh_native_reads_performed') is not False:
        raise ValueError('Supplemental lineage must be retained-input offline replay')
    originals = {}
    for name in ('sources.json', 'parsed-records.json'):
        item = lineage['original_inputs'][name]
        expected = 'supplemental/original-' + name
        if item['path'] != expected or digest(run_dir / expected) != item['sha256']:
            raise ValueError('Original retained input lineage hash mismatch')
        originals[name] = json.loads((run_dir / expected).read_text(encoding='utf-8'))
    original = originals['sources.json']
    native = json.loads((run_dir / 'sources.json').read_text(encoding='utf-8'))
    if (original['run_id'] != lineage['original_run_id'] or original['run_id'] == native['run_id']
            or {k:v for k,v in original.items() if k != 'run_id'} != {k:v for k,v in native.items() if k != 'run_id'}):
        raise ValueError('Native acquisition observations changed in supplemental replay')
    base = originals['parsed-records.json']
    if base.get('source_manifest') != {'path':'sources.json', 'sha256':digest(run_dir / 'supplemental/original-sources.json')} or base.get('run_id') != original['run_id']:
        raise ValueError('Original parsed input manifest binding mismatch')
    if parsed is not None:
        expected = apply_policy(base, parsed['expense_policy'])
        expected.update(run_id=native['run_id'], source_manifest={'path':'sources.json', 'sha256':digest(run_dir / 'sources.json')})
        if parsed != expected:
            raise ValueError('Supplemental replay changed original parsed source observations')
