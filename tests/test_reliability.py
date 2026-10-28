import contextlib
import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scan_intake import scan_intake
from local_pipeline import local_triage
if 'objc' not in sys.modules:
    try:
        __import__('objc')
    except ImportError:
        sys.modules['objc'] = types.SimpleNamespace(
            loadBundle=lambda *args, **kwargs: None,
            lookUpClass=lambda name: type(name, (), {}))
from tools import vision_ocr


class ScriptReliabilityTests(unittest.TestCase):
    def test_negative_amounts_keep_the_sign(self):
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance -$50.00'), '-50.00')
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance -50.00'), '-50.00')
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance -1,234.56'), '-1,234.56')
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance $50.00'), '50.00')

    def test_scan_intake_ocr_returns_failure_if_any_input_fails(self):
        results = [types.SimpleNamespace(returncode=0), types.SimpleNamespace(returncode=2)]
        with mock.patch.object(scan_intake.subprocess, 'run', side_effect=results):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(scan_intake.ocr(['good.pdf', 'bad.pdf']), 1)

    def test_duplicate_name_and_size_mismatch_is_not_reported_as_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive, folder, out = root / 'drive', root / 'folder', root / 'out'
            (drive / 'one').mkdir(parents=True)
            (drive / 'two').mkdir()
            (folder / 'copy').mkdir(parents=True)
            (drive / 'one' / 'report.txt').write_bytes(b'same')
            (drive / 'two' / 'report.txt').write_bytes(b'diff')
            (folder / 'copy' / 'report.txt').write_bytes(b'same')
            (drive / 'one' / 'odd\nname.txt').write_bytes(b'short')
            (folder / 'copy' / 'odd\nname.txt').write_bytes(b'short')
            result = subprocess.run(
                [sys.executable, str(ROOT / 'local_pipeline/drive_folder_diff.py'),
                 '--drive', str(drive), '--folder', str(folder), '--out', str(out), '--hash'],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('report.txt', (out / 'same.tsv').read_text())
            differ = (out / 'differ.tsv').read_text()
            self.assertIn('report.txt', differ)
            self.assertIn('one/report.txt | two/report.txt', differ)
            self.assertIn('copy/report.txt', differ)
            same = (out / 'same.tsv').read_text()
            self.assertIn(r'odd\nname.txt', same)
            self.assertEqual(len(same.splitlines()), 2)

    def test_pii_sweep_scans_newline_named_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'archive'
            sidecars = root / '_DERIVED' / 'text'
            sidecars.mkdir(parents=True)
            (sidecars / 'odd\nname.txt').write_text(
                'synthetic ID ' + '-'.join(('123', '45', '6789')))
            result = subprocess.run(
                ['bash', str(ROOT / 'local_pipeline/pii_sweep.sh'), str(root)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('scanned 1 sidecars, 1 carry', result.stdout)
            report = next((root / '_DERIVED').glob('_pii_sweep_*.txt')).read_text()
            self.assertIn(r'--- odd\nname', report)

    def test_extract_failure_does_not_leave_a_final_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fakebin = root / 'bin'
            fakebin.mkdir()
            self._write_extractor_fakes(fakebin)
            archive = root / 'archive'
            archive.mkdir()
            (archive / 'broken.pdf').write_bytes(b'pdf')
            result = self._extract(archive, fakebin, root, FAKE_EXTRACT_FAIL='1')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertFalse((archive / '_DERIVED/text/broken.pdf.txt').exists())
            self.assertEqual(list((archive / '_DERIVED/text').rglob('*.part.*')), [])

    def test_image_detection_failure_is_queued_and_newline_paths_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fakebin = root / 'bin'
            fakebin.mkdir()
            self._write_extractor_fakes(fakebin)
            self._write(fakebin / 'ocrmypdf', """#!/bin/sh
side=
last=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--sidecar" ]; then side="$2"; shift 2
  else last="$1"; shift
  fi
done
printf 'recognized text' > "$side"
printf 'ocr pdf' > "$last"
""")
            archive = root / 'archive'
            archive.mkdir()
            source = archive / 'odd\nname.pdf'
            source.write_bytes(b'pdf')
            failed = self._extract(archive, fakebin, root, FAKE_IMAGE_FAIL='1')
            self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
            failed_queue = list((archive / '_DERIVED').glob('_image_only_*.txt'))[0]
            self.assertEqual(failed_queue.read_bytes(), os.fsencode(os.path.realpath(source)) + b'\0')
            result = self._extract(archive, fakebin, root, FAKE_RASTER='1')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            queues = list((archive / '_DERIVED').glob('_image_only_*.txt'))
            self.assertEqual(len(queues), 1)
            self.assertEqual(queues[0].read_bytes(), os.fsencode(os.path.realpath(source)) + b'\0',
                             result.stdout + result.stderr)
            result = subprocess.run(
                ['bash', str(ROOT / 'local_pipeline/ocr_queue.sh'), str(archive)],
                capture_output=True, text=True,
                env=self._env(fakebin, root, OCR_YES='1'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((archive / '_DERIVED/text/odd\nname.pdf.txt').read_text(), 'recognized text')
            legacy = archive / 'legacy.pdf'
            legacy.write_bytes(b'pdf')
            queues[0].write_bytes(os.fsencode(os.path.realpath(legacy)) + b'\n')
            result = subprocess.run(
                ['bash', str(ROOT / 'local_pipeline/ocr_queue.sh'), str(archive)],
                capture_output=True, text=True,
                env=self._env(fakebin, root, OCR_YES='1'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(queues[0].read_bytes(), os.fsencode(os.path.realpath(legacy)) + b'\0')
            self.assertEqual((archive / '_DERIVED/text/legacy.pdf.txt').read_text(), 'recognized text')
            queues[0].write_bytes(b'\0')
            result = subprocess.run(
                ['bash', str(ROOT / 'local_pipeline/ocr_queue.sh'), str(archive)],
                capture_output=True, text=True,
                env=self._env(fakebin, root, OCR_YES='1'))
            self.assertEqual(result.returncode, 1)
            self.assertIn('queue has no valid paths', result.stdout)

    def test_remote_cleartext_ollama_requires_opt_in(self):
        with mock.patch.dict(os.environ, {'OLLAMA_ALLOW_REMOTE': '0'}):
            with self.assertRaises(SystemExit):
                local_triage.validate_ollama_url('http://192.0.2.10:11434')
        with mock.patch.dict(os.environ, {'OLLAMA_ALLOW_REMOTE': '1'}):
            self.assertEqual(local_triage.validate_ollama_url('http://192.0.2.10:11434'),
                             'http://192.0.2.10:11434')
        with self.assertRaises(SystemExit):
            local_triage.validate_ollama_url('@'.join(('https://user:password', 'ollama.example')))
        with self.assertRaises(SystemExit):
            local_triage.validate_ollama_url('https://ollama.example?token=example')
        self.assertEqual(local_triage.validate_ollama_url('https://ollama.example'), 'https://ollama.example')
        self.assertEqual(local_triage.validate_ollama_url('http://localhost:11434/'), 'http://localhost:11434')

    def test_ask_local_refuses_remote_http_without_sending_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakebin = Path(tmp)
            self._write(fakebin / 'ollama', """#!/bin/sh
printf 'NAME ID SIZE MODIFIED\\nstub:latest id 1GB today\\n'
""")
            env = os.environ.copy()
            env.update({
                'PATH': str(fakebin) + os.pathsep + env['PATH'],
                'OLLAMA_MODEL': 'stub:latest',
                'OLLAMA_URL': 'http://192.0.2.10:11434',
                'OLLAMA_ALLOW_REMOTE': '0',
            })
            result = subprocess.run(
                ['bash', str(ROOT / 'local_pipeline/ask_local.sh'), 'classify'],
                input='private document text', capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(result.returncode, 1)
            self.assertIn('use HTTPS or set OLLAMA_ALLOW_REMOTE=1', result.stderr)

    def test_datecheck_fails_when_http_request_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakebin = Path(tmp)
            self._write(fakebin / 'curl', '#!/bin/sh\nexit 7\n')
            env = os.environ.copy()
            env['PATH'] = str(fakebin) + os.pathsep + env['PATH']
            result = subprocess.run(
                ['bash', str(ROOT / 'tools/datecheck.sh'), 'https://example.test'],
                capture_output=True, text=True, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ERROR: request failed', result.stderr)

    def test_backup_bundle_accepts_git_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, worktree, dest = root / 'repo', root / 'worktree', root / 'backups'
            repo.mkdir()
            dest.mkdir()
            self._git(repo, 'init')
            self._git(repo, 'config', 'user.name', 'Test')
            self._git(repo, 'config', 'user.email', 'test@example.com')
            (repo / 'tracked.txt').write_text('fixture')
            self._git(repo, 'add', 'tracked.txt')
            self._git(repo, 'commit', '-m', 'fixture')
            self._git(repo, 'worktree', 'add', '-b', 'backup-test', str(worktree))
            self.assertTrue((worktree / '.git').is_file())
            env = os.environ.copy()
            env.update({'REPO': str(worktree), 'BACKUP_DEST': str(dest)})
            result = subprocess.run(
                ['bash', str(ROOT / 'tools/backup_repo_bundle.sh')],
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(list(dest.glob('*.bundle'))), 1)

    def test_vision_ocr_coverage_metrics_distinguish_partial_runs(self):
        full = vision_ocr.coverage_metrics(3, 12, 3, 0, True, '')
        self.assertTrue(full['coverage_complete'])
        self.assertEqual(full['unprocessed_pages'], 0)
        self.assertEqual((full['ocr_pages'], full['recognised_pages']), (3, 3))
        limited = vision_ocr.coverage_metrics(20, 12, 12, 0, True, '')
        self.assertFalse(limited['coverage_complete'])
        self.assertEqual(limited['unprocessed_pages'], 8)
        self.assertEqual(limited['ocr_pages'], 12)  # pages selected, as in earlier releases
        failed = vision_ocr.coverage_metrics(3, 12, 2, 1, True, 'page render failed')
        self.assertFalse(failed['coverage_complete'])
        self.assertEqual(failed['failed_pages'], 1)
        self.assertEqual((failed['ocr_pages'], failed['recognised_pages']), (3, 2))
        self.assertFalse(vision_ocr.coverage_metrics(0, 12, 0, 0, False, 'could not open PDF')['coverage_complete'])

    def test_vision_ocr_counts_blank_success_and_recognition_failure(self):
        with mock.patch.object(vision_ocr, '_recognise', side_effect=[[], ['text']]):
            self.assertEqual(vision_ocr.ocr_png_with_status('page.png'), ('text', True))
        with mock.patch.object(vision_ocr, '_recognise', side_effect=[None, None]):
            self.assertEqual(vision_ocr.ocr_png_with_status('page.png'), ('', False))

    def test_hyphen_separator_does_not_flip_the_sign(self):
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance - 50.00'), '50.00')
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance - 1,234.56'), '1,234.56')
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance - $1,234.56'), '1,234.56')
        self.assertEqual(scan_intake.amount('min_due', 'Minimum Payment Due: -25.00'), '-25.00')

    def test_backup_bundle_refuses_subfolder_and_git_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, dest = root / 'repo', root / 'backups'
            (repo / 'sub').mkdir(parents=True)
            dest.mkdir()
            self._git(repo, 'init')
            self._git(repo, 'config', 'user.name', 'Test')
            self._git(repo, 'config', 'user.email', '@'.join(('test', 'example.com')))
            (repo / 'sub' / 'tracked.txt').write_text('fixture')
            self._git(repo, 'add', '.')
            self._git(repo, 'commit', '-m', 'fixture')
            for target in (repo / 'sub', repo / '.git'):
                env = os.environ.copy()
                env.update({'REPO': str(target), 'BACKUP_DEST': str(dest)})
                result = subprocess.run(
                    ['bash', str(ROOT / 'tools/backup_repo_bundle.sh')],
                    capture_output=True, text=True, env=env, timeout=60)
                self.assertEqual(result.returncode, 1, target.name + ': ' + result.stdout + result.stderr)
                self.assertIn('not the top folder', result.stdout)
            self.assertEqual(list(dest.glob('*.bundle')), [])

    def test_identical_copies_with_different_counts_are_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive, folder, out = root / 'drive', root / 'folder', root / 'out'
            for d in (drive / 'a', drive / 'b', folder / 'c'):
                d.mkdir(parents=True)
            for d in (drive / 'a', drive / 'b', folder / 'c'):
                (d / 'copy.txt').write_bytes(b'same bytes')
            result = subprocess.run(
                [sys.executable, str(ROOT / 'local_pipeline/drive_folder_diff.py'),
                 '--drive', str(drive), '--folder', str(folder), '--out', str(out), '--hash'],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('copy.txt', (out / 'same.tsv').read_text())
            self.assertNotIn('copy.txt', (out / 'differ.tsv').read_text())

    def test_widget_dump_continues_after_one_failed_file(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest('pypdf is not installed (widget_dump.py needs it)')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fakebin = root / 'bin'
            fakebin.mkdir()
            self._write(fakebin / 'pdftotext', """#!/bin/sh
case "$2" in *bad.pdf) echo 'cannot read' >&2; exit 1;; esac
printf '<page width="612" height="792"></page>'
""")
            for name in ('bad.pdf', 'good.pdf'):
                w = PdfWriter()
                w.add_blank_page(width=612, height=792)
                with open(root / name, 'wb') as fh:
                    w.write(fh)
            env = os.environ.copy()
            env['PATH'] = str(fakebin) + os.pathsep + env['PATH']
            result = subprocess.run(
                [sys.executable, str(ROOT / 'pdf_forms/widget_dump.py'), str(root / 'bad.pdf'), str(root / 'good.pdf')],
                capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(result.returncode, 1)
            self.assertIn('pdftotext failed', result.stderr)
            self.assertIn('##### ' + str(root / 'good.pdf'), result.stdout)

    def test_datecheck_reads_date_from_an_error_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakebin = Path(tmp)
            self._write(fakebin / 'curl', """#!/bin/sh
case "$1" in -f*) exit 22;; esac
printf 'HTTP/1.1 403 Forbidden\r\nDate: Wed, 01 Jan 2031 00:00:00 GMT\r\n\r\n'
""")
            env = os.environ.copy()
            env['PATH'] = str(fakebin) + os.pathsep + env['PATH']
            result = subprocess.run(
                ['bash', str(ROOT / 'tools/datecheck.sh'), 'https://example.test'],
                capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Date: Wed, 01 Jan 2031', result.stdout)
            self.assertIn('403', result.stdout)

    def test_dash_leaders_read_as_a_positive_amount(self):
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance -----1,234.56'), '1,234.56')
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance -- 1,234.56'), '1,234.56')
        self.assertEqual(scan_intake.amount('min_due', 'Minimum Payment Due ----25.00'), '25.00')
        # a single minus attached to the figure is still a sign
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance -1,234.56'), '-1,234.56')

    def test_unicode_minus_keeps_the_sign(self):
        minus = '−'
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance ' + minus + '$50.00'), '-50.00')
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance ' + minus + '50.00'), '-50.00')
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance ' + minus + ' 50.00'), '50.00')
        # the minus sits first in the character class: a colon or a letter before the figure is fine
        self.assertEqual(scan_intake.amount('new_balance', 'New Balance:1,234.56'), '1,234.56')

    def test_large_image_listing_is_not_a_failed_check(self):
        # The listing of a scan with thousands of images is bigger than a pipe buffer. Reading it
        # must not end in a broken pipe, which under pipefail looked like a failed check.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fakebin = root / 'bin'
            fakebin.mkdir()
            self._write_extractor_fakes(fakebin)
            archive = root / 'archive'
            archive.mkdir()
            source = archive / 'big scan.pdf'
            source.write_bytes(b'pdf')
            result = self._extract(archive, fakebin, root, FAKE_RASTER='1', FAKE_RASTER_LINES='5000')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            queue = list((archive / '_DERIVED').glob('_image_only_*.txt'))[0]
            self.assertEqual(queue.read_bytes(), os.fsencode(os.path.realpath(source)) + b'\0')
            log = list((archive / '_DERIVED').glob('_extract_log_*.txt'))[0].read_text()
            self.assertNotIn('FAIL_IMAGE_CHECK', log)
            self.assertIn('5000 rasters', log)

    def test_ocr_done_file_with_failed_image_check_is_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fakebin = root / 'bin'
            fakebin.mkdir()
            self._write_extractor_fakes(fakebin)
            self._write_fake_ocrmypdf(fakebin)
            archive = root / 'archive'
            archive.mkdir()
            source = archive / 'scan.pdf'
            source.write_bytes(b'pdf')
            past = source.stat().st_mtime - 120     # older than anything the run writes, also to the second
            os.utime(source, (past, past))
            first = self._extract(archive, fakebin, root, FAKE_RASTER='1')
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            ocr = subprocess.run(
                ['bash', str(ROOT / 'local_pipeline/ocr_queue.sh'), str(archive)],
                capture_output=True, text=True, env=self._env(fakebin, root, OCR_YES='1'), timeout=60)
            self.assertEqual(ocr.returncode, 0, ocr.stdout + ocr.stderr)
            for _ in range(2):
                again = self._extract(archive, fakebin, root, FAKE_IMAGE_FAIL='1')
                self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            queue = list((archive / '_DERIVED').glob('_image_only_*.txt'))[0]
            self.assertEqual(queue.read_bytes(), b'')
            log = list((archive / '_DERIVED').glob('_extract_log_*.txt'))[0].read_text()
            self.assertNotIn('FAIL_IMAGE_CHECK', log)

    def test_legacy_queue_is_left_whole_when_its_rewrite_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fakebin = root / 'bin'
            fakebin.mkdir()
            self._write_extractor_fakes(fakebin)
            self._write_fake_ocrmypdf(fakebin)
            archive = root / 'archive'
            (archive / '_DERIVED').mkdir(parents=True)
            queue = archive / '_DERIVED' / '_image_only_2030-01-15.txt'
            base = os.fsencode(os.path.realpath(archive))
            original = b''.join(base + b'/folder-%04d/statement-scan-%04d.pdf\n' % (i, i) for i in range(400))
            queue.write_bytes(original)
            # A file size limit makes the rewrite fail part way, as a full disk would.
            script = "trap '' XFSZ; ulimit -f 8; exec bash %s %s" % (
                shlex.quote(str(ROOT / 'local_pipeline/ocr_queue.sh')), shlex.quote(str(archive)))
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                                    env=self._env(fakebin, root), stdin=subprocess.DEVNULL, timeout=60)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('could not convert', result.stdout)
            self.assertEqual(queue.read_bytes(), original)
            self.assertEqual(list((archive / '_DERIVED').glob('*.part.*')), [])

    def test_widget_dump_skips_a_file_pypdf_cannot_read(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest('pypdf is not installed (widget_dump.py needs it)')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fakebin = root / 'bin'
            fakebin.mkdir()
            self._write(fakebin / 'pdftotext', """#!/bin/sh
printf '<page width="612" height="792"></page>'
""")
            (root / 'bad.pdf').write_bytes(b'this is not a PDF file\n')
            w = PdfWriter()
            w.add_blank_page(width=612, height=792)
            with open(root / 'good.pdf', 'wb') as fh:
                w.write(fh)
            env = os.environ.copy()
            env['PATH'] = str(fakebin) + os.pathsep + env['PATH']
            result = subprocess.run(
                [sys.executable, str(ROOT / 'pdf_forms/widget_dump.py'), str(root / 'bad.pdf'), str(root / 'good.pdf')],
                capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('could not be read', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertIn('##### ' + str(root / 'good.pdf'), result.stdout)

    @staticmethod
    def _write(path, content):
        path.write_text(content)
        path.chmod(0o755)

    def _write_extractor_fakes(self, fakebin):
        self._write(fakebin / 'pdftotext', """#!/bin/sh
for last do :; done
if [ "${FAKE_EXTRACT_FAIL:-0}" = 1 ]; then
  printf 'partial output' > "$last"
  exit 1
fi
printf 'short' > "$last"
""")
        self._write(fakebin / 'pdfimages', """#!/bin/sh
if [ "${FAKE_IMAGE_FAIL:-0}" = 1 ]; then exit 2; fi
printf 'page num type width height color comp bpc enc interp object ID x-ppi y-ppi size ratio\\n'
printf '%s\\n' '--------------------------------------------------------------------------------'
if [ "${FAKE_RASTER:-0}" = 1 ]; then
  n=${FAKE_RASTER_LINES:-1}; i=0
  while [ "$i" -lt "$n" ]; do i=$((i+1)); printf '%s\\n' "1 $i image 100 100 rgb 3 8 jpeg no 1 0 72 72 1K 1%"; done
fi
""")

    def _write_fake_ocrmypdf(self, fakebin):
        self._write(fakebin / 'ocrmypdf', """#!/bin/sh
side=
last=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--sidecar" ]; then side="$2"; shift 2
  else last="$1"; shift
  fi
done
printf 'recognized text' > "$side"
printf 'ocr pdf' > "$last"
""")

    @staticmethod
    def _env(fakebin, root, **extra):
        env = os.environ.copy()
        env.update({
            'PDFTOOLS_BIN': str(fakebin),
            'OCR_TMPDIR': str(root / 'ocr-tmp'),
            'HOME': str(root),
        })
        env.update({key: str(value) for key, value in extra.items()})
        return env

    def _extract(self, archive, fakebin, root, **extra):
        return subprocess.run(
            ['bash', str(ROOT / 'local_pipeline/extract_all.sh'), str(archive)],
            capture_output=True, text=True,
            env=self._env(fakebin, root, **extra))

    @staticmethod
    def _git(cwd, *args):
        result = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
