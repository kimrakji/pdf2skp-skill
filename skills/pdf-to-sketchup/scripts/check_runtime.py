"""Discover SketchUp and verify a real draft round trip in disposable files."""

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from core.files import digest
from externals.sketchup.sdk import SDKUnavailable, cached_sdk_library, prepare_windows_sdk


def library_candidates(explicit=None):
    if explicit:
        return [Path(explicit).expanduser()]
    roots = [Path('/Applications'), Path.home() / 'Applications']
    patterns = ['SketchUp*/SketchUp.app/Contents/Frameworks/SketchUpAPI.framework/SketchUpAPI',
                'SketchUp.app/Contents/Frameworks/SketchUpAPI.framework/SketchUpAPI']
    if sys.platform == 'win32':
        roots = [Path(os.environ.get('ProgramFiles', 'C:/Program Files')),
                 Path(os.environ.get('ProgramW6432', 'C:/Program Files'))]
        patterns = ['SketchUp/SketchUp*/SketchUpAPI.dll', 'SketchUp*/SketchUpAPI.dll']
    paths = {p.resolve() for root in roots for pattern in patterns for p in root.glob(pattern) if p.is_file()}
    return sorted(paths, reverse=True)


def check_native(library, runtime_root):
    from PIL import Image

    with tempfile.TemporaryDirectory(prefix='native-check-', dir=runtime_root) as folder:
        root = Path(folder)
        image = root / 'source-plan.png'
        Image.new('RGB', (32, 32), 'white').save(image)
        walls = [{'id': 'setup-wall', 'outer_mm': [[0, 0], [600, 0], [600, 100], [0, 100]],
                  'holes_mm': [], 'height_mm': 2700, 'area_mm2': 60000,
                  'group': 'Walls_Default', 'source_ids': ['setup-check']}]
        reference = {'image_path': 'source-plan.png', 'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                     'width_mm': 1000, 'height_mm': 1000, 'origin_mm': [0, 0, -1]}
        model = {'schema_version': '1.0', 'units': 'mm', 'delivery': 'draft', 'status': 'draft_ready',
                 'scope': 'partial', 'review_items': [], 'source_sha256': '0' * 64,
                 'walls': walls, 'reference': reference, 'geometry_sha256': digest({'walls': walls, 'reference': reference})}
        model_path = root / 'model.json'
        model_path.write_text(json.dumps(model), encoding='utf-8')
        common = [sys.executable, str(Path(__file__).with_name('main.py'))]
        for command, output in [('export-native', root / 'check.skp'), ('verify-native', root / 'reopen.json')]:
            args = [*common, command, '--model', str(model_path), '--library', str(library), '--out', str(output)]
            if command == 'verify-native':
                args += ['--skp', str(root / 'check.skp')]
            result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
            if result.returncode:
                raise RuntimeError(f'{command} failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}')
        report = json.loads((root / 'reopen.json').read_text(encoding='utf-8'))
        if report.get('wall_count') != 1 or not report.get('reference_verified'):
            raise RuntimeError('Draft wall/source plan round trip was not verified')
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--library', type=Path, default=os.environ.get('PDF2SKP_SKETCHUP_API'))
    parser.add_argument('--sdk-url', help='Published official Windows SDK ZIP URL (agent/developer option)')
    parser.add_argument('--sdk-sha256', help='Expected SDK ZIP SHA-256 (agent/developer option)')
    args = parser.parse_args()
    args.runtime_root.mkdir(parents=True, exist_ok=True)
    report = {'ready': False, 'python': sys.executable, 'platform': sys.platform,
              'sketchup_library': None, 'dependencies_ready': False, 'errors': []}
    try:
        for module in ('pdfplumber', 'pypdf', 'pypdfium2', 'shapely', 'jsonschema', 'PIL'):
            importlib.import_module(module)
        report['dependencies_ready'] = True
        candidates = library_candidates(args.library)
        for library in candidates:
            try:
                check_native(library, args.runtime_root)
                report.update(ready=True, sketchup_library=str(library.resolve()), native_roundtrip_verified=True,
                              sketchup_source='explicit' if args.library else 'installed')
                break
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
                report['errors'].append(f'{library}: {error}')
        if not report['ready'] and sys.platform == 'win32' and not args.library:
            report['sdk_status'] = 'preparing'
            try:
                library = cached_sdk_library(args.runtime_root, args.sdk_url, args.sdk_sha256)
                from_cache = library is not None
                library = library or prepare_windows_sdk(args.runtime_root, args.sdk_url, args.sdk_sha256)
                try:
                    check_native(library, args.runtime_root)
                except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                    # Repair a cached but unusable SDK once; never retry indefinitely.
                    if not from_cache:
                        raise
                    library = prepare_windows_sdk(args.runtime_root, args.sdk_url, args.sdk_sha256, refresh=True)
                    check_native(library, args.runtime_root)
                report.update(ready=True, sketchup_library=str(library.resolve()), native_roundtrip_verified=True,
                              sketchup_source='sdk', sdk_status='verified')
            except SDKUnavailable as error:
                report['sdk_status'] = 'unavailable'
                report['errors'].append(str(error))
            except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, subprocess.TimeoutExpired) as error:
                report['sdk_status'] = 'failed'
                report['errors'].append(f'Windows SDK setup failed: {error}')
        elif not candidates:
            raise RuntimeError('SketchUp C API was not found in the installed SketchUp. Python is ready; native saving is unavailable.')
    except (ImportError, OSError, RuntimeError) as error:
        report['errors'].append(str(error))
    target = args.runtime_root / 'runtime.json'
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(target)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
