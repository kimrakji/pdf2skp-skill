"""Runtime readiness requires a working native exporter, not an existing file."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1] / 'skills/pdf-to-sketchup'


class RuntimeSetupTest(unittest.TestCase):
    def check_runtime(self, root, library):
        result = subprocess.run(
            [sys.executable, str(SKILL / 'scripts/check_runtime.py'),
             '--runtime-root', str(root), '--library', str(library)],
            capture_output=True, text=True, timeout=90)
        report = json.loads((root / 'runtime.json').read_text(encoding='utf-8'))
        self.assertEqual(json.loads(result.stdout), report)
        self.assertTrue(report['dependencies_ready'])
        return result, report

    def test_missing_explicit_library_does_not_fall_back_to_installed_sketchup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result, report = self.check_runtime(root, root / 'missing-api')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(report['ready'])
            self.assertIsNone(report['sketchup_library'])
            self.assertTrue(report['errors'])

    def test_existing_but_invalid_library_is_not_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake = root / 'fake-api'
            fake.write_text('not a native library', encoding='utf-8')
            result, report = self.check_runtime(root, fake)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(report['ready'])
            self.assertTrue(report['errors'])

    def test_real_roundtrip_and_failure_replaces_previous_ready_report(self):
        library = Path(os.environ.get('INTERIOR_OS_TEST_SKETCHUP_API',
                       '/Applications/SketchUp 2026/SketchUp.app/Contents/Frameworks/SketchUpAPI.framework/SketchUpAPI'))
        if not library.is_file():
            self.skipTest('No local SketchUp C API')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result, report = self.check_runtime(root, library)
            self.assertEqual(result.returncode, 0, result.stderr + str(report))
            self.assertTrue(report['ready'])
            self.assertTrue(report['native_roundtrip_verified'])
            self.assertEqual(set(p.name for p in root.iterdir()), {'runtime.json'})
            result, report = self.check_runtime(root, root / 'missing-api')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(report['ready'])


if __name__ == '__main__':
    unittest.main()
