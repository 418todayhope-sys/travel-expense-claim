"""Command-line interface for travel claim tooling."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .outputs import write_claims_csv
from .live_run import run_live_sources
from .offline_replay import run_offline_replay
from .readiness import readiness_summary, validate_readiness, write_readiness_reports
from .parsing import parse_retained_run
from .snapshots import seal_batch_snapshot, verify_snapshot
from .sources import capture_sources, verify_source_manifest


def _default_schema_path() -> Path:
    """Return the repository's authoritative snapshot schema path."""
    return Path(__file__).resolve().parents[2] / "snapshot.schema.json"


def validate_snapshot(snapshot_path: Path, schema_path: Path) -> list[str]:
    """Return validation errors for a snapshot and schema, or an empty list."""
    try:
        with snapshot_path.open(encoding="utf-8") as snapshot_file:
            snapshot = json.load(snapshot_file)
    except FileNotFoundError:
        return [f"Snapshot file not found: {snapshot_path}"]
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Could not read snapshot {snapshot_path}: {exc}"]

    try:
        with schema_path.open(encoding="utf-8") as schema_file:
            schema = json.load(schema_file)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Could not read schema {schema_path}: {exc}"]

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(snapshot), key=lambda error: list(map(str, error.absolute_path)))
    return [
        f"{'.'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in errors
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="travel-claim")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser(
        "validate-snapshot", help="validate a JSON snapshot against snapshot.schema.json"
    )
    validate.add_argument("snapshot", type=Path, help="path to the snapshot JSON file")
    validate.add_argument(
        "--schema", type=Path, default=_default_schema_path(), help="schema JSON path"
    )

    capture = commands.add_parser("capture-sources", help="freshly retrieve and retain all five native sources")
    capture.add_argument("run_id", help="new, stable run identifier")
    capture.add_argument("run_dir", type=Path, help="new artifacts/runs/<run-id> directory")
    capture.add_argument("--case-clock", help="supplied scenario clock; omit only for source-only capture")

    live = commands.add_parser("live-run", help="freshly attempt all five sources, retain and transcribe; report blockers without offline fallback")
    live.add_argument("run_id")
    live.add_argument("run_dir", type=Path)
    live.add_argument("--case-clock", help="explicit authoritative scenario clock; never inferred from retrieval time")
    live.add_argument("--timeout", type=float, default=30.0, help="per-request timeout seconds")

    verify_sources = commands.add_parser("verify-sources", help="verify source manifest and retained-byte hashes")
    verify_sources.add_argument("run_dir", type=Path)

    parse_sources = commands.add_parser("parse-retained", help="transcribe hash-verified PDFs and workbook into traceable records")
    parse_sources.add_argument("run_dir", type=Path)
    parse_sources.add_argument("--output", type=Path, help="optional new output path; defaults to parsed-records.json in the run")

    seal = commands.add_parser("seal-batch", help="schema-check and immutably seal one batch state JSON")
    seal.add_argument("run_dir", type=Path)
    seal.add_argument("batch_id")
    seal.add_argument("state", type=Path, help="JSON object containing claims, requests, cancellations, events, issues")
    seal.add_argument("--run-id", required=True)
    seal.add_argument("--predecessor", type=Path)
    seal.add_argument("--schema", type=Path, default=_default_schema_path())

    verify_batch = commands.add_parser("verify-batch", help="verify schema and source/predecessor bindings")
    verify_batch.add_argument("run_dir", type=Path)
    verify_batch.add_argument("snapshot", type=Path)
    verify_batch.add_argument("--schema", type=Path, default=_default_schema_path())

    csv_cmd = commands.add_parser("write-claims-csv", help="write the exact current-claim CSV contract")
    csv_cmd.add_argument("claims_json", type=Path, help="JSON array of current claim summary objects")
    csv_cmd.add_argument("output", type=Path)

    replay = commands.add_parser(
        "offline-replay",
        help="replay verified retained records in arrival order without fresh native-source reads",
    )
    replay.add_argument("run_dir", type=Path, help="existing retained-source run directory")
    replay.add_argument("--schema", type=Path, default=_default_schema_path(), help="snapshot schema path")
    policy_replay = commands.add_parser('policy-replay', help='new offline retained-input run with separately verified browser policy evidence')
    policy_replay.add_argument('source_run', type=Path)
    policy_replay.add_argument('run_dir', type=Path)
    policy_replay.add_argument('--run-id', required=True)
    policy_replay.add_argument('--browser-policy', type=Path, required=True)
    policy_replay.add_argument('--schema', type=Path, default=_default_schema_path())
    receipt = commands.add_parser('continue-receipt', help='derive a new offline result from one verified missing-receipt response; never append to sealed arrivals')
    receipt.add_argument('parent_run', type=Path)
    receipt.add_argument('response', type=Path)
    receipt.add_argument('output', type=Path)
    receipt.add_argument('--evidence-dir', type=Path, required=True)
    receipt.add_argument('--run-id', required=True)
    receipt.add_argument('--schema', type=Path, default=_default_schema_path())
    readiness = commands.add_parser("validate-readiness", help="check local submission evidence; PASS/BLOCKED/FAIL, never live compliance")
    readiness.add_argument("run_dir", type=Path)
    readiness.add_argument("--schema", type=Path, default=_default_schema_path())
    readiness.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    readiness.add_argument("--output-dir", type=Path, required=True, help="new directory for readiness.json and readiness.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == 'continue-receipt':
        from .receipt_continuation import continue_receipt
        try:
            result = continue_receipt(args.parent_run, args.response, args.evidence_dir, args.output,
                run_id=args.run_id, schema_path=args.schema)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            print(f'Receipt continuation rejected: {exc}', file=sys.stderr)
            return 1
        print(f"OFFLINE RECEIPT CONTINUATION {result['run_id']}: {'unchanged replay' if result['replayed'] else 'derived result verified'}; {result['output']}; no new approvals or financial closure")
        return 0
    if args.command == 'policy-replay':
        from .policy_evidence import create_policy_replay
        try:
            result = create_policy_replay(args.source_run, args.run_dir, run_id=args.run_id,
                browser_policy=args.browser_policy, schema_path=args.schema)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f'Policy replay failed: {exc}', file=sys.stderr)
            return 1
        print(f"OFFLINE REPLAY {result['run_id']}: supplemental user-provided browser policy; calendar date 2026-11-15 Europe/Amsterdam; no time inferred; native observations unchanged; final live compliance not established")
        return 0
    if args.command == "validate-readiness":
        try:
            run_root = args.run_dir.resolve()
            output_root = args.output_dir.resolve()
            if output_root == run_root or output_root.is_relative_to(run_root):
                raise ValueError("Readiness outputs must be outside the retained run directory")
            report = validate_readiness(args.run_dir, schema_path=args.schema, repo_dir=args.repo)
            write_readiness_reports(report, args.output_dir)
        except (OSError, ValueError) as exc:
            print(f"Could not validate readiness: {exc}", file=sys.stderr)
            return 1
        print(readiness_summary(report))
        print(f"Readiness reports: {args.output_dir}")
        return {"PASS": 0, "BLOCKED": 2, "FAIL": 1}[report["status"]]
    if args.command == "validate-snapshot":
        errors = validate_snapshot(args.snapshot, args.schema)
        if errors:
            print("Snapshot validation failed:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print(f"Snapshot is valid: {args.snapshot}")
        return 0
    if args.command == "live-run":
        try:
            report = run_live_sources(args.run_dir, run_id=args.run_id, case_clock=args.case_clock, timeout=args.timeout)
        except (OSError, ValueError) as exc:
            print(f"Live-source attempt failed: {exc}", file=sys.stderr)
            return 1
        print(f"LIVE SOURCE ATTEMPT {report['status']}: {args.run_id}; acquisition {report['acquisition_status']}; no cached fallback; final compliance not established")
        print(f"Report: {args.run_dir / 'live-run.md'}")
        return {"PASS": 0, "BLOCKED": 2, "FAIL": 1}[report['status']]
    if args.command == "capture-sources":
        try:
            manifest = capture_sources(args.run_dir, run_id=args.run_id, case_clock=args.case_clock)
        except Exception as exc:
            print(f"Source capture failed: {exc}", file=sys.stderr)
            return 1
        counts = {state: sum(row["status"] == state for row in manifest["files"]) for state in ("read", "partial", "unavailable")}
        print(f"Source capture {'PASS' if counts['read'] == 5 else 'BLOCKED'}: {args.run_id} ({counts['read']} read, {counts['partial']} partial, {counts['unavailable']} unavailable)")
        return 0 if counts["read"] == 5 else 2
    if args.command == "verify-sources":
        errors = verify_source_manifest(args.run_dir)
        if errors:
            print("Source verification failed:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print(f"Source manifest and retained bytes are valid: {args.run_dir}")
        return 0
    if args.command == "parse-retained":
        try:
            parsed = parse_retained_run(args.run_dir, output_path=args.output)
        except (OSError, ValueError, FileExistsError) as exc:
            print(f"Could not parse retained sources: {exc}", file=sys.stderr)
            return 1
        print(
            f"Parsed {len(parsed['records']['claim_revisions'])} claim revisions, "
            f"{len(parsed['records']['trips'])} trips, {len(parsed['records']['permits'])} permits, "
            f"{len(parsed['records']['receipts'])} receipt records, "
            f"{len(parsed['records']['decisions'])} decisions, "
            f"{len(parsed['records']['finance_events'])} Finance events, and "
            f"{len(parsed['records']['cancellation_activities'])} cancellation activities; "
            f"arrival batches {parsed['arrival_batches']}; case clock {parsed['case_clock_state']}"
        )
        return 0 if not parsed["missing_sources"] and not parsed.get("transcription_issues") and parsed["case_clock"] else 2
    if args.command == "seal-batch":
        try:
            state = json.loads(args.state.read_text(encoding="utf-8"))
            snapshot_path = seal_batch_snapshot(
                args.run_dir,
                run_id=args.run_id,
                batch_id=args.batch_id,
                claims=state["claims"],
                requests=state["requests"],
                travel_cancellations=state["travel_cancellations"],
                admitted_event_ids=state["admitted_event_ids"],
                issues=state["issues"],
                schema_path=args.schema,
                predecessor_path=args.predecessor,
            )
        except (OSError, KeyError, json.JSONDecodeError, ValueError) as exc:
            print(f"Could not seal batch: {exc}", file=sys.stderr)
            return 1
        print(f"Sealed batch snapshot: {snapshot_path}")
        return 0
    if args.command == "verify-batch":
        errors = verify_snapshot(args.snapshot, args.run_dir, args.schema)
        if errors:
            print("Batch verification failed:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print(f"Batch snapshot and bindings are valid: {args.snapshot}")
        return 0
    if args.command == "write-claims-csv":
        try:
            claims = json.loads(args.claims_json.read_text(encoding="utf-8"))
            if not isinstance(claims, list):
                raise ValueError("claims JSON must be an array")
            write_claims_csv(claims, args.output)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"Could not write claims CSV: {exc}", file=sys.stderr)
            return 1
        print(f"Wrote claims CSV: {args.output}")
        return 0
    if args.command == "offline-replay":
        try:
            result = run_offline_replay(args.run_dir, schema_path=args.schema)
        except (OSError, KeyError, json.JSONDecodeError, ValueError, FileExistsError) as exc:
            print(f"Offline replay failed: {exc}", file=sys.stderr)
            return 1
        print(f"OFFLINE REPLAY complete: {result['run_id']} (no fresh native-source reads)")
        for snapshot in result["snapshots"]:
            print(f"Snapshot: {snapshot}")
        for label, output in result["outputs"].items():
            print(f"{label}: {output}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
