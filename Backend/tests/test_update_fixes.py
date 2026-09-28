"""Old downloads, streams that get cut off, and the taskbar buttons.

Each of these was seen on the user's machine: old update downloads left in
the data folder, a stream that ended short of what it promised the player,
and taskbar buttons that never appeared because a class was defined twice.
"""

from __future__ import annotations

import ast
import hashlib
import time
from pathlib import Path

import pytest

from dannify import streaming, updates

BACKEND = Path(__file__).resolve().parents[1]


def _load_from_desktop(*names: str) -> dict:
    """Pull top-level definitions out of desktop.py without importing it
    (importing it starts setting up the desktop shell)."""

    source = (BACKEND / 'desktop.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    wanted = [
        node for node in tree.body
        if (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names)
        or (isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in names for t in node.targets
        ))
    ]
    namespace: dict = {'time': time, 'Path': Path}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), 'desktop.py', 'exec'), namespace)
    return namespace


# ---------------------------------------------------------------------------
# Old update downloads
# ---------------------------------------------------------------------------
def test_old_downloads_go_and_a_waiting_update_stays(tmp_path):
    folder = tmp_path / 'updates'
    (folder / 'delta-3.17.0' / 'runtime').mkdir(parents=True)
    (folder / 'delta-3.17.0' / 'Dannify.exe').write_bytes(b'x')
    (folder / 'Dannify-Setup-3.17.0.exe').write_bytes(b'x')
    (folder / 'Dannify-Setup-3.18.0.exe.part').write_bytes(b'x')
    (folder / 'delta-3.18.1').mkdir()
    (folder / 'delta-3.19.0').mkdir()  # newer: waiting to be applied
    (folder / 'Dannify-Setup-3.19.0.exe').write_bytes(b'x')
    (folder / 'notes.txt').write_text('not ours')

    removed = updates.prune_downloads(folder, '3.18.1')

    assert sorted(removed) == [
        'Dannify-Setup-3.17.0.exe', 'Dannify-Setup-3.18.0.exe.part', 'delta-3.17.0', 'delta-3.18.1',
    ]
    assert sorted(p.name for p in folder.iterdir()) == [
        'Dannify-Setup-3.19.0.exe', 'delta-3.19.0', 'notes.txt',
    ]


def test_pruning_copes_with_nothing_there(tmp_path):
    assert updates.prune_downloads(tmp_path / 'missing', '3.18.1') == []


def test_pruning_keeps_everything_when_the_running_version_is_unknown(tmp_path):
    (tmp_path / 'Dannify-Setup-3.17.0.exe').write_bytes(b'x')
    assert updates.prune_downloads(tmp_path, '') == []
    assert (tmp_path / 'Dannify-Setup-3.17.0.exe').exists()


def test_update_check_prefers_assets_for_the_release_version(monkeypatch):
    monkeypatch.setattr(updates, '_fetch_latest', lambda: {
        'tag_name': 'v4.1.0',
        'assets': [
            {'name': 'Dannify-Setup-4.0.0.exe', 'browser_download_url': 'old-setup'},
            {'name': 'Dannify-Setup-4.1.0.exe', 'browser_download_url': 'new-setup', 'digest': 'sha256:' + '1' * 64},
            {'name': 'package-4.0.0.json', 'browser_download_url': 'old-manifest'},
            {'name': 'package-4.1.0.json', 'browser_download_url': 'new-manifest', 'digest': 'sha256:' + '2' * 64},
            {'name': 'package-4.0.0.zip', 'browser_download_url': 'old-package'},
            {'name': 'package-4.1.0.zip', 'browser_download_url': 'new-package'},
        ],
    })

    result = updates.check('4.0.0', force=True)

    assert result['download_url'] == 'new-setup'
    assert result['package_manifest_url'] == 'new-manifest'
    assert result['package_url'] == 'new-package'


def test_update_check_does_not_fallback_to_another_release_asset(monkeypatch):
    monkeypatch.setattr(updates, '_fetch_latest', lambda: {
        'tag_name': 'v4.1.0',
        'assets': [
            {'name': 'Dannify-Setup-4.0.0.exe', 'browser_download_url': 'old-setup'},
            {'name': 'package-4.0.0.json', 'browser_download_url': 'old-manifest'},
        ],
    })
    result = updates.check('4.0.0', force=True)
    assert result['download_url'] == ''
    assert result['package_manifest_url'] == ''


def test_update_check_rejects_assets_without_github_digest(monkeypatch):
    monkeypatch.setattr(updates, '_fetch_latest', lambda: {
        'tag_name': 'v4.1.0',
        'assets': [
            {'name': 'Dannify-Setup-4.1.0.exe', 'browser_download_url': 'setup'},
        ],
    })
    result = updates.check('4.0.0', force=True)
    assert result['available'] is False
    assert 'verified digest' in result['error']


def test_download_rejects_a_release_hash_mismatch(tmp_path, monkeypatch):
    class Response:
        headers = {'Content-Length': '3'}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            if hasattr(self, 'done'):
                return b''
            self.done = True
            return b'bad'

    monkeypatch.setattr(updates.urllib.request, 'urlopen', lambda *a, **k: Response())
    with pytest.raises(RuntimeError, match='hash'):
        updates.download('https://example.invalid/Dannify-Setup-4.1.0.exe', tmp_path, expected_sha256='0' * 64)
    assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------------------
