#!/usr/bin/env python3
"""Restore and hash-verify the published Stage 7 evidence using only Python stdlib.

Never overwrite existing evidence. Native source statuses and provenance remain
exactly as captured. Gzip is transport encoding, not a replacement source.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'artifacts/submission/stage7-evidence-manifest.json'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def confined(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f'evidence path escapes checkout: {value}')
    return path


def restore():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    # Validate every delivered object and any existing destination before writing.
    for row in manifest['files']:
        stored, destination = confined(row['stored_path']), confined(row['path'])
        if digest(stored) != row['stored_sha256'] or stored.stat().st_size != row['stored_bytes']:
            raise ValueError(f'published object differs from manifest: {row["stored_path"]}')
        if destination.exists() and digest(destination) != row['sha256']:
            raise ValueError(f'existing evidence differs; refusing overwrite: {row["path"]}')
    restored = 0
    for row in manifest['files']:
        destination = confined(row['path'])
        if not destination.exists():
            if row['encoding'] != 'gzip':
                raise ValueError(f'missing original evidence: {row["path"]}')
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
                    temporary = Path(output.name)
                    with gzip.open(confined(row['stored_path']), 'rb') as source:
                        while block := source.read(1024 * 1024):
                            output.write(block)
                if digest(temporary) != row['sha256'] or temporary.stat().st_size != row['bytes']:
                    raise ValueError(f'restored bytes differ: {row["path"]}')
                # Atomic no-clobber install, including concurrent invocations.
                os.link(temporary, destination)
                restored += 1
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        if destination.stat().st_size != row['bytes'] or digest(destination) != row['sha256']:
            raise ValueError(f'evidence differs from manifest: {row["path"]}')
    print(f'PASS: {len(manifest["files"])} exact evidence files verified; {restored} restored; none overwritten.')


if __name__ == '__main__':
    restore()
