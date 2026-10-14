"""Render unsent owner follow-ups using only retained unresolved evidence."""

from __future__ import annotations

from typing import Any


def render_follow_up_drafts(
    *, run_id: str, queue: dict[str, Any], blockers: list[dict[str, Any]],
) -> tuple[str, int]:
    """Return one human-review draft per owner, without mutating queue history."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for item in queue["items"].values():
        if item["status"] != "open":
            continue
        category = "Claim-specific repairs" if item["subject_type"] == "claim" else "Trip/permit repairs"
        grouped.setdefault(item["owner"], {}).setdefault(category, []).append(item)
    for blocker in blockers:
        # Parser unresolved_issues has no status field; explicitly resolved
        # entries, if supplied, must never produce a follow-up.
        if blocker.get("status", "open") != "open":
            continue
        grouped.setdefault(blocker["owner"], {}).setdefault("External run-level blockers", []).append(blocker)

    lines = [
        "# Project D follow-up drafts — OFFLINE REPLAY", "",
        "**DRAFTS — HUMAN REVIEW REQUIRED — NOT SENT.**", "",
        "Offline replay of retained evidence; no fresh live-source reads were performed. "
        "These drafts do not establish policy eligibility, entitlement, approvals, payment confirmations, or a case-clock date.",
        "",
        f"Run: `{run_id}`. Draft messages: **{len(grouped)}** (one per responsible owner).", "",
        "Independent valid records continue processing while unresolved items await evidence. "
        "Review each draft against current source evidence before any human sends it.", "",
    ]
    categories = ("Claim-specific repairs", "Trip/permit repairs", "External run-level blockers")
    for owner, sections in sorted(grouped.items()):
        lines.extend([
            f"## Draft for {owner}", "",
            "**DRAFT — HUMAN REVIEW REQUIRED — NOT SENT.**", "",
            f"Responsible owner: {owner}", "",
            "Please address the following unresolved items and provide evidence tied to the listed references. "
            "If an item cannot be answered, identify what remains unresolved in your response.", "",
        ])
        for category in categories:
            if category not in sections:
                continue
            lines.extend([f"### {category}", ""])
            is_blocker = category == "External run-level blockers"
            for row in sorted(sections[category], key=lambda row: row["record_id"] if is_blocker else row["item_id"]):
                identity = row["record_id"] if is_blocker else row["item_id"]
                subject = f"{row['subject_type']} `{row['subject_id']}`"
                if not is_blocker:
                    subject += f", revision {row['revision']}"
                lines.extend([
                    f"- Item `{identity}` — {subject}.",
                    f"  - Unresolved question / retained reason: {row['reason'] if is_blocker else row['missing_or_return_reason']}",
                    f"  - Requested next action: {row['next_action']}",
                ])
                if is_blocker:
                    lines.extend([
                        f"  - Evidence needed: {row.get('evidence_needed') or 'not specified in retained issue; human review required'}",
                        f"  - Retained issue reference: `parsed-records.json#unresolved_issues/{identity}` in run `{run_id}`.",
                    ])
                else:
                    lines.append(f"  - Queue reference: `repair-queue.json#items/{identity}`; opened in run `{row['run_id']}`, batch `{row['batch_id']}`.")
                    refs = "; ".join(f"`{ref}`" for ref in row["source_refs"])
                    lines.append(f"  - Retained evidence references: {refs or 'none retained; human review required'}")
            lines.append("")
    if not grouped:
        lines.extend(["No unresolved items; no draft messages generated.", ""])
    return "\n".join(lines), len(grouped)
