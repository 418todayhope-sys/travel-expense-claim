"""Follow-up drafts preserve evidence without sending or changing state."""

from copy import deepcopy

from travel_claim.follow_up import render_follow_up_drafts
from travel_claim.outputs import add_repair_item, new_repair_queue


def test_owner_drafts_group_categories_preserve_trace_and_exclude_resolved_items():
    queue = new_repair_queue()
    for identity, kind, subject, revision, owner in (
        ("claim-1", "claim", "C1", 3, "Owner A"),
        ("claim-2", "claim", "C2", 1, "Owner B"),
        ("trip-1", "trip", "T1", 2, "Owner A"),
        ("permit-1", "permit", "P1", 1, "Owner A"),
        ("resolved-claim", "claim", "C-RESOLVED", 1, "Resolved Owner"),
        ("resolved-trip", "trip", "T-RESOLVED", 1, "Owner A"),
    ):
        add_repair_item(
            queue, item_id=identity, subject_type=kind, subject_id=subject,
            revision=revision, owner=owner, source_refs=[f"binder@{'a' * 64}#page {revision}"],
            missing_or_return_reason=f"retained question for {identity}",
            next_action=f"retained action for {identity}", run_id="retained-run", batch_id="arrival-002",
        )
        if identity.startswith("resolved"):
            queue["items"][identity]["status"] = "resolved"
    blockers = [
        dict(record_id="policy", subject_type="policy", subject_id="POL-2026.2",
             owner="Owner A", reason="native policy unavailable", next_action="obtain native policy",
             evidence_needed="authorized policy content"),
        dict(record_id="clock", subject_type="scenario", subject_id="clock",
             owner="Facilitator", reason="authoritative clock unconfirmed", next_action="confirm case clock",
             evidence_needed="authoritative date, time, timezone"),
        dict(record_id="resolved-blocker", subject_type="policy", subject_id="OLD",
             owner="Resolved Owner", status="resolved", reason="old issue", next_action="old action"),
    ]
    before = deepcopy((queue, blockers))
    text, count = render_follow_up_drafts(run_id="replay-run", queue=queue, blockers=blockers)
    assert (queue, blockers) == before
    assert count == 3
    assert text.count("## Draft for ") == count
    assert text.count("**DRAFT — HUMAN REVIEW REQUIRED — NOT SENT.**") == count
    assert "Offline replay of retained evidence; no fresh live-source reads" in text
    assert "Resolved Owner" not in text
    for identity in ("resolved-claim", "resolved-trip", "C-RESOLVED", "T-RESOLVED", "resolved-blocker"):
        assert identity not in text
    owner_a = text.split("## Draft for Owner A\n", 1)[1].split("## Draft for Owner B", 1)[0]
    claim_section = owner_a.split("### Claim-specific repairs", 1)[1].split("### Trip/permit repairs", 1)[0]
    trip_section = owner_a.split("### Trip/permit repairs", 1)[1].split("### External run-level blockers", 1)[0]
    assert "claim-1" in claim_section and "trip-1" not in claim_section and "policy" not in claim_section
    assert "trip-1" in trip_section and "permit-1" in trip_section and "claim-1" not in trip_section
    assert "### External run-level blockers" in owner_a
    assert "parsed-records.json#unresolved_issues/policy" in owner_a
    assert "authorized policy content" in owner_a
    for item in queue["items"].values():
        if item["status"] == "resolved":
            continue
        owner_text = text.split(f"## Draft for {item['owner']}\n", 1)[1].split("\n## Draft for ", 1)[0]
        assert f"{item['subject_type']} `{item['subject_id']}`, revision {item['revision']}" in owner_text
        assert item["missing_or_return_reason"] in owner_text
        assert item["next_action"] in owner_text
        assert f"repair-queue.json#items/{item['item_id']}" in owner_text
        assert "run `retained-run`, batch `arrival-002`" in owner_text
        assert all(ref in owner_text for ref in item["source_refs"])
    reordered = deepcopy(queue)
    reordered["items"] = dict(reversed(list(reordered["items"].items())))
    assert render_follow_up_drafts(run_id="replay-run", queue=reordered, blockers=list(reversed(blockers))) == (text, count)


def test_no_unresolved_items_means_no_messages_and_missing_evidence_is_explicit():
    queue = new_repair_queue()
    text, count = render_follow_up_drafts(run_id="empty", queue=queue, blockers=[])
    assert count == 0
    assert "No unresolved items; no draft messages generated." in text
    assert "## Draft for " not in text
    add_repair_item(
        queue, item_id="missing", subject_type="claim", subject_id="C1", revision=1,
        owner="Owner", source_refs=[], missing_or_return_reason="evidence missing",
        next_action="obtain evidence", run_id="run", batch_id="arrival-001",
    )
    text, count = render_follow_up_drafts(run_id="run", queue=queue, blockers=[])
    assert count == 1
    assert "Retained evidence references: none retained; human review required" in text
