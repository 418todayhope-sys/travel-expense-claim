"""Schema-checked, content-addressed batch snapshots."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .sources import sha256_bytes, verify_source_manifest


def _schema_errors(snapshot: dict, schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{'.'.join(map(str, err.absolute_path)) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(snapshot), key=lambda e: list(map(str, e.absolute_path)))
    ]


def _check_semantics(snapshot: dict) -> list[str]:
    errors: list[str] = []
    issue_ids = [issue["record_id"] for issue in snapshot["issues"]]
    if len(issue_ids) != len(set(issue_ids)):
        errors.append("issues[].record_id values must be unique")
    issue_set = set(issue_ids)
    for cancellation in snapshot["travel_cancellations"]:
        missing = set(cancellation["issue_record_ids"]) - issue_set
        if missing:
            errors.append(f"cancellation {cancellation['cancellation_id']} refers to missing issue records: {sorted(missing)}")
    claim_ids = {claim["claim_id"] for claim in snapshot["claims"]}
    for request in snapshot["requests"]:
        if request["claim_id"] not in claim_ids:
            errors.append(f"request {request['request_id']} refers to missing claim {request['claim_id']}")
    cancellation_event_ids = {
        event_id
        for cancellation in snapshot["travel_cancellations"]
        for event_id in cancellation["admitted_cancellation_event_ids"]
    }
    overlap = cancellation_event_ids & set(snapshot["admitted_event_ids"])
    if overlap:
        errors.append(f"Finance admitted_event_ids must not contain cancellation activity IDs: {sorted(overlap)}")
    return errors


def verify_snapshot(snapshot_path: Path, run_dir: Path, schema_path: Path) -> list[str]:
    """Verify this snapshot and every sealed snapshot in its predecessor chain."""
    return _verify_snapshot(snapshot_path, run_dir, schema_path, set())


def _verify_snapshot(
    snapshot_path: Path,
    run_dir: Path,
    schema_path: Path,
    seen_paths: set[Path],
) -> list[str]:
    """Validate schema plus source/predecessor hashes and required references."""
    resolved_snapshot = snapshot_path.resolve()
    if resolved_snapshot in seen_paths:
        return [f"predecessor cycle detected at {snapshot_path}"]
    seen_paths.add(resolved_snapshot)
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Cannot read snapshot: {exc}"]
    errors = _schema_errors(snapshot, schema_path)
    if errors:
        return errors
    errors.extend(_check_semantics(snapshot))
    errors.extend(verify_source_manifest(run_dir))
    try:
        manifest = json.loads((run_dir / "sources.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("sources.json must be an object")
        if manifest.get("run_id") != snapshot["run_id"]:
            errors.append("snapshot run_id does not match sources.json run_id")
        files = manifest.get("files", [])
        retained_ids = {
            record.get("source_id")
            for record in files if isinstance(record, dict)
            if record.get("status") == "read"
        }
        for claim in snapshot["claims"]:
            for line in claim["lines"]:
                missing_sources = set(line["source_ids"]) - retained_ids
                if missing_sources:
                    errors.append(
                        f"claim {claim['claim_id']} cost {line['cost_id']} refers to unavailable source IDs: {sorted(missing_sources)}"
                    )
    except (OSError, json.JSONDecodeError, ValueError):
        manifest = {}
    source_binding = snapshot["source_binding"]
    source_path = run_dir / source_binding["path"]
    if not source_path.resolve().is_relative_to(run_dir.resolve()):
        errors.append("source_binding path escapes the run directory")
        return errors
    if source_path.resolve() != (run_dir / "sources.json").resolve():
        errors.append("source_binding must identify this run's sources.json")
        return errors
    try:
        actual = sha256_bytes(source_path.read_bytes())
    except OSError as exc:
        errors.append(f"Cannot read bound sources file {source_binding['path']}: {exc}")
    else:
        if actual != source_binding["sha256"]:
            errors.append("source_binding SHA-256 does not match retained sources.json")
    predecessor = snapshot["predecessor"]
    if predecessor is not None:
        previous_path = run_dir / predecessor["path"]
        if not previous_path.resolve().is_relative_to((run_dir / "batches").resolve()):
            errors.append("predecessor path escapes the run's batches directory")
            return errors
        try:
            actual = sha256_bytes(previous_path.read_bytes())
        except OSError as exc:
            errors.append(f"Cannot read predecessor {predecessor['path']}: {exc}")
        else:
            if actual != predecessor["sha256"]:
                errors.append("predecessor SHA-256 does not match retained snapshot")
            else:
                errors.extend(
                    f"predecessor chain: {error}"
                    for error in _verify_snapshot(previous_path, run_dir, schema_path, seen_paths)
                )
    return errors


def seal_batch_snapshot(
    run_dir: Path,
    *,
    run_id: str,
    batch_id: str,
    claims: list[dict],
    requests: list[dict],
    travel_cancellations: list[dict],
    admitted_event_ids: list[str],
    issues: list[dict],
    schema_path: Path,
    predecessor_path: Path | None = None,
    allow_unconfirmed_case_clock: bool = False,
) -> Path:
    """Seal one batch. Binding paths are relative to the run directory.

    Existing snapshots are never overwritten. The first snapshot uses a null
    predecessor; later snapshots hash the exact prior serialized bytes.
    """
    batches_dir = run_dir / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)
    if not batch_id or Path(batch_id).name != batch_id or batch_id in {".", ".."}:
        raise ValueError("batch_id must be a single safe path component")
    target = batches_dir / f"{batch_id}.json"
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite sealed snapshot: {target}")
    source_path = run_dir / "sources.json"
    if not source_path.is_file():
        raise FileNotFoundError(f"Required source manifest missing: {source_path}")
    source_errors = verify_source_manifest(run_dir)
    if source_errors:
        raise ValueError("Source manifest is not integrity-valid: " + "; ".join(source_errors))
    manifest = json.loads(source_path.read_text(encoding="utf-8"))
    if manifest.get("run_id") != run_id:
        raise ValueError("Snapshot run_id must match sources.json run_id")
    if not manifest.get("case_clock") and not allow_unconfirmed_case_clock:
        raise ValueError("Cannot consume a batch without the supplied scenario case_clock")
    existing_snapshots = list(batches_dir.glob("*.json"))
    if existing_snapshots and predecessor_path is None:
        raise ValueError("A later batch must bind its predecessor snapshot")
    source_rel = Path("sources.json")
    predecessor = None
    if predecessor_path is not None:
        predecessor_path = predecessor_path.resolve()
        if not predecessor_path.is_file():
            raise FileNotFoundError(f"Predecessor snapshot missing: {predecessor_path}")
        if predecessor_path.parent.resolve() != batches_dir.resolve():
            raise ValueError("Predecessor must be a retained snapshot in this run's batches directory")
        # Verify its source binding and full schema before chaining from it.
        predecessor_errors = verify_snapshot(predecessor_path, run_dir, schema_path)
        if predecessor_errors:
            raise ValueError("Predecessor snapshot is invalid: " + "; ".join(predecessor_errors))
        prior_state = json.loads(predecessor_path.read_text(encoding="utf-8"))
        if prior_state["run_id"] != run_id:
            raise ValueError("Predecessor snapshot belongs to a different run")
        chain_paths: set[Path] = set()
        cursor = predecessor_path.resolve()
        while cursor not in chain_paths:
            chain_paths.add(cursor)
            cursor_state = json.loads(cursor.read_text(encoding="utf-8"))
            previous = cursor_state["predecessor"]
            if previous is None:
                break
            cursor = (run_dir / previous["path"]).resolve()
        existing_paths = {path.resolve() for path in existing_snapshots}
        if chain_paths != existing_paths:
            raise ValueError("Predecessor must be the end of the complete retained snapshot chain; orphaned or missing prior state found")
        predecessor = {
            "path": (Path("batches") / predecessor_path.name).as_posix(),
            "sha256": sha256_bytes(predecessor_path.read_bytes()),
        }
    snapshot = {
        "schema_version": "travel-claim-snapshot/2",
        "run_id": run_id,
        "batch_id": batch_id,
        "predecessor": predecessor,
        "source_binding": {
            "path": source_rel.as_posix(),
            "sha256": sha256_bytes(source_path.read_bytes()),
        },
        "claims": copy.deepcopy(claims),
        "requests": copy.deepcopy(requests),
        "travel_cancellations": copy.deepcopy(travel_cancellations),
        "admitted_event_ids": list(admitted_event_ids),
        "issues": copy.deepcopy(issues),
    }
    errors = _schema_errors(snapshot, schema_path) + _check_semantics(snapshot)
    if errors:
        raise ValueError("Refusing to seal invalid snapshot: " + "; ".join(errors))
    serialized = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    # Exclusive create prevents a concurrent run from replacing prior bytes.
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(serialized)
    errors = verify_snapshot(target, run_dir, schema_path)
    if errors:
        # Do not remove or rewrite a possibly observed sealed file. Surface the
        # integrity failure for operator investigation.
        raise ValueError("New snapshot failed post-seal integrity checks: " + "; ".join(errors))
    return target
