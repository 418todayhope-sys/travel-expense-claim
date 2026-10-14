import json

from travel_claim.cli import main


def _valid_snapshot():
    return {
        "schema_version": "travel-claim-snapshot/2",
        "run_id": "run-1",
        "batch_id": "batch-1",
        "predecessor": None,
        "source_binding": {"path": "sources.json", "sha256": "a" * 64},
        "claims": [],
        "requests": [],
        "travel_cancellations": [],
        "admitted_event_ids": [],
        "issues": [],
    }


def test_valid_snapshot_passes(tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(_valid_snapshot()), encoding="utf-8")

    result = main(["validate-snapshot", str(snapshot)])

    assert result == 0
    assert "Snapshot is valid" in capsys.readouterr().out


def test_invalid_snapshot_fails(tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")

    result = main(["validate-snapshot", str(snapshot)])

    captured = capsys.readouterr()
    assert result == 1
    assert "Snapshot validation failed" in captured.err


def test_missing_snapshot_file_fails(tmp_path, capsys):
    missing_snapshot = tmp_path / "missing.json"

    result = main(["validate-snapshot", str(missing_snapshot)])

    assert result == 1
    assert "Snapshot file not found" in capsys.readouterr().err
