"""Replay the preserved regression runner with only its repository locator replaced."""
from pathlib import Path
import argparse
import hashlib
import json

HERE = Path(__file__).resolve().parent
ORIGINAL_SHA256 = '1cf08b72a1ab8d4d8e027405b37319f1a8870e190c7fd2a41fd015e98f51bd45'
ORIGINAL_ROOT_LINE = "ROOT=Path('/home/maxg/travel-expense-claim-omega4')"


def configured_source(repository):
    raw = (HERE / 'original-runner.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != ORIGINAL_SHA256:
        raise ValueError('Original regression runner hash mismatch')
    source = raw.decode('utf-8')
    if source.count(ORIGINAL_ROOT_LINE) != 1:
        raise ValueError('Expected exactly one original repository locator')
    configured = source.replace(ORIGINAL_ROOT_LINE, 'ROOT=Path(' + repr(str(repository)) + ')', 1)
    return compile(configured, str(HERE / 'original-runner.py'), 'exec')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=HERE.parents[2])
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    repository = args.repository.resolve()
    for name in ('validation/validate.py', 'tests/test_ordinary_closure_safeguards.py', '.git'):
        if not (repository / name).exists():
            raise ValueError('Missing replay checkout component: ' + name)
    code = configured_source(repository)
    if args.check_only:
        print(json.dumps({'configuration': 'valid', 'original_runner_hash': 'verified',
                          'repository': str(repository), 'tests_executed': False}))
        return
    exec(code, {'__name__': '__main__', '__file__': str(HERE / 'original-runner.py')})


if __name__ == '__main__':
    main()
