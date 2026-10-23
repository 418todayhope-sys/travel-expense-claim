# Portable business-disposition preservation verification

The original `../omega4-attempt002-business-disposition-v1/verify-preservation.py`
is sealed by that directory's `manifest.json` and remains unchanged. This
separately versioned verifier preserves its comparison checks while locating the
repository from its own file location and reading its adjacent packaged baseline.
The baseline is an exact copy of the original sealed baseline; its hash is
checked against the original manifest before comparisons run.

From the repository root, using Python 3.10+ and only the standard library:

```sh
python3 -B artifacts/verifications/omega4-attempt002-business-disposition-portability-v1/verify-preservation.py
python3 -B -m unittest discover -s tests -p test_preservation_portability.py -v
```

The verifier does not depend on the invocation working directory. Keep its
repository-relative package location and retain the original manifest, baseline
and artifact history. It neither accesses the network nor writes evidence.
Run without `-O`: inherited comparison checks use Python assertions.

The focused test copies the repository into a differently named temporary
location, runs an isolated Python process from outside that repository, and
rejects Path-based reads outside the relocated tree. Missing or modified local
baselines must fail; they cannot fall back to another checkout or a shared
temporary baseline. Only temporary test copies are modified.

This is preservation/comparison verification, not the full workflow's semantic
verifier, an independent source-completeness check or external operator
acceptance. It preserves all financial holds and unresolved items. The full
workflow still needs its documented third-party packages and time-zone data;
transitive dependencies remain unlocked. Historical semantic replay still needs
matching historical code and documentation. No existing sealed output, decision,
interview or source file was rewritten.
