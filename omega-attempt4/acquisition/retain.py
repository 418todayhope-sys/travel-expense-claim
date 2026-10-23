"""Acquire fixed public bindings; retain raw evidence without interpreting business data.

Python 3.10+ standard library only. No cookies, credentials, historical fallback,
business parsing, or policy-completeness claims. Run directories are create-only.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import io
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).with_name("sources.json")
SUPPLEMENT = "user-provided-sources/20261020/POL-2026.2-20261020-browser-copy.txt"
PROVENANCE = "user-provided-sources/20261020/POL-2026.2-20261020-browser-copy.provenance.json"
POLICY_HASH = "04d8121a91986dc0839094b5e7f574c44f6261c60c1c3ba9aeeee1c279ee5993"
POLICY_PROVENANCE_HASH = "8e0d9fb0e30a6c5468e36ddc785842841eca8d6d922ecc1bd3baa90267c1359f"
TABS = ("People", "Trips", "Merchant payments", "FX", "Caps", "Budget",
        "Review ledger", "Review packets", "Finance activity", "Travel cancellations")
WORKBOOK_URL = "https://docs.google.com/spreadsheets/d/1338nvKD6rgAdLgGRhYCMMlQyDNLK0sE8pvFWrZAaaxg/edit"
WORKBOOK_EXPORT = WORKBOOK_URL.removesuffix("edit") + "export?format=xlsx"
WORKBOOK_DOWNLOAD_HOST = "doc-08-48-sheets.googleusercontent.com"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_bindings() -> tuple[bytes, list[dict]]:
    raw = MANIFEST.read_bytes()
    doc = json.loads(raw)
    bindings = doc["sources"]
    expected = ("initial-claims", "claim-updates", "receipts", "travel-registers", "policy")
    if doc["manifest_version"] != "omega4-source-bindings/1" or tuple(
        b["source_id"] for b in bindings
    ) != expected:
        raise ValueError("Unexpected fixed source manifest identity/order")
    for b in bindings:
        if Path(b["filename"]).name != b["filename"]:
            raise ValueError("Unsafe retained filename")
        original = urllib.parse.urlsplit(b["url"])
        route = urllib.parse.urlsplit(b["retrieval_route"])
        if any(u.scheme != "https" or u.username or u.password or u.port for u in (original, route)):
            raise ValueError("Only credential-free HTTPS source routes are allowed")
        if b["kind"] == "pdf":
            match = re.fullmatch(r"/file/d/([A-Za-z0-9_-]+)/view", original.path)
            if not match or original.netloc != "drive.google.com" or b["retrieval_route"] != (
                "https://drive.google.com/uc?export=download&id=" + match[1]
            ):
                raise ValueError("PDF route does not match original source identity")
        elif b["kind"] == "xlsx":
            match = re.fullmatch(r"/spreadsheets/d/([A-Za-z0-9_-]+)/edit", original.path)
            if not match or original.netloc != "docs.google.com" or b["retrieval_route"] != (
                "https://docs.google.com/spreadsheets/d/" + match[1] + "/export?format=xlsx"
            ):
                raise ValueError("Workbook route does not match original source identity")
        elif b["kind"] != "notion" or original.netloc != "private-pecorino-70e.notion.site" or b["url"] != b["retrieval_route"]:
            raise ValueError("Unexpected policy binding")
    return raw, bindings


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    final_url: str
    content_type: str | None = None
    error: str | None = None


class PublicRedirects(urllib.request.HTTPRedirectHandler):
    """Permit Google's public download redirects, never login/credential routes."""

    def __init__(self, binding: dict | None = None):
        super().__init__()
        self.workbook = bool(binding and binding.get("source_id") == "travel-registers"
                             and binding.get("kind") == "xlsx"
                             and binding.get("url") == WORKBOOK_URL
                             and binding.get("retrieval_route") == WORKBOOK_EXPORT)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urllib.parse.urlsplit(newurl)
        allowed = {"drive.google.com", "docs.google.com", "drive.usercontent.google.com"}
        if self.workbook and req.full_url == WORKBOOK_EXPORT:
            allowed.add(WORKBOOK_DOWNLOAD_HOST)
        if (url.scheme != "https" or url.username or url.password or url.port
                or url.hostname not in allowed):
            raise urllib.error.URLError("Redirect outside allowed public download hosts")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_public(binding: dict) -> Response:
    # No cookie jar, auth handler, browser session, environment proxy credentials,
    # or external credentials. Each source is freshly requested.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), PublicRedirects(binding))
    request = urllib.request.Request(binding["retrieval_route"], headers={
        "User-Agent": "Omega4-source-acquisition/1", "Cache-Control": "no-cache",
        "Accept-Encoding": "identity",
    })
    try:
        with opener.open(request, timeout=40) as response:
            try:
                body = response.read()
            except http.client.IncompleteRead as exc:
                return Response(response.status, exc.partial, response.url,
                                response.headers.get("Content-Type"), "Incomplete HTTP response")
            length = response.headers.get("Content-Length")
            error = None if length is None or int(length) == len(body) else "Content-Length mismatch"
            return Response(response.status, body, response.url,
                            response.headers.get("Content-Type"), error)
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.read(), exc.url, exc.headers.get("Content-Type"),
                        f"HTTP {exc.code}: {exc.reason}")


