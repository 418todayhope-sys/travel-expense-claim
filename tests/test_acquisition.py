"""Offline transport fixtures test retention, not validity of fictional business data."""

import io
from email.message import Message
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import urllib.response
import zipfile

from acquisition import retain as a


def workbook(tabs=a.TABS):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets>'
                         + ''.join(f'<sheet name="{name}"/>' for name in tabs) + '</sheets></workbook>')
    return stream.getvalue()


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = []

    def transport(self, binding):
        self.calls.append(binding["source_id"])
        body = (workbook() if binding["kind"] == "xlsx" else b"<html>Notion app shell</html>"
                if binding["kind"] == "notion" else b"%PDF-1.4\nfixture\n%%EOF\n")
        return a.Response(200, body, binding["retrieval_route"])

    def acquire(self, run_id="run-1", **kwargs):
        return a.acquire(self.root, run_id, fetch=kwargs.pop("fetch", self.transport),
                         clock=lambda: "2026-10-20T15:00:00Z", **kwargs)

    def test_successful_native_bytes_and_scope(self):
        doc = self.acquire()
        self.assertEqual(len(self.calls), 5)
        for entry in doc["files"][:4]:
            body = (self.root / "run-1" / entry["path"]).read_bytes()
            self.assertEqual(a.sha256(body), entry["sha256"])
            self.assertEqual(len(body), entry["byte_count"])
            self.assertEqual(entry["status"], "read")
            self.assertEqual(entry["observed_at"], "2026-10-20T15:00:00Z")
            self.assertIsNone(entry["version"])
            self.assertFalse(entry["version_verified"])
            self.assertEqual(entry["completeness"], "unverified")
        a.verify_run(self.root / "run-1")

    def test_policy_shell_not_success_and_supplement_separate(self):
        doc = self.acquire()
        policy = doc["files"][-1]
        self.assertEqual(policy["status"], "unavailable")
        self.assertIsNone(policy["path"])
        self.assertIsNone(policy["sha256"])
        self.assertIn("completeness", policy["error"])
        body = (self.root / "run-1" / policy["observation"]["response_path"]).read_bytes()
        self.assertEqual(a.sha256(body), policy["observation"]["sha256"])
        supplemental = doc["supplemental_evidence"][0]
        self.assertFalse(supplemental["native_acquisition"])
        self.assertEqual(supplemental["sha256"], a.POLICY_HASH)
        self.assertEqual((self.root / "run-1" / supplemental["path"]).read_bytes(),
                         (a.ROOT / a.SUPPLEMENT).read_bytes())
        self.assertEqual((self.root / "run-1" / supplemental["provenance_path"]).read_bytes(),
                         (a.ROOT / a.PROVENANCE).read_bytes())
        self.assertEqual(doc["result"], "partial")

    def test_http_403_and_browser_text_never_native_policy(self):
        for status, body in [(403, b"Forbidden"), (200, (a.ROOT / a.SUPPLEMENT).read_bytes())]:
            def transport(binding):
                return (a.Response(status, body, binding["retrieval_route"])
                        if binding["kind"] == "notion" else self.transport(binding))
            doc = self.acquire("http-" + str(status), fetch=transport)
            self.assertEqual(doc["files"][-1]["status"], "unavailable")
            a.verify_run(self.root / ("http-" + str(status)))

    def test_network_failure_still_attempts_other_sources(self):
        def transport(binding):
            if binding["source_id"] == "initial-claims":
                raise OSError("offline")
            return self.transport(binding)
        doc = self.acquire(fetch=transport)
        self.assertIn("offline", doc["files"][0]["error"])
        self.assertIsNone(doc["files"][0]["byte_count"])
        self.assertEqual(doc["files"][1]["status"], "read")
        a.verify_run(self.root / "run-1")

    def test_repeat_runs_fetch_fresh_and_refuse_overwrite(self):
        self.acquire()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaises(FileExistsError):
            self.acquire()
        self.assertEqual(len(self.calls), 5)
        self.acquire("run-2")
        self.assertEqual(len(self.calls), 10)
        for path, body in before.items():
            self.assertEqual((self.root / path).read_bytes(), body)

    def test_integrity_detects_changed_source_bytes(self):
        doc = self.acquire()
        (self.root / "run-1" / doc["files"][0]["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "hash/length"):
            a.verify_run(self.root / "run-1")

    def test_integrity_detects_reassigned_source_identity(self):
        self.acquire()
        path = self.root / "run-1/sources.json"
        doc = json.loads(path.read_text())
        doc["files"][0]["url"] = doc["files"][1]["url"]
        path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError, "identity"):
            a.verify_run(path.parent)

    def test_manifest_routes_match_interview_identities(self):
        _, bindings = a.load_bindings()
        interview = next((a.ROOT / 'interviews').glob('*20261020*.md')).read_text()
        for binding in bindings:
            self.assertIn(binding["url"], interview)
        raw = json.loads(a.MANIFEST.read_text())
        raw["sources"][0]["retrieval_route"] = raw["sources"][1]["retrieval_route"]
        bad = self.root / "bindings.json"
        bad.write_text(json.dumps(raw))
        with patch.object(a, "MANIFEST", bad), self.assertRaisesRegex(ValueError, "identity"):
            a.load_bindings()

    def test_bad_or_partial_payload_not_read(self):
        for run_id, body, error in [('html', b'<html>login</html>', None),
                                     ('partial', b'%PDF-1.4\n%%EOF', 'Incomplete HTTP response')]:
            def transport(binding):
                return (a.Response(200, body, binding["retrieval_route"], error=error)
                        if binding["kind"] == "pdf" else self.transport(binding))
            doc = self.acquire(run_id, fetch=transport)
            self.assertTrue(all(x["status"] == "unavailable" for x in doc["files"][:3]))

    def test_missing_workbook_tabs_visible(self):
        def transport(binding):
            return (a.Response(200, workbook(a.TABS[:-1]), binding["retrieval_route"])
                    if binding["kind"] == "xlsx" else self.transport(binding))
        doc = self.acquire(fetch=transport)
        self.assertIn("tab inventory", doc["files"][3]["error"])

    def test_missing_or_corrupt_supplement_never_falls_back(self):
        for run_id, corrupt in [('missing', False), ('corrupt', True)]:
            repo = self.root / run_id
            if corrupt:
                (repo / a.SUPPLEMENT).parent.mkdir(parents=True)
                (repo / a.SUPPLEMENT).write_bytes(b'changed')
                (repo / a.PROVENANCE).write_bytes((a.ROOT / a.PROVENANCE).read_bytes())
            doc = self.acquire('run-' + run_id, repo=repo)
            self.assertEqual(doc["supplemental_evidence"][0]["status"], "unavailable")
            self.assertEqual(doc["files"][-1]["status"], "unavailable")

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            self.acquire('../escape')
        self.assertEqual(self.calls, [])

    def test_http_transport_retains_error_body(self):
        _, bindings = a.load_bindings()
        error = urllib.error.HTTPError(bindings[-1]["url"], 403, "Forbidden", {}, io.BytesIO(b"denied"))
        with patch.object(a.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect = error
            response = a.fetch_public(bindings[-1])
            self.assertEqual(response.status, 403)
            self.assertEqual(response.body, b'denied')
            self.assertIn('HTTP 403', response.error)
            request = build.return_value.open.call_args.args[0]
            self.assertNotIn('Authorization', request.headers)
            self.assertNotIn('Cookie', request.headers)

    def test_login_and_credential_redirects_blocked(self):
        handler = a.PublicRedirects()
        request = urllib.request.Request('https://drive.google.com/uc')
        for url in ['https://accounts.google.com/login', 'http://drive.google.com/uc',
                    'https://user:secret@drive.google.com/uc', 'https://example.org/file']:
            with self.assertRaises(urllib.error.URLError):
                handler.redirect_request(request, None, 302, '', {}, url)

    def test_supplemental_provenance_corruption_detected(self):
        doc = self.acquire()
        path = self.root / 'run-1' / doc['supplemental_evidence'][0]['provenance_path']
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Supplemental'):
            a.verify_run(self.root / 'run-1')

    def test_workbook_307_redirect_to_xlsx_retained(self):
        _, bindings = a.load_bindings()
        binding = bindings[3]
        payload = workbook()
        target = 'https://' + a.WORKBOOK_DOWNLOAD_HOST + '/export/fixture?token=synthetic'
        visited = []

        class OfflineHTTPS(urllib.request.HTTPSHandler):
            def https_open(self, req):
                visited.append(req.full_url)
                headers = Message()
                if req.full_url == a.WORKBOOK_EXPORT:
                    headers['Location'] = target
                    response = urllib.response.addinfourl(io.BytesIO(b''), headers, req.full_url, 307)
                else:
                    if req.full_url != target:
                        raise AssertionError('Unexpected offline request')
                    headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    headers['Content-Length'] = str(len(payload))
                    response = urllib.response.addinfourl(io.BytesIO(payload), headers, req.full_url, 200)
                response.msg = 'offline fixture'
                return response

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                             a.PublicRedirects(binding), OfflineHTTPS())
        def transport(source):
            if source['source_id'] != 'travel-registers':
                return self.transport(source)
            with patch.object(a.urllib.request, 'build_opener', return_value=opener):
                return a.fetch_public(source)
        doc = self.acquire(fetch=transport)
        self.assertEqual(visited, [a.WORKBOOK_EXPORT, target])
        entry = doc['files'][3]
        self.assertEqual(entry['status'], 'read')
        self.assertEqual(entry['sha256'], a.sha256(payload))
        self.assertEqual((self.root / 'run-1' / entry['path']).read_bytes(), payload)
        a.verify_run(self.root / 'run-1')

    def test_workbook_exception_rejects_unsafe_or_unscoped_redirects(self):
        _, bindings = a.load_bindings()
        handler = a.PublicRedirects(bindings[3])
        req = urllib.request.Request(a.WORKBOOK_EXPORT)
        host = a.WORKBOOK_DOWNLOAD_HOST
        for target in [f'http://{host}/export', f'https://user:secret@{host}/export',
                       f'https://{host}:8443/export', f'https://{host}:443/export',
                       f'https://{host}.example.org/export',
                       'https://doc-99-99-sheets.googleusercontent.com/export',
                       'https://accounts.google.com/login', 'https://example.org/export']:
            with self.subTest(target=target), self.assertRaises(urllib.error.URLError):
                handler.redirect_request(req, None, 307, '', {}, target)
        target = f'https://{host}/export'
        for binding in [None, bindings[0], bindings[4],
                        dict(bindings[3], retrieval_route=a.WORKBOOK_EXPORT + '&other=1'),
                        dict(bindings[3], url=a.WORKBOOK_URL + '?other=1')]:
            with self.assertRaises(urllib.error.URLError):
                a.PublicRedirects(binding).redirect_request(req, None, 307, '', {}, target)
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(urllib.request.Request('https://docs.google.com/other'),
                                     None, 307, '', {}, target)


if __name__ == '__main__':
    unittest.main()
