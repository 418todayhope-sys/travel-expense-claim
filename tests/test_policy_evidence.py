"""Supplemental browser evidence is reproducible and never native acquisition."""
import hashlib
import json
from pathlib import Path

import pytest

from test_offline_replay import _capture, SCHEMA
from test_readiness import _repo
from travel_claim.cli import main
from travel_claim.policy_evidence import create_policy_replay, verify_policy_evidence, CLOCK, POLICY_PATH
from travel_claim.readiness import validate_readiness
from travel_claim.snapshots import verify_snapshot
from travel_claim.event_validation import observation_error, utc_time

POLICY = Path(__file__).parent / 'fixtures/POL-2026.2-browser-copy.txt'


def inputs(tmp_path):
    source, _ = _capture(tmp_path)
    path = source / 'parsed-records.json'
    obj = json.loads(path.read_text())
    obj['records'] = {k: [] for k in obj['records']}
    path.write_text(json.dumps(obj))
    return source


def replay(tmp_path):
    source = inputs(tmp_path)
    run = tmp_path / 'supplemented'
    create_policy_replay(source, run, run_id=run.name, browser_policy=POLICY, schema_path=SCHEMA)
    return source, run


def test_cli_binds_exact_browser_copy_clock_lineage_and_keeps_native_failures(tmp_path, capsys):
    source = inputs(tmp_path)
    before = {str(p): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    run = tmp_path / 'new-policy-replay'
    assert main(['policy-replay', str(source), str(run), '--run-id', run.name, '--browser-policy', str(POLICY)]) == 0
    assert 'no time inferred' in capsys.readouterr().out
    assert (run / POLICY_PATH).read_bytes() == POLICY.read_bytes()
    native = json.loads((run / 'sources.json').read_text())
    assert native['files'] == json.loads((source / 'sources.json').read_text())['files']
    assert native['case_clock'] is None
    assert native['files'][0]['status'] == 'unavailable'
    parsed = json.loads((run / 'parsed-records.json').read_text())
    assert parsed['event_clock'] == CLOCK and parsed['case_clock'] is None
    assert parsed['supplemental_policy']['native_acquisition'] is False
    assert parsed['supplemental_policy']['policy_version'] == 'POL-2026.2'
    assert 'not native HTTP/API' in parsed['expense_policy']['provenance']
    assert not any(i['record_id'] == 'scenario-case-clock' for i in parsed['unresolved_issues'])
    for snapshot in sorted((run / 'batches').glob('*.json')):
        assert verify_snapshot(snapshot, run, SCHEMA) == []
        obj = json.loads(snapshot.read_text())
        assert obj['event_clock'] == CLOCK
        assert obj['supplemental_policy_binding'] == verify_policy_evidence(run, parsed)
    assert before == {str(p): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    report = (run / 'report.md').read_text()
    assert 'user-provided browser-visible copy' in report and 'Same-day cutoff' in report
    assert 'policy-pol-2026-2`=unavailable' in report


def test_readiness_accepts_supplemental_integrity_but_keeps_native_and_offline_blockers(tmp_path):
    _, run = replay(tmp_path)
    result = validate_readiness(run, schema_path=SCHEMA, repo_dir=_repo(tmp_path))
    checks = {c['check']:c for c in result['checks']}
    assert result['integrity_status'] == 'PASS', [c for c in result['checks'] if c['status']=='FAIL']
    assert checks['supplemental-policy-evidence']['status'] == 'PASS'
    assert checks['authoritative-case-clock']['status'] == 'PASS'
    assert 'calendar-date' in checks['authoritative-case-clock']['detail']
    assert checks['source-completeness:policy-pol-2026-2']['status'] == 'BLOCKED'
    assert result['status'] == 'BLOCKED' and result['final_live_source_compliance'] is False


@pytest.mark.parametrize('target', [POLICY_PATH, 'supplemental-policy.json', 'retained-input-lineage.json',
    'supplemental/original-sources.json', 'supplemental/original-parsed-records.json'])
def test_missing_or_tampered_evidence_is_integrity_failure(tmp_path, target):
    _, run = replay(tmp_path)
    path = run / target
    if target == POLICY_PATH:
        path.write_bytes(path.read_bytes() + b'\n')
    else:
        path.unlink()
    with pytest.raises((OSError, ValueError, KeyError)):
        verify_policy_evidence(run)
    assert verify_snapshot(run / 'batches/arrival-001.json', run, SCHEMA)
    result = validate_readiness(run, schema_path=SCHEMA, repo_dir=_repo(tmp_path))
    assert result['status'] == 'FAIL'


@pytest.mark.parametrize('field,value', [('event_clock', {'date':'2026-11-15','timezone':'UTC'}),
    ('supplemental_policy', {}), ('expense_policy', {})])
def test_parsed_binding_cannot_change_clock_provenance_or_policy(tmp_path, field, value):
    _, run = replay(tmp_path)
    parsed = json.loads((run / 'parsed-records.json').read_text())
    parsed[field] = value
    with pytest.raises(ValueError):
        verify_policy_evidence(run, parsed)


def test_wrong_policy_or_missing_file_creates_no_run(tmp_path):
    source = inputs(tmp_path)
    wrong = tmp_path / 'wrong.txt'
    wrong.write_bytes(POLICY.read_bytes() + b'\n')
    for policy in (wrong, tmp_path / 'absent.txt'):
        output = tmp_path / 'must-not-exist'
        assert main(['policy-replay', str(source), str(output), '--run-id', output.name, '--browser-policy', str(policy)]) == 1
        assert not output.exists()


def test_existing_runs_are_never_overwritten(tmp_path):
    source, run = replay(tmp_path)
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in run.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):
        create_policy_replay(source, run, run_id=run.name, browser_policy=POLICY, schema_path=SCHEMA)
    assert before == {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in run.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):
        create_policy_replay(source, source, run_id=source.name, browser_policy=POLICY, schema_path=SCHEMA)


@pytest.mark.parametrize('stamp,expected', [('2026-11-14T22:59:59Z', None),
    ('2026-11-14T23:00:00Z', 'same-day'), ('2026-11-15T22:59:59Z', 'same-day'),
    ('2026-11-15T23:00:00Z', 'future')])
def test_calendar_clock_preserves_amsterdam_day_and_unknown_cutoff(stamp, expected):
    error = observation_error(utc_time(stamp), CLOCK)
    assert error is None if expected is None else expected in error


def test_native_observation_cannot_be_reclassified_by_supplemental_replay(tmp_path):
    _, run = replay(tmp_path)
    path = run / 'sources.json'
    obj = json.loads(path.read_text())
    obj['files'][0]['status'] = 'read'
    path.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match='Native acquisition observations changed'):
        verify_policy_evidence(run)