def inspect_envelope(binding: dict, response: Response) -> tuple[str | None, dict]:
    """Check transport/container shape, never assert complete business access."""
    structure = {}
    if response.error:
        return response.error, structure
    if response.status != 200:
        return f"HTTP {response.status}; source unavailable", structure
    body = response.body
    if binding["kind"] == "notion":
        return ("Native Notion policy body/completeness cannot be verified by this HTTP adapter; "
                "shells and browser copies are not native policy retrieval"), structure
    if binding["kind"] == "pdf":
        if not body.startswith(b"%PDF-") or not body.rstrip().endswith(b"%%EOF"):
            return "Response is not an intact PDF envelope", structure
        structure["pdf_envelope"] = True
        structure["page_text_inspection"] = "not performed by acquisition module"
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                if archive.testzip() is not None:
                    return "XLSX ZIP integrity failure", structure
                tree = ET.fromstring(archive.read("xl/workbook.xml"))
                ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                tabs = [s.attrib["name"] for s in tree.findall("s:sheets/s:sheet", ns)]
                structure["tabs"] = tabs
                if tuple(tabs) != TABS:
                    return "Workbook tab inventory differs from fixed expected scope", structure
        except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError, RuntimeError) as exc:
            return f"Invalid XLSX container: {exc}", structure
    return None, structure


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def supplemental_record(repo: Path, run: Path, policy_url: str) -> dict:
    record = {"source_id": "user-browser-policy-20261020", "native_acquisition": False,
              "status": "unavailable", "path": None, "sha256": None, "version": None,
              "provenance_path": None, "provenance_sha256": None, "error": None}
    try:
        body = (repo / SUPPLEMENT).read_bytes()
        provenance = (repo / PROVENANCE).read_bytes()
        doc = json.loads(provenance)
        if (sha256(body) != POLICY_HASH or sha256(provenance) != POLICY_PROVENANCE_HASH
                or doc["sha256"] != POLICY_HASH or doc["source_url"] != policy_url
                or doc["source_version"] != "POL-2026.2" or doc["path"] != SUPPLEMENT
                or doc["native_automated_access"] is not False
                or doc["remote_notion_completeness_independently_verified"] is not False):
            raise ValueError("Supplemental policy identity/hash/provenance mismatch")
        relative = "supplemental/" + Path(SUPPLEMENT).name
        relative_provenance = "supplemental/" + Path(PROVENANCE).name
        write_new(run / relative, body)
        write_new(run / relative_provenance, provenance)
        record.update(status="retained", path=relative, sha256=POLICY_HASH,
                      byte_count=len(body), version="POL-2026.2",
                      provenance_path=relative_provenance, provenance_sha256=sha256(provenance),
                      source_url=policy_url, limitations=doc["limitations"])
    except (OSError, ValueError, KeyError) as exc:
        record["error"] = str(exc)
    return record


