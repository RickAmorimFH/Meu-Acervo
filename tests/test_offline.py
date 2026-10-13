"""Conjunto independente que roda mesmo sem Flask/yt-dlp instalados.

É uma verificação de lógica pura; NÃO substitui os testes de integração.
"""
import importlib.util
import io
import sys
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VID = "X9RjRGR0ipg"

@pytest.fixture(scope="module")
def downloader_offline():
    name = "downloader_in_offline_test"
    spec = importlib.util.spec_from_file_location(name, ROOT / "downloader.py")
    module = importlib.util.module_from_spec(spec)
    old = sys.modules.get("yt_dlp")
    sys.modules["yt_dlp"] = types.ModuleType("yt_dlp")
    try:
        spec.loader.exec_module(module)
    finally:
        if old is not None:
            sys.modules["yt_dlp"] = old
        else:
            del sys.modules["yt_dlp"]
    return module


def test_normalizes_links(downloader_offline):
    d = downloader_offline
    assert d.normalize_link("https://youtu.be/" + VID)[1] == f"https://www.youtube.com/watch?v={VID}"
    assert d.normalize_link("https://youtube.com/shorts/" + VID)[0] == VID


def test_blocks_ssrf_and_invalid_ids(downloader_offline):
    d = downloader_offline
    for bad in [f"https://youtube.com.evil.org/watch?v={VID}",
                f"https://youtube.com@127.0.0.1/watch?v={VID}",
                f"https://youtube.com:8042/watch?v={VID}",
                f"http://youtu.be/{VID}", "https://youtu.be/a"]:
        with pytest.raises(d.UserInputError):
            d.normalize_link(bad)


def test_duplicate_limit_and_error_line(downloader_offline):
    d = downloader_offline
    rows, duplicates = d.parse_links(f"https://youtu.be/{VID}\nhttps://youtube.com/watch?v={VID}")
    assert len(rows) == 1 and duplicates == 1
    with pytest.raises(d.UserInputError, match="Linha 2"):
        d.parse_links(f"https://youtu.be/{VID}\nhttps://localhost")
    with pytest.raises(d.UserInputError):
        d.parse_links("\n".join(f"https://youtu.be/{n:011d}" for n in range(11)))


def test_safe_archive_and_sizes(downloader_offline, tmp_path):
    d = downloader_offline
    names = ["track 1.mp3", "track 2.mp3"]
    files = []
    for n in names:
        target = tmp_path / n
        target.write_bytes(b"abc")
        files.append(target)
    archive = tmp_path / "result.zip"
    d.create_zip(files, archive)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert z.namelist() == ["01_track 1.mp3", "02_track 2.mp3"]
    assert d.total_disk_bytes(tmp_path) > 6
    assert "/" not in d.safe_filename("bad/folder/name.mp3")


def test_mocked_download_mp4_configuration(downloader_offline, tmp_path, monkeypatch):
    """Executa toda a função sem rede: simula os callbacks do yt-dlp."""
    d = downloader_offline
    captured = {}
    class FakeYDL:
        def __init__(self, options):
            captured.update(options)
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def extract_info(self, url, download):
            assert url.endswith(VID) and download is True
            target = Path(captured['outtmpl']).parent
            (target / 'Video [X9RjRGR0ipg].mp4').write_bytes(b'video + audio')
            for hook in captured['progress_hooks']:
                hook({'status': 'downloading', 'downloaded_bytes': 50, 'total_bytes': 100})
                hook({'status': 'finished'})
            for hook in captured['postprocessor_hooks']:
                hook({'status': 'started'})
    monkeypatch.setattr(d.yt_dlp, 'YoutubeDL', FakeYDL, raising=False)
    monkeypatch.setattr(d.shutil, 'which', lambda _: '/bin/ffmpeg')
    from threading import Event
    from time import monotonic
    stages = []
    result = d.download_video(f'https://www.youtube.com/watch?v={VID}', 'mp4',
                              tmp_path / 'video_01', tmp_path, Event(), monotonic() + 10,
                              10_000, 5000, lambda a, b: stages.append((a, b)))
    assert result.suffix == '.mp4' and result.read_bytes() == b'video + audio'
    assert captured['allowed_extractors'] == ['youtube']
    assert captured['merge_output_format'] == 'mp4'
    assert captured['postprocessors'][0]['key'] == 'FFmpegVideoConvertor'
    assert any(stage == 'Baixando' and value == 50 for stage, value in stages)
    assert any(stage == 'Convertendo e finalizando' for stage, _ in stages)


