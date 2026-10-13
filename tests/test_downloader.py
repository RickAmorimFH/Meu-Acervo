"""Testes reais de entrada, formatos de saída e limites, sem rede."""
from pathlib import Path
from threading import Event
from unittest.mock import Mock
import zipfile

import pytest
pytest.importorskip("yt_dlp")

from downloader import (CancelledError, ResourceLimitError, UserInputError,
                        create_zip, download_video, normalize_link, parse_links,
                        safe_filename, total_disk_bytes)

VID = "X9RjRGR0ipg"

@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}",
    f"https://m.youtube.com/watch?v={VID}&t=9",
    f"https://youtu.be/{VID}",
    f"https://youtube.com/shorts/{VID}",
    f"https://www.youtube.com/live/{VID}",
])
def test_allowed_video_links(url):
    ident, normalized = normalize_link(url)
    assert ident == VID
    assert normalized == f"https://www.youtube.com/watch?v={VID}"

@pytest.mark.parametrize("url", [
    "http://youtube.com/watch?v=X9RjRGR0ipg",
    f"https://youtube.com.evil.example/watch?v={VID}",
    f"https://youtube.com@127.0.0.1/watch?v={VID}",
    f"https://youtube.com:444/watch?v={VID}",
    "https://127.0.0.1/",
    "https://youtu.be/NOT-VIDEO-ID",
    f"https://youtube.com/playlist?list={VID}",
    f"https://youtu.be/{VID}/evil",
    "file:///etc/passwd",
    f"https://youtube.com/watch?v={VID}%0A",
])
def test_invalid_and_ssrf_urls(url):
    with pytest.raises(UserInputError):
        normalize_link(url)


def test_deduplicate_same_video_different_forms():
    links, count = parse_links(f"https://youtu.be/{VID}\nhttps://www.youtube.com/watch?v={VID}")
    assert len(links) == 1 and count == 1


def test_too_many_links():
    with pytest.raises(UserInputError):
        parse_links("\n".join([f"https://youtu.be/{i:011d}" for i in range(11)]))


def test_invalid_line_reports_index():
    with pytest.raises(UserInputError, match="Linha 2"):
        parse_links(f"https://youtu.be/{VID}\nhttps://invalid.example")


def test_safe_file_names_and_zip(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    first, second = source / "track.mp3", source / "track copy.mp3"
    first.write_bytes(b"music1")
    second.write_bytes(b"music2")
    output = tmp_path / "bundle.zip"
    create_zip([first, second], output)
    with zipfile.ZipFile(output) as z:
        assert z.namelist() == ["01_track.mp3", "02_track copy.mp3"]
        assert z.read("01_track.mp3") == b"music1"
        assert z.testzip() is None
    assert safe_filename(r"../\secret:track<>.mp4") == "__secret_track__.mp4"
    assert total_disk_bytes(source) == 12


def test_missing_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr("downloader.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="FFmpeg"):
        download_video("https://www.youtube.com/watch?v=" + VID, "mp3",
                       tmp_path / "folder", tmp_path, Event(), 99999999999, 99999, 9999, Mock())


def test_cancelled_job(monkeypatch, tmp_path):
    monkeypatch.setattr("downloader.shutil.which", lambda _: "/bin/ffmpeg")
    cancellation = Event()
    cancellation.set()
    with pytest.raises(CancelledError):
        download_video("https://www.youtube.com/watch?v=" + VID, "mp3",
                       tmp_path / "folder", tmp_path, cancellation, 99999999999, 99999, 9999, Mock())


def test_disk_limit(monkeypatch, tmp_path):
    monkeypatch.setattr("downloader.shutil.which", lambda _: "/bin/ffmpeg")
    (tmp_path / "big.bin").write_bytes(b"x" * 4096)
    with pytest.raises(ResourceLimitError):
        download_video("https://www.youtube.com/watch?v=" + VID, "mp3",
                       tmp_path / "folder", tmp_path, Event(), 99999999999, 100, 100, Mock())