def acquire(output_root: Path, run_id: str, *, repo: Path = ROOT,
            fetch=fetch_public, clock=utc_now) -> dict:
    """Create one immutable acquisition run. Existing run IDs are never reused.

    An injected transport is for offline tests; the CLI always uses fresh HTTP.
    Missing/invalid supplemental evidence never substitutes for native failure.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", run_id):
        raise ValueError("run_id must be a simple nonempty identifier (max 100 characters)")
    manifest_bytes, bindings = load_bindings()
    run = Path(output_root) / run_id
    run.mkdir(parents=True, exist_ok=False)
    write_new(run / "source-bindings.json", manifest_bytes)
    files = []
    for binding in bindings:
        entry = {"source_id": binding["source_id"], "url": binding["url"],
                 "retrieval_route": binding["retrieval_route"], "locator": binding["locator"],
                 "status": "unavailable", "error": None, "path": None, "sha256": None,
                 "version": None, "version_verified": False, "byte_count": None,
                 "completeness": "unverified", "missing_scope": [binding["locator"]]}
        try:
            response = fetch(binding)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            entry.update(error=f"{type(exc).__name__}: {exc}", observed_at=clock())
            files.append(entry)
            continue
        entry["observed_at"] = clock()
        error, structure = inspect_envelope(binding, response)
        # Retain even failed response bodies as diagnostic evidence, separate from usable source bytes.
        relative = ("responses/" + binding["source_id"] + ".body" if error
                    else "sources/" + binding["filename"])
        write_new(run / relative, response.body)
        entry.update(byte_count=len(response.body), structure=structure, error=error,
                     observation={"method": "fresh-unauthenticated-http",
                                  "http_status": response.status, "final_url": response.final_url,
                                  "content_type": response.content_type, "response_path": relative,
                                  "byte_count": len(response.body), "sha256": sha256(response.body)})
        if error is None:
            entry.update(status="read", path=relative, sha256=sha256(response.body),
                         missing_scope=[], remaining_verification=[
                             "Complete relevant business content/history and semantic source version"])
        files.append(entry)
    supplemental = supplemental_record(repo, run, bindings[-1]["url"])
    document = {"schema_version": "omega4-acquisition/1", "run_id": run_id,
                "source_version": None, "case_clock": None,
                "source_bindings": {"path": "source-bindings.json", "sha256": sha256(manifest_bytes)},
                "scope": "source acquisition only; no business parsing or completeness certification",
                "result": "partial" if any(e["status"] != "read" for e in files)
                          or supplemental["status"] != "retained" else "acquired",
                "files": files, "supplemental_evidence": [supplemental]}
    write_new(run / "sources.json", (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode())
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "runs")
    args = parser.parse_args()
    try:
        doc = acquire(args.output_root, args.run_id)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Acquisition failed: {exc}; existing/incomplete runs are never overwritten.\n")
    print(f"{doc['result']}: {args.output_root / args.run_id / 'sources.json'}")
    return 2 if doc["result"] == "partial" else 0


def verify_run(run: Path) -> None:
    """Verify retained hashes and fixed source identities, not business completeness."""
    raw, bindings = load_bindings()
    doc = json.loads((run / "sources.json").read_bytes())
    if ((run / "source-bindings.json").read_bytes() != raw
            or doc["source_bindings"] != {"path": "source-bindings.json", "sha256": sha256(raw)}
            or [e["source_id"] for e in doc["files"]] != [b["source_id"] for b in bindings]):
        raise ValueError("Retained source binding identity mismatch")
    for entry, binding in zip(doc["files"], bindings):
        if any(entry[k] != binding[k] for k in ("url", "retrieval_route", "locator")):
            raise ValueError("Source identity mismatch")
        observation = entry.get("observation")
        if observation:
            expected_path = ("sources/" + binding["filename"] if entry["status"] == "read"
                             else "responses/" + binding["source_id"] + ".body")
            if observation["response_path"] != expected_path:
                raise ValueError("Unexpected response path")
            body = (run / expected_path).read_bytes()
            if sha256(body) != observation["sha256"] or len(body) != observation["byte_count"]:
                raise ValueError("Retained response hash/length mismatch")
            if entry["status"] == "read":
                if (binding["kind"] == "notion" or entry["path"] != expected_path
                        or entry["sha256"] != sha256(body) or entry["byte_count"] != len(body)):
                    raise ValueError("Invalid native source binding")
        elif entry["status"] != "unavailable":
            raise ValueError("Read source lacks response evidence")
        if entry["status"] == "unavailable" and any(entry[k] is not None for k in ("path", "sha256", "version")):
            raise ValueError("Unavailable content must not be bound as usable source")
    for item in doc["supplemental_evidence"]:
        if item["status"] == "retained":
            expected_path = "supplemental/" + Path(SUPPLEMENT).name
            expected_provenance = "supplemental/" + Path(PROVENANCE).name
            if (item["native_acquisition"] is not False or item["path"] != expected_path
                    or item["provenance_path"] != expected_provenance
                    or item["sha256"] != POLICY_HASH or item["provenance_sha256"] != POLICY_PROVENANCE_HASH
                    or sha256((run / expected_path).read_bytes()) != POLICY_HASH
                    or sha256((run / expected_provenance).read_bytes()) != POLICY_PROVENANCE_HASH):
                raise ValueError("Supplemental evidence integrity mismatch")


if __name__ == "__main__":
    raise SystemExit(main())