# A stream the CDN cuts off part way
# ---------------------------------------------------------------------------
AUDIO = bytes(range(256)) * 400  # 102400 bytes


class FakeResponse:
    def __init__(self, start, end, total, cut_after=None, status=206):
        self.status_code = status
        self.start, self.end, self.cut_after = start, end, cut_after
        self.headers = {'Content-Range': f'bytes {start}-{end}/{total}', 'Content-Length': str(end - start + 1)}
        if status == 200:
            self.headers = {'Content-Length': str(total)}
        self.closed = False

    def iter_content(self, size):
        body = AUDIO[self.start:self.end + 1]
        sent = 0
        for at in range(0, len(body), 4096):
            if self.cut_after is not None and sent >= self.cut_after:
                raise ConnectionResetError('the CDN let go')
            chunk = body[at:at + 4096]
            sent += len(chunk)
            yield chunk

    def close(self):
        self.closed = True


@pytest.fixture
def cdn(monkeypatch):
    asked = []
    plan = {'cuts': [], 'status': 206}

    def get_range(url, range_header, timeout=12.0, **_):
        first, _, last = range_header[len('bytes='):].partition('-')
        asked.append(range_header)
        cut = plan['cuts'].pop(0) if plan['cuts'] else None
        return FakeResponse(int(first), int(last), len(AUDIO), cut_after=cut, status=plan['status'])

    monkeypatch.setattr(streaming, '_http_get_range', get_range)
    return asked, plan


def test_a_cut_stream_is_picked_up_where_it_stopped(cdn):
    asked, plan = cdn
    plan['cuts'] = [20000]  # the second connection is cut too
    first = FakeResponse(0, len(AUDIO) - 1, len(AUDIO), cut_after=30000)
    got = b''.join(streaming._relay('vid', first, 'https://cdn/x'))
    assert got == AUDIO
    # Each connection hands over whole 4096 byte chunks before it drops, so
    # the first got 8 of them to the player and the second 5 more.
    assert asked == [f'bytes=32768-{len(AUDIO) - 1}', f'bytes={32768 + 20480}-{len(AUDIO) - 1}']


def test_a_seek_range_is_resumed_within_its_own_span(cdn):
    asked, plan = cdn
    first = FakeResponse(50000, 80000, len(AUDIO), cut_after=8000)
    got = b''.join(streaming._relay('vid', first, 'https://cdn/x'))
    assert got == AUDIO[50000:80001]
    assert asked == [f'bytes={50000 + 8192}-80000']


def test_it_gives_up_after_a_few_tries(cdn):
    asked, plan = cdn
    plan['cuts'] = [0, 0, 0, 0, 0]
    first = FakeResponse(0, len(AUDIO) - 1, len(AUDIO), cut_after=4096)
    got = b''.join(streaming._relay('vid', first, 'https://cdn/x'))
    assert len(asked) == streaming.RESUMES
    assert AUDIO.startswith(got) and len(got) < len(AUDIO)


def test_a_cdn_that_will_not_resume_ends_the_stream(cdn):
    asked, plan = cdn
    plan['status'] = 200  # answered with the whole file instead of the part
    first = FakeResponse(0, len(AUDIO) - 1, len(AUDIO), cut_after=10000)
    got = b''.join(streaming._relay('vid', first, 'https://cdn/x'))
    assert len(asked) == 1 and len(got) < len(AUDIO)


def test_a_whole_stream_is_passed_through_untouched(cdn):
    asked, _ = cdn
    first = FakeResponse(0, len(AUDIO) - 1, len(AUDIO), status=200)
    assert b''.join(streaming._relay('vid', first, 'https://cdn/x')) == AUDIO
    assert asked == []


def test_the_relay_always_gives_its_slot_back(cdn):
    before = streaming._PROXY_SEMA._value
    first = FakeResponse(0, len(AUDIO) - 1, len(AUDIO), cut_after=4096)
    gen = streaming._relay('vid', first, 'https://cdn/x')
    next(gen)
    gen.close()  # the listener seeked away
    assert streaming._PROXY_SEMA._value == before
    assert first.closed


# ---------------------------------------------------------------------------
# A name defined twice in one module replaces the first without a word
# ---------------------------------------------------------------------------
def test_no_module_defines_the_same_name_twice():
    found = {}
    for path in [BACKEND / 'main.py', BACKEND / 'desktop.py', *sorted((BACKEND / 'dannify').glob('*.py'))]:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        names = [
            n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        twice = sorted({n for n in names if names.count(n) > 1})
        if twice:
            found[path.name] = twice
    assert found == {}


@pytest.mark.skipif(not hasattr(__import__('ctypes'), 'WinDLL'), reason='Windows only')
def test_the_taskbar_guid_parses_the_taskbar_interface():
    import ctypes

    tree = ast.parse((BACKEND / 'desktop.py').read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == '_GUID')
    ns = {'ctypes': ctypes, 'ole32': ctypes.WinDLL('ole32')}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'desktop.py', 'exec'), ns)

    iid = ns['_GUID'].parse('{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}')  # ITaskbarList3
    assert (iid.Data1, iid.Data2, iid.Data3) == (0xEA1AFB91, 0x9E28, 0x4B86)
    assert bytes(iid.Data4) == bytes.fromhex('90E99E9F8A5EEFAF')
