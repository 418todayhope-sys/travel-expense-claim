"""Regressions for Stage 7's reproduced partial-response defects (synthetic only)."""
import copy
import json

import pytest

from travel_claim.outputs import (add_repair_item, apply_partial_response, new_repair_queue,
                                 load_repair_queue, write_repair_queue)
from partial_response_fixtures import retained_response


def queue_fixture():
    queue = new_repair_queue()
    for key in ('A', 'B', 'unmatched'):
        add_repair_item(queue, item_id=key, subject_type='claim', subject_id='SYN-' + key,
            revision=2, source_refs=['synthetic/claim/' + key], missing_or_return_reason='receipt missing',
            owner='synthetic employee', next_action='provide matched receipt', run_id='synthetic', batch_id='b1')
    return queue


def apply(queue, outcomes, root=None, response_id='reply'):
    kwargs = {} if root is None else {'evidence_directory': root}
    apply_partial_response(queue, response_id=response_id, item_outcomes=outcomes,
                           run_id='synthetic', batch_id='b2', **kwargs)


def test_distinct_notes_are_journaled_per_item_and_exact_replay_survives_reload(tmp_path):
    queue = queue_fixture()
    outcomes = {'A': {'outcome': 'insufficient', 'note': 'A needs receipt', 'source_refs': ['reply/A']},
                'B': {'outcome': 'unanswered', 'note': 'B no answer', 'source_refs': []}}
    apply(queue, outcomes)
    assert [e['note'] for e in queue['events'] if e['event'] == 'response-recorded'] == [
        'A needs receipt', 'B no answer']
    path = tmp_path / 'queue.json'
    write_repair_queue(queue, path)
    loaded = load_repair_queue(path)
    before = copy.deepcopy(loaded)
    apply(loaded, outcomes)
    assert loaded == before


def test_unverified_nonempty_reference_cannot_resolve():
    queue = queue_fixture()
    apply(queue, {'A': {'outcome': 'supported', 'source_refs': ['not-a-retained-source']}})
    assert queue['items']['A']['status'] == 'open'
    assert queue['items']['A']['history'][-1]['admission_status'] == 'held'


def test_valid_multi_item_response_and_replay(tmp_path):
    queue = queue_fixture()
    untouched = copy.deepcopy(queue['items']['unmatched'])
    outcomes = retained_response(tmp_path, queue, 'reply', {
        'A': {'outcome': 'supported', 'note': 'A supplied'},
        'B': {'outcome': 'supported', 'note': 'B supplied'}})
    apply(queue, outcomes, tmp_path)
    assert [queue['items'][key]['status'] for key in ('A', 'B')] == ['resolved', 'resolved']
    assert queue['items']['unmatched'] == untouched
    assert [e['note'] for e in queue['events'] if e['event'] == 'response-recorded'] == ['A supplied', 'B supplied']
    before = copy.deepcopy(queue)
    apply(queue, outcomes, tmp_path)
    assert queue == before


@pytest.mark.parametrize('defect', ['tampered', 'missing', 'wrong-hash', 'wrong-locator',
    'wrong-item', 'wrong-subject', 'wrong-revision', 'insufficient', 'missing-reason', 'unobserved'])
def test_invalid_evidence_is_retained_without_resolving(tmp_path, defect):
    import hashlib
    queue = queue_fixture()
    outcomes = retained_response(tmp_path, queue, 'reply', {'A': {'outcome': 'supported'}})
    manifest = json.loads((tmp_path / 'sources.json').read_text())
    if defect == 'tampered':
        (tmp_path / 'evidence.json').write_text('{}')
    elif defect == 'missing':
        (tmp_path / 'evidence.json').unlink()
    elif defect in ('wrong-hash', 'wrong-locator'):
        ref = outcomes['A']['source_refs'][0]
        outcomes['A']['source_refs'] = [ref.replace(manifest['files'][0]['sha256'], '0'*64)
            if defect == 'wrong-hash' else ref.replace('/receipt', '/not-present')]
    elif defect == 'unobserved':
        manifest['files'][0]['status'] = 'unavailable'
        (tmp_path / 'sources.json').write_text(json.dumps(manifest))
    else:
        path = tmp_path / 'response.json'
        rows = json.loads(path.read_text())
        field, value = {'wrong-item': ('item_id', 'B'), 'wrong-subject': ('subject_id', 'SYN-B'),
            'wrong-revision': ('revision', 1), 'insufficient': ('sufficient', False),
            'missing-reason': ('reason', '')}[defect]
        rows[0][field] = value
        path.write_text(json.dumps(rows))
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest['files'][1]['sha256'] = sha
        (tmp_path / 'sources.json').write_text(json.dumps(manifest))
        outcomes['A']['assessment_ref'] = f'synthetic-response@{sha}#/0'
    apply(queue, outcomes, tmp_path)
    item = queue['items']['A']
    assert item['status'] == 'open'
    assert item['history'][-1]['source_refs'] == outcomes['A']['source_refs']
    assert item['history'][-1]['admission_status'] == 'held'


