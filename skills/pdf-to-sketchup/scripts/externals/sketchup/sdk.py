"""Prepare an official Windows x64 SDK in the user's runtime directory."""

import hashlib
import json
import re
import shutil
import stat
import struct
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


SDK_PAGE = 'https://extensions.sketchup.com/sketchup-sdk'
MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_EXPANDED = 2 * MAX_DOWNLOAD


class SDKUnavailable(RuntimeError):
    pass


def official_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or not any(host == domain or host.endswith('.' + domain)
                       for domain in ('sketchup.com', 'trimble.com'))):
        raise ValueError('SDK downloads must use an official SketchUp/Trimble HTTPS address')
    return url


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_official(url):
    request = Request(official_url(url), headers={'User-Agent': 'pdf2skp-skill/1.0'})
    return build_opener(OfficialRedirects()).open(request, timeout=60)


class DownloadLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(value for key, value in attrs if key == 'href' and value)


def discover_windows_sdk_url():
    try:
        with open_official(SDK_PAGE) as response:
            body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise ValueError('SDK download page is unexpectedly large')
        links = DownloadLinks()
        links.feed(body.decode('utf-8'))
        candidates = []
        for link in links.links:
            url = urljoin(SDK_PAGE, link)
            name = unquote(urlparse(url).path.rsplit('/', 1)[-1])
            if re.fullmatch(r'SDK[_-]WIN[_-]x64[_-][\w.-]+\.zip', name, re.IGNORECASE):
                official_url(url)
                candidates.append(url)
        if candidates:
            return max(candidates, key=lambda url: tuple(int(n) for n in re.findall(r'\d+', urlparse(url).path)))
    except (OSError, ValueError) as error:
        raise SDKUnavailable(f'Cannot read the official SDK download page: {error}. See {SDK_PAGE}') from error
    raise SDKUnavailable(
        f'No public Windows x64 SDK ZIP is published at {SDK_PAGE}. '
        'The vendor currently requires an SDK access request. '
        'Do not report setup as complete or use unofficial mirrors.')


def download_sdk(url, target, expected_sha256=None):
    if expected_sha256 and not re.fullmatch(r'[a-fA-F0-9]{64}', expected_sha256):
        raise ValueError('SDK SHA-256 must contain 64 hexadecimal characters')
    digest = hashlib.sha256()
    size = 0
    with open_official(url) as response, target.open('wb') as output:
        official_url(response.geturl())
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > MAX_DOWNLOAD:
                raise ValueError('SDK download exceeds the size limit')
            digest.update(block)
            output.write(block)
    checksum = digest.hexdigest()
    if expected_sha256 and checksum != expected_sha256.lower():
        raise ValueError('SDK download SHA-256 does not match')
    return checksum


def extract_sdk(archive, destination):
    # Validate every entry before writing; Windows aliases must also be rejected on macOS tests.
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        total, names = 0, set()
        if len(entries) > 20000:
            raise ValueError('SDK archive contains too many files')
        for item in entries:
            name = item.filename.replace('\\', '/')
            path = PurePosixPath(name)
            reserved = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.IGNORECASE)
            if (path.is_absolute() or not path.parts or '..' in path.parts
                    or any(':' in part or part.endswith((' ', '.')) or reserved.match(part) for part in path.parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError(f'Unsafe SDK archive path: {item.filename}')
            key = str(path).casefold()
            if key in names:
                raise ValueError(f'Duplicate SDK archive path: {item.filename}')
            names.add(key)
            total += item.file_size
            if total > MAX_EXPANDED:
                raise ValueError('SDK archive exceeds the expanded size limit')
        for item in entries:
            target = destination.joinpath(*PurePosixPath(item.filename.replace('\\', '/')).parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)


def windows_x64_dll(path):
    with path.open('rb') as source:
        header = source.read(64)
        if len(header) < 64 or header[:2] != b'MZ':
            return False
        source.seek(struct.unpack_from('<I', header, 0x3c)[0])
        pe = source.read(26)
    return (len(pe) == 26 and pe[:4] == b'PE\0\0'
            and struct.unpack_from('<H', pe, 4)[0] == 0x8664
            and struct.unpack_from('<H', pe, 24)[0] == 0x20b)


def find_sdk_library(root):
    for library in sorted(root.rglob('*')):
        if library.name.casefold() != 'sketchupapi.dll' or not library.is_file():
            continue
        companions = {p.name.casefold(): p for p in library.parent.iterdir() if p.is_file()}
        preferences = companions.get('sketchupcommonpreferences.dll')
        if preferences and windows_x64_dll(library) and windows_x64_dll(preferences):
            return library
    raise ValueError('SDK must contain x64 SketchUpAPI.dll and SketchUpCommonPreferences.dll in the same folder')


def cached_sdk_library(runtime_root, url=None, sha256=None):
    root = runtime_root / 'sdk' / 'windows-x64'
    try:
        manifest = json.loads((root / 'sdk.json').read_text(encoding='utf-8'))
        official_url(manifest['source_url'])
        if url and manifest['source_url'] != url:
            return None
        if sha256 and manifest['archive_sha256'] != sha256.lower():
            return None
        library = find_sdk_library(root / 'package')
        # Detect incomplete or altered extractions before trying to reuse them.
        actual_files = {p.relative_to(root / 'package').as_posix()
                        for p in (root / 'package').rglob('*') if p.is_file()}
        if actual_files != set(manifest['files']):
            return None
        for name, checksum in manifest['files'].items():
            path = (root / 'package' / name).resolve()
            if not path.is_relative_to((root / 'package').resolve()) or not path.is_file():
                return None
            with path.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != checksum:
                    return None
        return library
    except (OSError, ValueError, KeyError, TypeError):
        return None


def prepare_windows_sdk(runtime_root, url=None, sha256=None, refresh=False):
    if not refresh:
        cached = cached_sdk_library(runtime_root, url, sha256)
        if cached:
            return cached
    url = official_url(url or discover_windows_sdk_url())
    sdk_root = runtime_root / 'sdk'
    sdk_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sdk-download-', dir=sdk_root) as folder:
        stage = Path(folder)
        archive = stage / 'sdk.zip'
        checksum = download_sdk(url, archive, sha256)
        extracted = stage / 'windows-x64'
        package = extracted / 'package'
        package.mkdir(parents=True)
        extract_sdk(archive, package)
        library = find_sdk_library(package)
        relative = library.relative_to(extracted)
        files = {}
        for path in package.rglob('*'):
            if path.is_file():
                with path.open('rb') as source:
                    files[path.relative_to(package).as_posix()] = hashlib.file_digest(source, 'sha256').hexdigest()
        manifest = {'source_url': url, 'archive_sha256': checksum, 'files': files}
        (extracted / 'sdk.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        target = sdk_root / 'windows-x64'
        previous = stage / 'previous'
        if target.exists():
            target.rename(previous)
        try:
            extracted.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise
        return target / relative
