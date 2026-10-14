"""Run a labelled, integrity-checked replay over previously retained records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .follow_up import render_follow_up_drafts
from .integration import integrate_arrival_batch
from .outputs import owner_grouped_view, write_claims_csv, write_repair_queue
from .parsing import OUTPUT_NAME
from .snapshots import seal_batch_snapshot, verify_snapshot
from .sources import verify_source_manifest


OFFLINE_MARKER = {
    "record_id": "offline-replay-mode",
    "reason": "Offline replay of previously retained source content; this run did not attempt fresh native-source reads.",
    "owner": "Travel Administration Lead",
    "resolution_needed": "Perform a new authorized run with fresh reads of all five native sources before relying on current source state.",
}


def _exclusive_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def _report(
    *, run_id: str, parsed: dict[str, Any], snapshots: list[Path], latest: dict[str, Any],
    output_paths: dict[str, Path],
) -> str:
    manifest_hash = hashlib.sha256((snapshots[0].parents[1] / "sources.json").read_bytes()).hexdigest()
    lines = [
        "# Project D operations handoff — OFFLINE REPLAY",
        "",
        "> This is a structural replay from previously retained inputs. It did not perform fresh native-source reads and does not establish policy eligibility, reimbursement entitlement, approval readiness, or closure.",
        "",
        f"- Run ID: `{run_id}`",
        "- Mode: `offline-replay`",
        "- Fresh native reads in this run: **no**",
        f"- Retained `sources.json` SHA-256: `{manifest_hash}`",
        f"- Case clock: **unresolved** ({parsed.get('case_clock_issue', {}).get('owner', 'Exercise facilitator')}; {parsed.get('case_clock_issue', {}).get('next_action', 'obtain authoritative case clock')})",
        "- Reimbursement policy POL-2026.2: **unavailable**; eligibility, entitlement, caps, readiness, and final closure remain unresolved.",
        f"- Parsed input: `{OUTPUT_NAME}` SHA-256 `{hashlib.sha256((snapshots[0].parents[1] / OUTPUT_NAME).read_bytes()).hexdigest()}`; parsed source content remains in that file.",
        "- Retained source observations: " + "; ".join(
            f"`{row['source_id']}`={row['status']}" for row in json.loads(
                (snapshots[0].parents[1] / "sources.json").read_text(encoding="utf-8")
            )["files"]
        ) + ".",
        "",
        "## Batch projections",
        "",
    ]
    for path in snapshots:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        lines.append(
            f"- `{path.relative_to(path.parents[1])}` — {len(snapshot['claims'])} current claim rows, "
            f"{len(snapshot['travel_cancellations'])} independent cancellation processes, "
            f"{len(snapshot['issues'])} issues; schema and source/predecessor hashes verified."
        )
    lines.extend([
        "",
        "Each snapshot retains the observed claim revision and matching decision IDs. Decisions are not treated as proof of policy compliance. Finance event identities and supported confirmed cash are retained; no obligation or entitlement is inferred. Claim monetary entitlement and balance remain null when unsupported.",
        "",
        "Independent valid records continue through the replay while unresolved claims remain pending. External blockers prevent authoritative live-run conclusions, not retention of independent evidence or partial progress.",
        "",
    ])
    queue = latest["domain"]["repair_queue"]
    for title, subject_types in (
        ("Claim-specific actionable repairs by owner", {"claim"}),
        ("Trip and permit actionable repairs by owner", {"trip", "permit"}),
    ):
        open_queue = {"items": {
            key: item for key, item in queue["items"].items()
            if item["status"] == "open" and item["subject_type"] in subject_types
        }}
        lines.extend([
            f"## {title}", "",
            f"{len(open_queue['items'])} open items. Full item-level queue and history: `{output_paths['queue'].name}`. Local request drafts are unsent.",
            "",
        ])
        if not open_queue["items"]:
            lines.extend(["No open repair items in this category; this does not establish policy readiness or closure.", ""])
        for owner, items in owner_grouped_view(open_queue).items():
            lines.extend([f"### {owner}", ""])
            for item in items:
                lines.extend([
                    f"- Repair `{item['item_id']}` — subject {item['subject_type']} `{item['subject_id']}`, revision {item['revision']} (**open**).",
                    f"  - Reason: {item['missing_or_return_reason']}.",
                    f"  - Next action: {item['next_action']}.",
                    f"  - Opened in run `{item['run_id']}`, batch `{item['batch_id']}`.",
                    "  - Retained source references: " + "; ".join(
                        f"`{ref}`" for ref in item['source_refs']
                    ) if item['source_refs'] else "  - Retained source references: unavailable; obtain authoritative evidence.",
                ])
            lines.append("")
    lines.extend([
        "## Run-level external blockers", "",
        "These retained policy and clock issues apply to the run as a whole and are separate from claim repairs. They remain unresolved in this offline replay; no case-clock date or policy rule is inferred.",
        "",
    ])
    for blocker in parsed.get("unresolved_issues", []):
        lines.append(
            f"- `{blocker['record_id']}` ({blocker.get('subject_type')} `{blocker.get('subject_id')}`): "
            f"{blocker['reason']} Owner: {blocker['owner']}. Next: {blocker['next_action']} "
            f"Evidence needed: {blocker.get('evidence_needed', 'see source issue')}"
        )
    lines.extend([
        "",
        "## Outputs",
        "",
        f"- Current claims: `{output_paths['claims'].name}` (exact required CSV columns).",
        f"- Full integration state and source-linked histories: `{output_paths['state'].name}`.",
        f"- Repair queue: `{output_paths['queue'].name}` (grouped by owner, item identity retained).",
        f"- Owner follow-up drafts: `{output_paths['drafts'].name}` (human review required; not sent).",
        "",
        "For an authoritative live-source run, resume only after obtaining the authoritative case clock and an accessible native reimbursement policy, then perform fresh reads of all five source locations. This replay does not modify source content or send requests.",
        "",
    ])
    return "\n".join(lines)


def run_offline_replay(run_dir: Path, *, schema_path: Path) -> dict[str, Any]:
    """Consume retained parsed records in batch order and write immutable outputs."""
    errors = verify_source_manifest(run_dir)
    if errors:
        raise ValueError("Retained source manifest verification failed: " + "; ".join(errors))
    manifest_path = run_dir / "sources.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parsed_path = run_dir / OUTPUT_NAME
    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    actual_manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if parsed.get("run_id") != manifest.get("run_id"):
        raise ValueError("Parsed records run_id does not match the retained source manifest")
    if parsed.get("source_manifest") != {"path": "sources.json", "sha256": actual_manifest_hash}:
        raise ValueError("Parsed records are not bound to the current retained sources.json bytes")
    batches = parsed.get("arrival_batches")
    if not isinstance(batches, list) or not batches or batches != list(range(1, len(batches) + 1)):
        raise ValueError("Retained arrival batches must be a nonempty contiguous explicit sequence starting at 1")
    output_paths = {
        "claims": run_dir / "claims.csv",
        "report": run_dir / "report.md",
        "queue": run_dir / "repair-queue.json",
        "state": run_dir / "offline-replay-state.json",
        "drafts": run_dir / "follow-up-drafts.md",
    }
    occupied = [str(path) for path in output_paths.values() if path.exists()]
    if occupied:
        raise FileExistsError("Refusing to overwrite offline replay outputs: " + ", ".join(occupied))
    batches_dir = run_dir / "batches"
    if batches_dir.exists() and any(batches_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite or append to existing sealed batch chain: {batches_dir}")

    binding = {"path": "sources.json", "sha256": actual_manifest_hash}
    previous: dict[str, Any] | None = None
    previous_path: Path | None = None
    sealed: list[Path] = []
    for number in batches:
        batch_id = f"arrival-{number:03d}"
        predecessor = None
        if previous_path is not None:
            predecessor = {
                "path": f"batches/{previous_path.name}",
                "sha256": hashlib.sha256(previous_path.read_bytes()).hexdigest(),
            }
        current = integrate_arrival_batch(
            parsed, arrival_batch=number, run_id=manifest["run_id"], batch_id=batch_id,
            source_binding=binding, predecessor=predecessor, prior_result=previous,
        )
        current["snapshot"]["issues"].append(dict(OFFLINE_MARKER))
        path = seal_batch_snapshot(
            run_dir, run_id=manifest["run_id"], batch_id=batch_id,
            predecessor_path=previous_path, schema_path=schema_path,
            allow_unconfirmed_case_clock=True, **{
                key: current["snapshot"][key]
                for key in ("claims", "requests", "travel_cancellations", "admitted_event_ids", "issues")
            },
        )
        validation = verify_snapshot(path, run_dir, schema_path)
        if validation:
            raise ValueError(f"Snapshot verification failed for {path}: " + "; ".join(validation))
        sealed.append(path)
        previous, previous_path = current, path

    latest = previous
    assert latest is not None
    current_claims = []
    owner_by_claim: dict[str, str] = {}
    reason_by_claim: dict[str, str] = {}
    for item in latest["domain"]["repair_queue"]["items"].values():
        if item["subject_type"] == "claim" and item["status"] == "open":
            owner_by_claim.setdefault(item["subject_id"], item["owner"])
            reason_by_claim.setdefault(item["subject_id"], item["missing_or_return_reason"])
    for claim in latest["snapshot"]["claims"]:
        claim_id = claim["claim_id"]
        current_claims.append({
            "claim_id": claim_id,
            "revision": claim["revision"],
            "trip_id": claim["trip_id"],
            "status": "pending",
            "allowed_cents": None,
            "paid_cents": claim["paid_cents"],
            "balance_cents": claim["balance_cents"],
            "next_owner": owner_by_claim.get(claim_id, claim["next_owner"]),
            "reason": reason_by_claim.get(
                claim_id,
                "Offline structural replay; policy eligibility and reimbursement entitlement remain unresolved.",
            ),
        })
    write_claims_csv(current_claims, output_paths["claims"])
    queue = latest["domain"]["repair_queue"]
    write_repair_queue(queue, output_paths["queue"])
    _exclusive_json(output_paths["state"], {
        "mode": "offline-replay",
        "fresh_native_reads_performed": False,
        "run_id": manifest["run_id"],
        "case_clock": manifest.get("case_clock"),
        "source_manifest_sha256": actual_manifest_hash,
        "parsed_records_path": OUTPUT_NAME,
        "parsed_records_sha256": hashlib.sha256(parsed_path.read_bytes()).hexdigest(),
        "parsed_record_counts": {name: len(rows) for name, rows in parsed.get("records", {}).items()},
        "sealed_batches": [path.relative_to(run_dir).as_posix() for path in sealed],
        "revision_history": latest["revision_history"],
        "decision_history": latest["decision_history"],
        "finance_reconciliations": latest["finance_reconciliations"],
        "cancellation_state": latest["domain"]["cancellation_state"],
        "material_corrections": latest["domain"]["material_corrections"],
        "source_record_history": {
            "claim_revisions": latest["domain"]["claim_records"],
            "decisions": latest["domain"]["decision_records"],
            "finance_events": latest["domain"]["finance_records"],
            "cancellation_activities": latest["domain"]["cancellation_records"],
        },
        "repair_queue": queue,
    })
    drafts, draft_count = render_follow_up_drafts(
        run_id=manifest["run_id"], queue=queue, blockers=parsed.get("unresolved_issues", []),
    )
    with output_paths["drafts"].open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(drafts)
    report = _report(
        run_id=manifest["run_id"], parsed=parsed, snapshots=sealed, latest=latest,
        output_paths=output_paths,
    )
    output_paths["report"].write_text(report, encoding="utf-8", newline="\n")
    return {"run_id": manifest["run_id"], "snapshots": sealed, "outputs": output_paths, "state": latest, "draft_count": draft_count}
