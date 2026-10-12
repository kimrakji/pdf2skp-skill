"""Official SDK preparation, cache repair, and Windows fallback behavior."""

import contextlib
import hashlib
import io
import json
import stat
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/pdf-to-sketchup/scripts'
sys.path.insert(0, str(SCRIPTS))

import check_runtime
from externals.sketchup import sdk
from externals.sketchup.c_api import CAPI


URL = 'https://extensions.sketchup.com/SDK_WIN_x64_2026-1-103.zip'


def dll(machine=0x8664):
    body = bytearray(90)
    body[:2] = b'MZ'
    struct.pack_into('<I', body, 0x3c, 64)
    body[64:68] = b'PE\0\0'
    struct.pack_into('<H', body, 68, machine)
    struct.pack_into('<H', body, 88, 0x20b)
    return bytes(body)


def archive(entries=None):
    if entries is None:
        entries = [('binaries/sketchup/x64/SketchUpAPI.dll', dll()),
                   ('binaries/sketchup/x64/SketchUpCommonPreferences.dll', dll()),
                   ('LICENSE.txt', b'test license')]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as bundle:
        for name, data in entries:
            bundle.writestr(name, data)
    return buffer.getvalue()


class Response(io.BytesIO):
    def geturl(self):
        return URL


class SDKSetupTest(unittest.TestCase):
    def test_download_preserves_companion_and_license_then_reuses_cache_offline(self):
        data = archive()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(sdk, 'open_official', return_value=Response(data)) as request:
                library = sdk.prepare_windows_sdk(root, URL, hashlib.sha256(data).hexdigest())
            request.assert_called_once_with(URL)
            self.assertTrue((library.parent / 'SketchUpCommonPreferences.dll').is_file())
            package = root / 'sdk/windows-x64/package'
            self.assertEqual((package / 'LICENSE.txt').read_bytes(), b'test license')
            with patch.object(sdk, 'open_official', side_effect=AssertionError('offline')):
                self.assertEqual(sdk.prepare_windows_sdk(root), library)
            self.assertEqual({p.name for p in (root / 'sdk').iterdir()}, {'windows-x64'})

    def test_bad_hash_and_invalid_package_do_not_replace_a_working_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(sdk, 'open_official', return_value=Response(archive())):
                library = sdk.prepare_windows_sdk(root, URL)
            for body, checksum in [(archive(), '0' * 64), (b'not a ZIP', None),
                                   (archive([('SketchUpAPI.dll', dll())]), None),
                                   (archive([('SketchUpAPI.dll', dll(0x14c)),
                                             ('SketchUpCommonPreferences.dll', dll(0x14c))]), None)]:
                with self.subTest(checksum=checksum, size=len(body)):
                    with patch.object(sdk, 'open_official', return_value=Response(body)):
                        with self.assertRaises((ValueError, zipfile.BadZipFile)):
                            sdk.prepare_windows_sdk(root, URL, checksum, refresh=True)
                    self.assertEqual(sdk.cached_sdk_library(root), library)
                    self.assertEqual({p.name for p in (root / 'sdk').iterdir()}, {'windows-x64'})

    def test_incomplete_or_changed_cache_is_downloaded_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(sdk, 'open_official', return_value=Response(archive())):
                library = sdk.prepare_windows_sdk(root, URL)
            (library.parent / 'SketchUpCommonPreferences.dll').unlink()
            self.assertIsNone(sdk.cached_sdk_library(root))
            with patch.object(sdk, 'open_official', return_value=Response(archive())) as request:
                self.assertEqual(sdk.prepare_windows_sdk(root, URL), library)
            request.assert_called_once()
            library.write_bytes(dll() + b'altered')
            self.assertIsNone(sdk.cached_sdk_library(root))

    def test_rejects_traversal_windows_aliases_symlinks_and_duplicate_paths(self):
        unsafe = ['../escape.dll', '/escape.dll', 'C:\\escape.dll', '..\\escape.dll',
                  'CON.dll', 'folder./file', 'file:stream']
        for name in unsafe:
            with self.subTest(path=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                path = root / 'input.zip'
                path.write_bytes(archive([('safe.txt', b'safe'), (name, b'unsafe')]))
                destination = root / 'package'
                destination.mkdir()
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    sdk.extract_sdk(path, destination)
                self.assertEqual(list(destination.iterdir()), [])
        link = zipfile.ZipInfo('link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for entries in [[(link, b'../outside')], [('File.dll', b'a'), ('file.dll', b'b')]]:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                path = root / 'input.zip'
                path.write_bytes(archive(entries))
                with self.assertRaises(ValueError):
                    sdk.extract_sdk(path, root / 'package')

    def test_official_links_only_and_unavailable_page(self):
        for url in ['http://extensions.sketchup.com/sdk.zip', 'https://example.com/sdk.zip',
                    'https://sketchup.com.example.com/sdk.zip', 'https://user@sketchup.com/sdk.zip']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                sdk.official_url(url)
        with patch.object(sdk, 'open_official', return_value=Response(b'<button>Request Access</button>')):
            with self.assertRaises(sdk.SDKUnavailable):
                sdk.discover_windows_sdk_url()
        page = (f'<a href="{URL}">Windows</a>'
                '<a href="https://extensions.sketchup.com/SDK_WIN_x64_2026-2-1.zip">Windows</a>'
                '<a href="https://extensions.sketchup.com/SDK_MAC_2026-3-1.zip">Mac</a>').encode()
        with patch.object(sdk, 'open_official', return_value=Response(page)):
            self.assertTrue(sdk.discover_windows_sdk_url().endswith('2026-2-1.zip'))
        with self.assertRaises(ValueError):
            sdk.OfficialRedirects().redirect_request(None, None, 302, '', {}, 'https://example.com/sdk.zip')


class WindowsFallbackTest(unittest.TestCase):
    def run_setup(self, root, candidates=(), explicit=None, native_error=None, cached=None, download_error=None):
        args = ['check_runtime.py', '--runtime-root', str(root)]
        if explicit:
            args += ['--library', str(explicit)]
        with (patch.object(sys, 'argv', args), patch.object(sys, 'platform', 'win32'),
              patch.object(check_runtime.importlib, 'import_module'),
              patch.object(check_runtime, 'library_candidates', return_value=list(candidates)),
              patch.object(check_runtime, 'cached_sdk_library', return_value=cached),
              patch.object(check_runtime, 'check_native', side_effect=native_error) as native,
              patch.object(check_runtime, 'prepare_windows_sdk', return_value=root / 'sdk-api.dll',
                           side_effect=download_error) as prepare,
              contextlib.redirect_stdout(io.StringIO())):
            code = check_runtime.main()
        report = json.loads((root / 'runtime.json').read_text(encoding='utf-8'))
        return code, report, native, prepare

    def test_missing_or_unusable_installed_library_downloads_and_verifies_sdk(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for candidates, error in [((), None), ([root / 'installed.dll'], [RuntimeError('bad install'), None])]:
                code, report, native, prepare = self.run_setup(root, candidates, native_error=error)
                self.assertEqual(code, 0)
                self.assertTrue(report['native_roundtrip_verified'])
                self.assertEqual(report['sketchup_source'], 'sdk')
                self.assertEqual(report['sdk_status'], 'verified')
                prepare.assert_called_once()
                native.assert_called_with(root / 'sdk-api.dll', root)

    def test_working_installed_or_explicit_library_does_not_download_sdk(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            installed = root / 'installed.dll'
            code, report, _, prepare = self.run_setup(root, [installed])
            self.assertEqual(code, 0)
            self.assertEqual(report['sketchup_source'], 'installed')
            prepare.assert_not_called()
            code, report, _, prepare = self.run_setup(root, [installed], explicit=installed,
                                                     native_error=RuntimeError('invalid explicit library'))
            self.assertEqual(code, 1)
            self.assertFalse(report['ready'])
            prepare.assert_not_called()

    def test_unavailable_download_and_failed_native_probe_clear_previous_ready_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'runtime.json').write_text('{"ready": true}')
            code, report, native, prepare = self.run_setup(root, download_error=sdk.SDKUnavailable('Request access'))
            self.assertEqual(code, 1)
            self.assertFalse(report['ready'])
            self.assertEqual(report['sdk_status'], 'unavailable')
            native.assert_not_called()
            code, report, native, prepare = self.run_setup(root, native_error=RuntimeError('missing runtime DLL'))
            self.assertEqual(code, 1)
            self.assertFalse(report['ready'])
            self.assertEqual(report['sdk_status'], 'failed')
            self.assertIsNone(report['sketchup_library'])
            prepare.assert_called_once()

    def test_cached_native_failure_refreshes_once_and_reverifies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            code, report, native, prepare = self.run_setup(root, cached=root / 'cached.dll',
                                                         native_error=[RuntimeError('bad cache'), None])
            self.assertEqual(code, 0)
            self.assertTrue(report['ready'])
            self.assertEqual(native.call_count, 2)
            prepare.assert_called_once_with(root, None, None, refresh=True)

    def test_windows_dll_search_directory_lasts_until_termination_and_closes_on_load_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            library = Path(folder) / 'api.dll'
            library.touch()
            handle, native = Mock(), Mock()
            with (patch('externals.sketchup.c_api.sys.platform', 'win32'),
                  patch('externals.sketchup.c_api.os.add_dll_directory', return_value=handle, create=True) as directory,
                  patch('externals.sketchup.c_api.c.CDLL', return_value=native)):
                api = CAPI(library)
                with api:
                    handle.close.assert_not_called()
                native.SUTerminate.assert_called_once()
                handle.close.assert_called_once()
                with api:
                    self.assertEqual(directory.call_count, 2)
                self.assertEqual(handle.close.call_count, 2)
            handle.reset_mock()
            with (patch('externals.sketchup.c_api.sys.platform', 'win32'),
                  patch('externals.sketchup.c_api.os.add_dll_directory', return_value=handle, create=True),
                  patch('externals.sketchup.c_api.c.CDLL', side_effect=OSError('missing DLL'))):
                with self.assertRaises(OSError):
                    CAPI(library)
                handle.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