def test_state_clock_tamper_never_passes_authoritative_clock_check(tmp_path):
    _, run = replay(tmp_path)
    path = run / 'offline-replay-state.json'
    obj = json.loads(path.read_text())
    obj['event_clock'] = '2026-11-15T00:00:00Z'
    path.write_text(json.dumps(obj))
    result = validate_readiness(run, schema_path=SCHEMA, repo_dir=_repo(tmp_path))
    checks = {c['check']:c['status'] for c in result['checks']}
    assert checks['supplemental-policy-evidence'] == 'FAIL'
    assert checks['authoritative-case-clock'] == 'BLOCKED'
    assert result['status'] == 'FAIL'


def test_date_only_binding_drives_existing_finance_admission_hold(tmp_path):
    from test_event_integrity import payment, finance, CONTEXT
    from copy import deepcopy
    _, run = replay(tmp_path)
    parsed = json.loads((run / 'parsed-records.json').read_text())
    context = deepcopy(CONTEXT)
    context['clock'] = parsed['event_clock']
    event = payment()
    event['values']['Activity time (UTC)']['value'] = '2026-11-15T12:00:00Z'
    result = finance([event], context=context)
    assert not result['admitted_events'] and result['net_confirmed_cents'] == 0
    assert 'same-day' in str(result['repair_issues'])


def test_representative_retained_claim_preserves_supplemental_line_references(tmp_path):
    # Native C01 schema/records in a synthetic retained-byte harness. Rebinding
    # fixture hashes here is test data, never a claim about a real acquisition.
    source = inputs(tmp_path)
    path = source / 'parsed-records.json'
    base = json.loads(path.read_text())
    native = json.loads((Path(__file__).parent / 'fixtures/ordinary_claim_c01.json').read_text())
    rows = json.loads((source / 'sources.json').read_text())['files']
    by_id = {r['source_id']:r for r in rows}
    def bind(value):
        if isinstance(value, dict):
            if value.get('source_id') in by_id and 'source_sha256' in value:
                value['source_sha256'] = by_id[value['source_id']]['sha256']
            for child in value.values(): bind(child)
        elif isinstance(value, list):
            for child in value: bind(child)
    bind(native)
    base.update(records=native['records'], workbook_sheets=native['workbook_sheets'], arrival_batches=[1,2,3,4])
    path.write_text(json.dumps(base))
    run = tmp_path / 'representative'
    create_policy_replay(source, run, run_id=run.name, browser_policy=POLICY, schema_path=SCHEMA)
    snapshot = json.loads((run / 'batches/arrival-004.json').read_text())
    assert len(snapshot['claims']) == 1
    claim = snapshot['claims'][0]
    assert claim['claim_id'] == 'C01' and claim['status'] == 'pending'
    assert POLICY_PATH in claim['lines'][0]['source_ids']
    result = validate_readiness(run, schema_path=SCHEMA, repo_dir=_repo(tmp_path))
    assert result['integrity_status'] == 'PASS', [c for c in result['checks'] if c['status']=='FAIL']
    assert next(c['status'] for c in result['checks'] if c['check']=='repair-queue-traceability') == 'PASS'
