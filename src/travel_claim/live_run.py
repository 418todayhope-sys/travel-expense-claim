"""Fresh native acquisition and transcription, separate from retained replay.

This command never consumes an old manifest or seals business decisions with
missing clock/policy authority. Acquisition and business readiness are separate.
"""
from __future__ import annotations

import json
from pathlib import Path

from .parsing import parse_retained_run
from .sources import capture_sources, sha256_bytes, verify_source_manifest


def run_live_sources(run_dir: Path, *, run_id: str, case_clock: str | None, **capture_options) -> dict:
    """Always capture all five URLs into a new directory before reading inputs."""
    manifest = capture_sources(run_dir, run_id=run_id, case_clock=case_clock, **capture_options)
    errors = verify_source_manifest(run_dir)
    parsed = None
    if not errors:
        try:
            parsed = parse_retained_run(run_dir)
        except Exception as exc:
            errors.append(f"Native transcription failed: {type(exc).__name__}: {exc}")
    checks = [{'check': 'manifest-integrity', 'status': 'FAIL' if errors else 'PASS',
               'evidence': 'sources.json', 'detail': '; '.join(errors) or 'Fresh observations and retained bytes verified',
               'next_action': 'Repair retrieval/transcription integrity in a new run' if errors else 'No integrity repair needed'}]
    for row in manifest['files']:
        checks.append({'check': f"source:{row['source_id']}", 'status': 'PASS' if row['status'] == 'read' else 'BLOCKED',
                       'evidence': row['path'] or row['observation']['response_path'] or 'sources.json',
                       'detail': row['error'] or 'Complete supported export read; retained bytes bound by SHA-256',
                       'next_action': 'Obtain authorized native content and retry in a new run' if row['status'] != 'read' else 'Retain observed source version and wording'})
    for issue in (parsed or {}).get('transcription_issues', []):
        checks.append({'check': f"transcription:{issue['source_id']}", 'status': 'BLOCKED',
                       'evidence': issue['path'], 'detail': issue['error'], 'next_action': issue['next_action']})
    checks.append({'check': 'authoritative-case-clock', 'status': 'PASS' if case_clock else 'BLOCKED',
                   'evidence': 'sources.json', 'detail': 'Caller-supplied scenario clock' if case_clock else 'No authoritative case clock supplied; retrieval timestamps are not scenario time',
                   'next_action': 'Verify supplied authority before batch consumption' if case_clock else 'Obtain explicit date, time and timezone from the exercise facilitator'})
    checks.append({'check': 'native-policy-processing', 'status': 'BLOCKED', 'evidence': 'sources.json',
                   'detail': 'Complete native policy rule interpretation and final business compliance are not established by acquisition',
                   'next_action': 'Obtain the full authoritative policy and validate rule coverage before policy-dependent processing'})
    capture_complete = all(row['status'] == 'read' for row in manifest['files'])
    status = 'FAIL' if errors else 'BLOCKED' if any(c['status'] == 'BLOCKED' for c in checks) else 'PASS'
    report = {'schema_version': 'travel-claim-live-run/1', 'run_id': run_id, 'mode': 'live-source-attempt',
              'status': status, 'fresh_reads_attempted': len(manifest['files']), 'cache_fallback_used': False,
              'acquisition_status': 'PASS' if capture_complete and not errors else 'FAIL' if errors else 'BLOCKED',
              'final_live_source_compliance': False, 'batches_consumed': [],
              'source_manifest': {'path': 'sources.json', 'sha256': sha256_bytes((run_dir / 'sources.json').read_bytes())},
              'parsed_records': {'path': 'parsed-records.json', 'sha256': sha256_bytes((run_dir / 'parsed-records.json').read_bytes())} if parsed else None,
              'arrival_batches_observed': (parsed or {}).get('arrival_batches', []), 'checks': checks}
    with (run_dir / 'live-run.json').open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    lines = ['# Project D fresh native-source attempt', '', f"**{status}** — `{run_id}`; mode: `live-source-attempt`.", '',
             'All five original source locations were attempted in this invocation using native HTTP/export routes. '
             'No previous retained input was substituted. Retrieval observations are not a case clock.', '',
             f"Acquisition: **{report['acquisition_status']}**. Final live-source compliance: **not established**. No arrival batches consumed.", '',
             'Complete relevant returned bytes, usable partial content and diagnostic responses are retained in this run and bound in `sources.json`.', '']
    for check in checks:
        lines += [f"- **{check['status']}** `{check['check']}`: {check['detail']}",
                  f"  - Evidence: `{check['evidence']}`; next action: {check['next_action']}"]
    with (run_dir / 'live-run.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')
    return report