def test_prior_resolution_preserved_and_conflicting_replay_atomic(tmp_path):
    queue = queue_fixture()
    outcomes = retained_response(tmp_path, queue, 'reply', {'A': {'outcome': 'supported'}})
    apply(queue, outcomes, tmp_path)
    refs = copy.deepcopy(queue['items']['A']['resolution_source_refs'])
    apply(queue, {'A': {'outcome': 'supported', 'source_refs': ['bogus']}}, response_id='bad')
    assert queue['items']['A']['status'] == 'resolved'
    assert queue['items']['A']['resolution_source_refs'] == refs
    before = copy.deepcopy(queue)
    changed = copy.deepcopy(outcomes)
    changed['A']['note'] = 'conflicting note'
    with pytest.raises(ValueError, match='conflicting replay'):
        apply(queue, changed, tmp_path)
    assert queue == before


def test_supported_and_insufficient_items_keep_distinct_notes_and_refs(tmp_path):
    queue = queue_fixture()
    outcomes = retained_response(tmp_path, queue, 'reply', {
        'A': {'outcome': 'supported', 'note': 'A receipt provided'},
        'B': {'outcome': 'insufficient', 'note': 'B receipt still missing', 'source_refs': ['retained-unverified-reply/B']}})
    apply(queue, outcomes, tmp_path)
    assert queue['items']['A']['status'] == 'resolved'
    assert queue['items']['B']['status'] == 'open'
    assert [e['note'] for e in queue['events'] if e['event'] == 'response-recorded'] == [
        'A receipt provided', 'B receipt still missing']
    for key in ('A', 'B'):
        assert queue['items'][key]['history'][-1]['source_refs'] == outcomes[key]['source_refs']
    before = copy.deepcopy(queue)
    apply(queue, outcomes, tmp_path)
    assert queue == before


def test_historical_replay_cannot_resolve_new_revision(tmp_path):
    from travel_claim.outputs import update_repair_item, validate_partial_response_journal
    queue = queue_fixture()
    outcomes = retained_response(tmp_path, queue, 'reply', {'A': {'outcome': 'supported'}})
    apply(queue, outcomes, tmp_path)
    update_repair_item(queue, item_id='A', update_id='correction', run_id='synthetic', batch_id='b3', revision=3)
    before = copy.deepcopy(queue)
    apply(queue, outcomes, tmp_path)
    assert queue == before
    assert queue['items']['A']['status'] == 'open'
    validate_partial_response_journal(queue, tmp_path)


@pytest.mark.parametrize('tamper', ['event-note', 'resolution-refs', 'source-bytes', 'assessment', 'orphan-history'])
def test_readiness_journal_check_reverifies_admitted_resolutions(tmp_path, tamper):
    from travel_claim.outputs import validate_partial_response_journal
    queue = queue_fixture()
    outcomes = retained_response(tmp_path, queue, 'reply', {'A': {'outcome': 'supported'}})
    apply(queue, outcomes, tmp_path)
    validate_partial_response_journal(queue, tmp_path)
    if tamper == 'event-note':
        queue['events'][-1]['note'] = 'wrong item note'
    elif tamper == 'resolution-refs':
        queue['items']['A']['resolution_source_refs'] = ['unsupported']
    elif tamper == 'source-bytes':
        (tmp_path / 'evidence.json').write_text('{}')
    elif tamper == 'assessment':
        queue['items']['A']['history'][-1]['assessment_ref'] = 'unsupported'
    else:
        queue['events'].pop()
    with pytest.raises(ValueError):
        validate_partial_response_journal(queue, tmp_path)


def test_readiness_exposes_partial_response_integrity_failure(tmp_path):
    from test_readiness import _run, _repo, _checks
    from test_offline_replay import SCHEMA
    from travel_claim.readiness import validate_readiness
    run = _run(tmp_path, repairs=True)
    queue_path = run / 'repair-queue.json'
    persisted = json.loads(queue_path.read_text())
    item = next(iter(persisted['items'].values()))
    item['status'] = 'resolved'
    item['response_id'] = 'UNSUPPORTED'
    item['resolution_source_refs'] = ['not-a-retained-source']
    queue_path.write_text(json.dumps(persisted))
    state_path = run / 'offline-replay-state.json'
    state = json.loads(state_path.read_text())
    state['repair_queue']['items'][item['item_id']] = item
    state_path.write_text(json.dumps(state))
    result = validate_readiness(run, schema_path=SCHEMA, repo_dir=_repo(tmp_path))
    assert _checks(result)['partial-response-integrity'] == 'FAIL'


def test_accepted_multi_item_replay_is_unchanged_after_persistence(tmp_path):
    queue = queue_fixture()
    outcomes = retained_response(tmp_path / 'response-evidence', queue, 'reply', {
        'A': {'outcome': 'supported', 'note': 'A provided'},
        'B': {'outcome': 'supported', 'note': 'B provided'}})
    apply(queue, outcomes, tmp_path / 'response-evidence')
    path = tmp_path / 'queue.json'
    write_repair_queue(queue, path)
    loaded = load_repair_queue(path)
    before = copy.deepcopy(loaded)
    apply_partial_response(loaded, response_id='reply', item_outcomes=outcomes,
        run_id='later-run', batch_id='b4')
    assert loaded == before


def test_invalid_item_does_not_prevent_valid_independent_resolution(tmp_path):
    queue = queue_fixture()
    outcomes = retained_response(tmp_path, queue, 'reply', {
        'A': {'outcome': 'supported'}, 'B': {'outcome': 'supported'}})
    outcomes['A']['source_refs'] = ['unmatched']
    apply(queue, outcomes, tmp_path)
    assert queue['items']['A']['status'] == 'open'
    assert queue['items']['B']['status'] == 'resolved'
    before = copy.deepcopy(queue)
    apply(queue, outcomes, tmp_path)
    assert queue == before
