"""Offline repository-relative inventory and pre-change preservation check."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ALLOWED = {'validation/validate.py', 'reconciliation/reconcile.py'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check():
    baseline = json.loads((HERE / 'preservation-baseline.json').read_text())
    changed = []
    for name, expected in baseline.items():
        path = ROOT / name
        if not path.is_file():
            raise ValueError('Missing pre-existing file: ' + name)
        if digest(path) != expected:
            changed.append(name)
            if name not in ALLOWED or digest(HERE / 'prior-inputs' / name) != expected:
                raise ValueError('Unexpected change or missing original bytes: ' + name)
    if set(changed) != ALLOWED:
        raise ValueError('Authorized changed-file inventory differs')
    manifest = json.loads((HERE / 'manifest.json').read_text())
    for item in manifest['files']:
        path = (ROOT / item['path']).resolve()
        if not path.is_relative_to(ROOT) or digest(path) != item['sha256']:
            raise ValueError('Inventory hash mismatch: ' + item['path'])
    print(json.dumps({'preserved_existing_files': len(baseline) - len(changed),
                      'archived_prior_inputs': len(changed),
                      'verified_bindings': len(manifest['files'])}, sort_keys=True))


if __name__ == '__main__':
    check()