def test_mocked_download_mp3_configuration(downloader_offline, tmp_path, monkeypatch):
    d = downloader_offline
    captured = {}
    class FakeYDL:
        def __init__(self, options): captured.update(options)
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def extract_info(self, url, download):
            (Path(captured['outtmpl']).parent / 'Audio.mp3').write_bytes(b'audio')
    monkeypatch.setattr(d.yt_dlp, 'YoutubeDL', FakeYDL, raising=False)
    monkeypatch.setattr(d.shutil, 'which', lambda _: '/bin/ffmpeg')
    from threading import Event
    from time import monotonic
    result = d.download_video(f'https://www.youtube.com/watch?v={VID}', 'mp3',
                              tmp_path / 'media', tmp_path, Event(), monotonic() + 10,
                              10_000, 5000, lambda a, b: None)
    assert result.suffix == '.mp3'
    assert captured['format'] == 'bestaudio/best'
    assert captured['postprocessors'][0]['key'] == 'FFmpegExtractAudio'


def test_mocked_download_enforces_progress_limits(downloader_offline, tmp_path, monkeypatch):
    d = downloader_offline
    class FakeYDL:
        def __init__(self, options): self.options = options
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def extract_info(self, url, download):
            self.options['progress_hooks'][0]({'status':'downloading','downloaded_bytes':5001,'total_bytes':6000})
    monkeypatch.setattr(d.yt_dlp, 'YoutubeDL', FakeYDL, raising=False)
    monkeypatch.setattr(d.shutil, 'which', lambda _: '/bin/ffmpeg')
    from threading import Event
    from time import monotonic
    with pytest.raises(d.ResourceLimitError):
        d.download_video(f'https://www.youtube.com/watch?v={VID}', 'mp4',
                         tmp_path / 'media', tmp_path, Event(), monotonic() + 10,
                         10_000, 5000, lambda a, b: None)


def test_mocked_download_cancellation(downloader_offline, tmp_path, monkeypatch):
    d = downloader_offline
    from threading import Event
    from time import monotonic
    cancel = Event(); cancel.set()
    monkeypatch.setattr(d.shutil, 'which', lambda _: '/bin/ffmpeg')
    with pytest.raises(d.CancelledError):
        d.download_video(f'https://www.youtube.com/watch?v={VID}', 'mp3',
                         tmp_path / 'media', tmp_path, cancel, monotonic() + 10,
                         10_000, 5000, lambda a, b: None)


def test_two_simultaneous_tasks_keep_separate_directories(downloader_offline, tmp_path, monkeypatch):
    """Simula dois yt-dlp em threads, validando isolamento dos arquivos."""
    d = downloader_offline
    class FakeYDL:
        def __init__(self, options): self.options = options
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def extract_info(self, url, download):
            folder = Path(self.options['outtmpl']).parent
            name = folder.name
            (folder / f'{name}.mp3').write_bytes(name.encode())
    monkeypatch.setattr(d.yt_dlp, 'YoutubeDL', FakeYDL, raising=False)
    monkeypatch.setattr(d.shutil, 'which', lambda _: '/bin/ffmpeg')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic
    def work(n):
        root = tmp_path / ('job_' + n)
        root.mkdir()
        return d.download_video('https://www.youtube.com/watch?v=' + VID, 'mp3',
                                root / ('video_' + n), root, Event(), monotonic()+10,
                                100000, 100000, lambda a,b: None)
    with ThreadPoolExecutor(max_workers=2) as executor:
        files = list(executor.map(work, ['1', '2']))
    assert files[0].parent.parent != files[1].parent.parent
    assert files[0].read_bytes() != files[1].read_bytes()


def test_expired_deadline_rejected(downloader_offline, tmp_path, monkeypatch):
    d = downloader_offline
    monkeypatch.setattr(d.shutil, 'which', lambda _: '/bin/ffmpeg')
    from threading import Event
    from time import monotonic
    with pytest.raises(d.ResourceLimitError):
        d.download_video('https://www.youtube.com/watch?v=' + VID, 'mp3',
                         tmp_path / 'video', tmp_path, Event(), monotonic() - 1,
                         100000, 100000, lambda a, b: None)
