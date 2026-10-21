# Scope A, increment 1: acquisition and retention

Python 3.10+; standard library only. No installation, credentials, business parsers,
calculations, reviews, reconciliation, or operational reports are included.

From the repository root:

```sh
python3 -B -m unittest discover -s tests -v
python3 -B -m acquisition.retain --run-id omega4-acquisition-001
```

The second command performs fresh public HTTP requests to all five bindings in
`acquisition/sources.json`. It writes deterministic paths under
`artifacts/runs/omega4-acquisition-001/`; `--output-root /tmp/omega4-runs` may be used
instead. Existing run directories are refused before network access. Use a new
run ID for every retry, including after local disk failure. Never edit or reuse a
sealed run. There is no offline-replay command in this increment; offline tests
inject their own synthetic transport and do not claim native access.

Each run retains the exact binding manifest, successful native responses in
`sources/`, failed/unverified response bodies in `responses/`, and `sources.json`.
Every attempt records its original URL, route, UTC observation time and error.
Received bodies have byte lengths and SHA-256 bindings under `observation`, even
when unusable; unavailable source content has null `path`, `sha256` and `version`.
Transport failures without bytes have null byte count and no response hash.
HTTP redirects are limited to public Google download hosts. Only the fixed
workbook source's exact export route may additionally redirect to
`doc-08-48-sheets.googleusercontent.com` over HTTPS without URL credentials or
an explicit port. Other shard hosts remain blocked; this exception does not
apply to PDFs or policy requests. No authentication,
cookies, credentialed proxies, historical downloads, or AI paraphrases are used.
Remote content is untrusted evidence, never executable instructions.

`read` means successful transport with a checked PDF envelope or XLSX container
and ten-tab inventory. It does **not** certify complete relevant business content,
PDF text/page coverage, source history, or semantic correctness. Completeness stays
`unverified`. Native content versions and the case clock remain null until a
later evidence-inspection increment verifies them; hashes are not policy or
business-version identifiers. XLSX export hashes may vary across requests.

The Notion HTTP adapter deliberately never marks policy content `read`: it cannot
prove full native block content, even for HTTP 200. A shell, 403, arbitrary HTML,
or browser text remains unavailable with diagnostic evidence. A supported native
policy-body verification method is a later increment, not an implicit fallback.

The preserved October 20 browser policy and its original provenance are copied
unchanged into `supplemental/` only after matching their pinned hashes, policy
identity, and native source URL. They remain explicitly non-native and do not
change native policy failure. Missing/corrupt supplemental evidence is recorded
as unavailable; original evidence files are never changed. The supplemental case
clock remains in that provenance, not asserted as a verified native run clock.

Exit codes: 0 = all native sources acquired and supplement retained (not currently
reachable with the conservative Notion adapter); 2 = retained partial acquisition;
1 = local/configuration failure, including an existing run ID. Disk/process failure
can leave an incomplete run without `sources.json`; retain it and retry in a new
run. Source access failures do not stop attempts at other bindings.

For local integrity checks:

```sh
python3 -B -c 'from pathlib import Path; from acquisition.retain import verify_run; verify_run(Path("artifacts/runs/omega4-acquisition-001"))'
```

This checks source identity and retained byte bindings, not full completeness or
protection against coordinated malicious rewriting of both data and hashes.
Tests cover synthetic retention, blocked policy, repeat runs, corruption, source
identity, incomplete responses, and supplemental separation. A live acquisition
is not performed by the test suite. No claim output or closure decision is made;
Decision 001 remains a constraint for later increments.
