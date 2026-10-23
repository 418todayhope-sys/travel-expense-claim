"""Relocated preservation verification without access to the original checkout."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
PACKAGE = Path('artifacts/verifications/omega4-attempt002-business-disposition-portability-v1')


class PreservationPortabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='omega4-relocated-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.cwd = Path(cls.temp.name)
        cls.checkout = cls.cwd / 'different checkout' / 'repository'
        shutil.copytree(ROOT, cls.checkout,
                        ignore=shutil.ignore_patterns('.git', '.entire', '.codex', '__pycache__'))

    def run_verifier(self):
        # Path reads may only use the relocated repository. An accidental
        # original-checkout or shared /tmp baseline fallback must fail, even
        # when those files happen to exist on the test machine.
        runner = '''
from pathlib import Path
import runpy
import sys
root = Path(sys.argv[1]).resolve()
original_open = Path.open
def guarded_open(path, *args, **kwargs):
    if not path.resolve().is_relative_to(root):
        raise PermissionError("Read outside relocated checkout: " + str(path))
    return original_open(path, *args, **kwargs)
Path.open = guarded_open
runpy.run_path(sys.argv[2], run_name="__main__")
'''
        return subprocess.run(
            [sys.executable, '-I', '-B', '-c', runner, str(self.checkout),
             str(self.checkout / PACKAGE / 'verify-preservation.py')],
            cwd=self.cwd, capture_output=True, text=True, timeout=90)

    def test_relocated_checkout_uses_only_packaged_evidence(self):
        result = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report['checks'], report['verified_snapshot_chains'],
                          report['verified_snapshots']), ('passed', 3, 12))
        self.assertEqual((report['final_financial_holds'], report['actual_financial_closures']), (121, 0))
        self.assertEqual(report['final_repair_states'],
                         {'open': 582, 'cleared_by_recheck': 218, 'superseded': 45})

    def test_missing_packaged_baseline_has_no_external_fallback(self):
        baseline = self.checkout / PACKAGE / 'preservation-baseline.json'
        saved = baseline.read_bytes()
        baseline.unlink()
        try:
            result = self.run_verifier()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('preservation-baseline.json', result.stderr)
        finally:
            baseline.write_bytes(saved)

    def test_changed_packaged_baseline_is_rejected(self):
        baseline = self.checkout / PACKAGE / 'preservation-baseline.json'
        saved = baseline.read_bytes()
        baseline.write_text('{}')
        try:
            result = self.run_verifier()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('differs from the original sealed baseline', result.stderr)
        finally:
            baseline.write_bytes(saved)
