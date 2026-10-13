"""Integração Flask (test_client) com yt-dlp simulado: nunca toca a internet."""
import time
import zipfile
from pathlib import Path

import pytest
pytest.importorskip("flask")
pytest.importorskip("yt_dlp")

import app as backend
from downloader import CancelledError

VID1, VID2 = "X9RjRGR0ipg", "HxdmliAztEc"


class ImmediateExecutor:
    def submit(self, callback, *args):
        callback(*args)


class QueueExecutor:
    def submit(self, callback, *args):
        pass


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "STORE", tmp_path)
    monkeypatch.setattr(backend, "executor", ImmediateExecutor())
    monkeypatch.setattr(backend, "jobs", {})
    monkeypatch.setattr(backend, "ACCESS_KEY", "")
    backend.app.config["TESTING"] = True
    with backend.app.test_client() as c:
        c.get("/")
        with c.session_transaction() as s:
            token = s["csrf"]
        yield c, token


def mock_download(url, mode, folder, root, cancel_event, deadline, max_total, max_single, progress):
    folder.mkdir(parents=True)
    progress("Baixando", 45.5)
    path = folder / ("Meu_video.mp3" if mode == "mp3" else "Meu_video.mp4")
    path.write_bytes(b"simulated media")
    return path


def start(c, token, links, fmt="mp4"):
    return c.post("/api/jobs", data={"links": links, "formato": fmt, "csrf_token": token})


def test_home_security_and_csrf(client):
    c, token = client
    response = c.get("/")
    assert response.status_code == 200
    assert b"Meu Acervo" in response.data
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert start(c, "bad", f"https://youtu.be/{VID1}").status_code == 403


def test_media_single_and_status(client, monkeypatch):
    c, token = client
    monkeypatch.setattr(backend, "download_video", mock_download)
    response = start(c, token, f"https://youtu.be/{VID1}")
    assert response.status_code == 202
    jid = response.json["job_id"]
    info = c.get(f"/api/jobs/{jid}")
    assert info.json["status"] == "completed"
    assert info.json["results"][0]["status"] == "completed"
    assert c.get(f"/api/jobs/{jid}/download").data == b"simulated media"


def test_duplicate_links_and_zip(client, monkeypatch):
    c, token = client
    monkeypatch.setattr(backend, "download_video", mock_download)
    response = start(c, token, f"https://youtu.be/{VID1}\nhttps://youtube.com/watch?v={VID1}\nhttps://youtu.be/{VID2}", "mp3")
    jid = response.json["job_id"]
    info = c.get(f"/api/jobs/{jid}").json
    assert info["total"] == 2 and info["duplicates"] == 1
    zipped = c.get(f"/api/jobs/{jid}/download")
    assert zipped.status_code == 200
    import io
    with zipfile.ZipFile(io.BytesIO(zipped.data)) as z:
        assert len(z.namelist()) == 2
        assert z.testzip() is None
        assert z.namelist()[0].startswith("01_")


def test_errors_for_invalid_requests(client):
    c, token = client
    bad = [
        ({"links": "https://bad.example", "formato": "mp3"}, 400),
        ({"links": f"https://youtu.be/{VID1}", "formato": "exe"}, 400),
        ({"links": "", "formato": "mp4"}, 400),
    ]
    for data, expected in bad:
        data["csrf_token"] = token
        assert c.post("/api/jobs", data=data).status_code == expected


def test_partial_failures_keep_valid_files(client, monkeypatch):
    c, token = client
    def fake(url, *args):
        if VID2 in url:
            raise RuntimeError("video unavailable")
        return mock_download(url, *args)
    monkeypatch.setattr(backend, "download_video", fake)
    jid = start(c, token, f"https://youtu.be/{VID1}\nhttps://youtu.be/{VID2}").json["job_id"]
    state = c.get(f"/api/jobs/{jid}").json
    assert state["status"] == "completed"
    assert [r["status"] for r in state["results"]] == ["completed", "error"]
    assert c.get(f"/api/jobs/{jid}/download").status_code == 200


def test_all_failures(client, monkeypatch):
    c, token = client
    def fake(*args):
        raise RuntimeError("video unavailable")
    monkeypatch.setattr(backend, "download_video", fake)
    jid = start(c, token, f"https://youtu.be/{VID1}").json["job_id"]
    assert c.get(f"/api/jobs/{jid}").json["status"] == "failed"
    assert c.get(f"/api/jobs/{jid}/download").status_code == 404


def test_ownership_across_sessions(client, monkeypatch):
    c, token = client
    monkeypatch.setattr(backend, "download_video", mock_download)
    jid = start(c, token, f"https://youtu.be/{VID1}").json["job_id"]
    with backend.app.test_client() as other:
        assert other.get(f"/api/jobs/{jid}").status_code == 404
        assert other.get(f"/api/jobs/{jid}/download").status_code == 404


def test_path_and_method_restrictions(client):
    c, token = client
    assert c.get("/api/jobs/../download").status_code == 404
    assert c.get("/api/jobs").status_code == 405
    assert c.get("/api/jobs/" + "x" * 32).status_code == 404


def test_queue_and_cancel(client, monkeypatch):
    c, token = client
    monkeypatch.setattr(backend, "executor", QueueExecutor())
    jid = start(c, token, f"https://youtu.be/{VID1}").json["job_id"]
    assert start(c, token, f"https://youtu.be/{VID2}").status_code == 409
    assert c.post(f"/api/jobs/{jid}/cancel").status_code == 403
    resp = c.post(f"/api/jobs/{jid}/cancel", headers={"X-CSRF-Token": token})
    assert resp.status_code == 200
    assert backend.jobs[jid].cancel_event.is_set()


def test_cleanup_only_expired_and_not_running(client, monkeypatch):
    c, token = client
    monkeypatch.setattr(backend, "download_video", mock_download)
    jid = start(c, token, f"https://youtu.be/{VID1}").json["job_id"]
    job = backend.jobs[jid]
    assert job.folder.exists()
    job.finished = time.time() - backend.READY_TTL - 2
    backend.cleanup(force=True)
    assert jid not in backend.jobs
    assert not job.folder.exists()


def test_reject_nonloopback_when_local(client):
    c, token = client
    response = c.get("/", environ_overrides={"REMOTE_ADDR": "192.0.2.5"})
    assert response.status_code == 403
