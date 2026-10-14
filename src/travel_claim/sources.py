"""Fresh native-source retrieval and byte-bound source manifests.

This module deliberately has no cache/fallback path. Every capture invokes the
configured native URL or its documented export route again.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping


@dataclass(frozen=True)
class NativeSource:
    source_id: str
    title: str
    url: str
    locator: str
    export_url: str | None = None
    kind: str = "binary"


SOURCES: tuple[NativeSource, ...] = (
    NativeSource(
        "policy-pol-2026-2",
        "Travel reimbursement policy POL-2026.2",
        "https://private-pecorino-70e.notion.site/Project-D-Alderbridge-travel-reimbursement-policy-POL-2026-1-3d80b700541e81ed93ebd386abc1dcb0",
        "Notion policy page body",
        kind="notion",
    ),
    NativeSource(
        "initial-claim-binder",
        "Initial claim binder",
        "https://drive.google.com/file/d/13sRj6s_kMeP1hsYGstWWmfkb6SCN1YOS/view",
        "Complete PDF document",
        "https://drive.google.com/uc?export=download&id=13sRj6s_kMeP1hsYGstWWmfkb6SCN1YOS",
        "pdf",
    ),
    NativeSource(
        "claim-updates-binder",
        "Claim updates binder",
        "https://drive.google.com/file/d/16829RwrGrMCK9oq5TnWuytFewGk_8xQP/view",
        "Complete PDF document",
        "https://drive.google.com/uc?export=download&id=16829RwrGrMCK9oq5TnWuytFewGk_8xQP",
        "pdf",
    ),
    NativeSource(
        "receipt-binder",
        "Receipt binder",
        "https://drive.google.com/file/d/1Ynn1VLH-faRIy91xy95rOWwCBhy5mjjM/view",
        "Complete PDF document",
        "https://drive.google.com/uc?export=download&id=1Ynn1VLH-faRIy91xy95rOWwCBhy5mjjM",
        "pdf",
    ),
    NativeSource(
        "travel-registers-workbook",
        "Travel registers workbook",
        "https://docs.google.com/spreadsheets/d/1338nvKD6rgAdLgGRhYCMMlQyDNLK0sE8pvFWrZAaaxg/edit",
        "All workbook tabs via native XLSX export",
        "https://docs.google.com/spreadsheets/d/1338nvKD6rgAdLgGRhYCMMlQyDNLK0sE8pvFWrZAaaxg/export?format=xlsx",
        "xlsx",
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _policy_page_is_relevant_html(content: bytes) -> bool:
    text = content.decode("utf-8", "replace")
    # A successful response can still be only a generic Notion app/login shell.
    has_policy_id = bool(re.search(r"POL[- ]2026(?:\.2|[- ]2)", text, re.I))
    has_policy_body = bool(re.search(r"lodging|meal cap|permit approval|reimbursement", text, re.I))
    return has_policy_id and has_policy_body


def _validate_payload(source: NativeSource, content: bytes) -> tuple[bool, str | None, str | None]:
    """Return (usable, filename suffix, failure reason), without parsing case answers."""
    if source.kind == "notion":
        if not content or not _policy_page_is_relevant_html(content):
            return False, None, "HTTP response contained a generic Notion shell; policy page content was not accessible"
        return True, "html", None
    if source.kind == "pdf":
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
            return False, None, "Export did not contain a complete PDF signature and trailer"
        return True, "pdf", None
    if source.kind == "xlsx":
        try:
            import io

            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if archive.testzip() is not None or "xl/workbook.xml" not in archive.namelist():
                    return False, None, "XLSX archive is corrupt or has no workbook index"
        except (OSError, zipfile.BadZipFile):
            return False, None, "Export was not a readable XLSX workbook"
        return True, "xlsx", None
    return (bool(content), "bin" if content else None, None if content else "Empty response body")


def _request(url: str, timeout: float) -> tuple[bytes, Mapping[str, str], str]:
    req = urllib.request.Request(url, headers={"User-Agent": "travel-claim-source-capture/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(), dict(response.headers.items()), response.geturl()


def capture_sources(
    run_dir: Path,
    *,
    run_id: str,
    case_clock: str | None,
    source_specs: tuple[NativeSource, ...] = SOURCES,
    fetch: Callable[[str, float], tuple[bytes, Mapping[str, str], str]] = _request,
    observed_at: Callable[[], str] = _utc_now,
    timeout: float = 30.0,
) -> dict:
    """Freshly attempt every source and write exact returned bytes plus sources.json.

    `case_clock` is caller supplied scenario time. It may be null for a
    source-acquisition-only run where no supplied batch clock has been read.
    """
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run_id must be a single safe path component")
    if run_dir.name != run_id:
        raise ValueError("run_dir basename must equal run_id")
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "sources.json"
    if manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite source manifest: {manifest_path}")
    source_dir = run_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    if any(source_dir.iterdir()):
        raise FileExistsError(f"Refusing to reuse nonempty retained-source directory: {source_dir}")
    entries: list[dict] = []
    for source in source_specs:
        timestamp = observed_at()
        url_attempted = source.export_url or source.url
        try:
            body, headers, _final_url = fetch(url_attempted, timeout)
            usable, suffix, validation_error = _validate_payload(source, body)
            timestamp = observed_at()
            version = headers.get("ETag") or headers.get("Last-Modified")
            if usable:
                rel_path = Path("sources") / f"{source.source_id}.{suffix}"
                content_path = run_dir / rel_path
                with content_path.open("xb") as retained:
                    retained.write(body)
                entries.append({
                    "source_id": source.source_id,
                    "path": rel_path.as_posix(),
                    "sha256": sha256_bytes(body),
                    "status": "read",
                    "error": None,
                    "url": source.url,
                    "locator": source.locator,
                    "observed_at": timestamp,
                    "version": version,
                    "scope": source.title,
                    "missing_scope": [],
                })
            else:
                entries.append({
                    "source_id": source.source_id,
                    "path": None,
                    "sha256": None,
                    "status": "unavailable",
                    "error": validation_error,
                    "url": source.url,
                    "locator": source.locator,
                    "observed_at": timestamp,
                    "version": None,
                    "scope": source.title,
                    "missing_scope": [source.title],
                })
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            timestamp = observed_at()
            entries.append({
                "source_id": source.source_id,
                "path": None,
                "sha256": None,
                "status": "unavailable",
                "error": f"{type(exc).__name__}: {exc}",
                "url": source.url,
                "locator": source.locator,
                "observed_at": timestamp,
                "version": None,
                "scope": source.title,
                "missing_scope": [source.title],
            })
    manifest = {
        "run_id": run_id,
        "source_version": "native-source-manifest/1",
        "case_clock": case_clock,
        "files": entries,
    }
    with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def verify_source_manifest(run_dir: Path) -> list[str]:
    """Check source manifest shape, five source attempts, and retained-byte hashes."""
    errors: list[str] = []
    path = run_dir / "sources.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Cannot read sources.json: {exc}"]
    if not isinstance(manifest, dict):
        return ["sources.json must contain an object"]
    if set(manifest) != {"run_id", "source_version", "case_clock", "files"}:
        errors.append("sources.json must contain exactly run_id, source_version, case_clock, and files")
    if manifest.get("run_id") != run_dir.name:
        errors.append("sources.json run_id must match its run directory")
    if not isinstance(manifest.get("files"), list):
        return errors + ["sources.json files must be an array"]
    seen: set[str] = set()
    for record in manifest["files"]:
        if not isinstance(record, dict):
            errors.append("every files[] entry must be an object")
            continue
        sid = record.get("source_id")
        if not isinstance(sid, str) or not sid or sid in seen:
            errors.append(f"source_id is empty or duplicated: {sid!r}")
        else:
            seen.add(sid)
        required = {
            "source_id", "path", "sha256", "status", "error", "url", "locator",
            "observed_at", "version", "scope", "missing_scope",
        }
        if not required.issubset(record):
            errors.append(f"{sid}: missing required metadata fields {sorted(required - set(record))}")
            continue
        if not isinstance(record.get("url"), str) or not record["url"] or not isinstance(record.get("locator"), str) or not record["locator"]:
            errors.append(f"{sid}: url and locator must be nonempty strings")
        if not isinstance(record.get("scope"), str) or not record["scope"]:
            errors.append(f"{sid}: scope must identify the observed source portion")
        if not isinstance(record.get("missing_scope"), list) or not all(isinstance(x, str) and x for x in record["missing_scope"]):
            errors.append(f"{sid}: missing_scope must be an array of nonempty strings")
        try:
            observed = datetime.fromisoformat(str(record["observed_at"]).replace("Z", "+00:00"))
            if observed.utcoffset() is None or observed.utcoffset().total_seconds() != 0:
                errors.append(f"{sid}: observed_at must be UTC")
        except (TypeError, ValueError):
            errors.append(f"{sid}: observed_at must be an ISO UTC timestamp")
        if record["error"] is not None and not isinstance(record["error"], str):
            errors.append(f"{sid}: error must be a string or null")
        if record["status"] == "read":
            if not isinstance(record["path"], str) or not record["path"] or not isinstance(record["sha256"], str) or not record["sha256"]:
                errors.append(f"{sid}: read record has no retained path or hash")
                continue
            content_path = run_dir / record["path"]
            if not content_path.resolve().is_relative_to(run_dir.resolve()):
                errors.append(f"{sid}: retained path escapes the run directory")
                continue
            try:
                actual = sha256_bytes(content_path.read_bytes())
            except OSError as exc:
                errors.append(f"{sid}: cannot read retained content: {exc}")
            else:
                if actual != record["sha256"]:
                    errors.append(f"{sid}: retained content hash mismatch")
        elif record["status"] == "unavailable":
            if any(record[k] is not None for k in ("path", "sha256", "version")):
                errors.append(f"{sid}: unavailable scope must have null path, sha256, and version")
            if not record["error"]:
                errors.append(f"{sid}: unavailable scope has no error")
        else:
            errors.append(f"{sid}: invalid status {record['status']!r}")
    expected_urls = {source.url for source in SOURCES}
    observed_urls = {
        record.get("url")
        for record in manifest["files"]
        if isinstance(record, dict) and isinstance(record.get("url"), str)
    }
    if observed_urls != expected_urls:
        errors.append("manifest must cover exactly all five configured native source URLs")
    return errors
