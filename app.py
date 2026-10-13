"""Meu Acervo: Flask + tarefas locais isoladas e progresso real do yt-dlp.

Somente para uso local por padrão. Para servir em rede, é obrigatória uma chave de
acesso e sessão segura; veja README e a seção de limitações do modo hospedado.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for

from downloader import (
    CancelledError, ResourceLimitError, UserInputError, create_zip,
    download_video, error_for_user, parse_links, safe_filename, total_disk_bytes,
)

BASE = Path(__file__).resolve().parent
STORE = Path(os.environ.get("ACERVO_STORAGE", str(BASE / "downloads"))).resolve()
STORE.mkdir(parents=True, exist_ok=True)
try:
    STORE.chmod(0o700)
except OSError:
    pass

APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
ACCESS_KEY = os.environ.get("MEU_ACERVO_ACCESS_KEY", "")
NETWORK_MODE = os.environ.get("ACERVO_PUBLIC_MODE") == "1" or APP_HOST not in ("127.0.0.1", "localhost", "::1")
if NETWORK_MODE and (len(ACCESS_KEY) < 16 or len(os.environ.get("SECRET_KEY", "")) < 32
                     or not os.environ.get("TRUSTED_HOSTS", "").strip()):
    raise RuntimeError("Acesso em rede requer MEU_ACERVO_ACCESS_KEY (16+), SECRET_KEY (32+) e TRUSTED_HOSTS.")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=8 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=NETWORK_MODE,
    PERMANENT_SESSION_LIFETIME=3600 * 4,
    SEND_FILE_MAX_AGE_DEFAULT=0,
)
if os.environ.get("TRUSTED_HOSTS"):
    app.config["TRUSTED_HOSTS"] = [h.strip() for h in os.environ["TRUSTED_HOSTS"].split(",") if h.strip()]

MAX_RUNNING = 2
MAX_PENDING = 4
MAX_BYTES = int(os.environ.get("ACERVO_MAX_TOTAL_BYTES", 1_500_000_000))
MAX_SINGLE_BYTES = int(os.environ.get("ACERVO_MAX_VIDEO_BYTES", 750_000_000))
MAX_JOB_SECONDS = 1800
READY_TTL = 3600
ERROR_TTL = 900
logger = logging.getLogger("meu_acervo")
executor = ThreadPoolExecutor(max_workers=MAX_RUNNING, thread_name_prefix="acervo")
registry_lock = threading.RLock()
jobs: dict[str, "Job"] = {}
login_attempts: dict[str, list[float]] = {}
last_cleanup = 0.0


@dataclass
class Job:
    id: str
    owner: str
    mode: str
    videos: list[dict]
    folder: Path
    duplicates: int = 0
    readers: int = 0
    status: str = "queued"
    stage: str = "Aguardando processamento"
    current: int = 0
    percent: float | None = None
    output: Path | None = None
    error: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def snapshot(self) -> dict:
        return {
            "id": self.id, "status": self.status, "stage": self.stage,
            "current": self.current, "total": len(self.videos), "percent": self.percent,
            "duplicates": self.duplicates, "error": self.error,
            "results": [{"id": item["id"], "status": item["status"],
                         "message": item.get("message", "")} for item in self.videos],
            "can_download": self.status == "completed" and self.output is not None,
        }


def owner_id() -> str:
    if "sid" not in session:
        session["sid"] = secrets.token_urlsafe(24)
    return session["sid"]


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf() -> bool:
    expected = session.get("csrf", "")
    incoming = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    return bool(expected and incoming and hmac.compare_digest(expected, incoming))


def authenticated() -> bool:
    return not ACCESS_KEY or session.get("authenticated") is True


def guard_auth():
    if not authenticated():
        abort(401)


def cleanup(force: bool = False) -> None:
    global last_cleanup
    now = time.time()
    with registry_lock:
        if not force and now - last_cleanup < 60:
            return
        last_cleanup = now
        active_folders = set()
        expired_folders = []
        for ident, job in list(jobs.items()):
            if job.status in ("queued", "running") or job.readers > 0:
                active_folders.add(job.folder)
                continue
            if job.finished and now - job.finished > (READY_TTL if job.status == "completed" else ERROR_TTL):
                expired_folders.append(job.folder)
                del jobs[ident]
            else:
                active_folders.add(job.folder)
    for folder in expired_folders:
        shutil.rmtree(folder, ignore_errors=True)
    try:
        for folder in STORE.iterdir():
            if not folder.is_dir() or folder in active_folders:
                continue
            try:
                if now - folder.stat().st_mtime > 60:
                    shutil.rmtree(folder)
            except OSError:
                logger.warning("Não foi possível remover arquivos temporários antigos")
    except OSError:
        logger.warning("Não foi possível verificar arquivos temporários")


def janitor() -> None:
    while True:
        time.sleep(60)
        cleanup(force=True)


threading.Thread(target=janitor, daemon=True, name="acervo-cleanup").start()


def error_response(message: str, status: int = 400):
    return jsonify({"error": message}), status


@app.before_request
def set_session():
    # Defesa contra exposição acidental (por exemplo, gunicorn em 0.0.0.0).
    if not NETWORK_MODE and (request.remote_addr or "") not in ("127.0.0.1", "::1"):
        abort(403)
    owner_id()
    csrf_token()
    cleanup()


@app.after_request
def headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    )
    response.headers["Cache-Control"] = (
        "public, max-age=3600" if request.endpoint == "static" else "no-store"
    )
    if NETWORK_MODE:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.errorhandler(413)
def too_large(_):
    return error_response("Formulário excedeu o limite permitido.", 413)


@app.errorhandler(401)
def unauthorized(_):
    return error_response("Acesso não autorizado. Entre novamente.", 401)


@app.errorhandler(403)
def forbidden(_):
    return error_response("Acesso negado. Confira a configuração do servidor.", 403)


@app.errorhandler(404)
def missing(_):
    return error_response("Recurso não encontrado.", 404)


@app.get("/")
def index():
    return render_template("index.html", csrf_token=csrf_token(), auth_required=bool(ACCESS_KEY),
                           authenticated=authenticated(), login_error="")


@app.post("/login")
def login():
    if not ACCESS_KEY:
        return redirect(url_for("index"))
    if not check_csrf():
        return error_response("Sessão inválida. Atualize a página.", 403)
    key = request.remote_addr or "unknown"
    with registry_lock:
        recent = [t for t in login_attempts.get(key, []) if time.time() - t < 900]
        if len(recent) >= 5:
            return render_template("index.html", csrf_token=csrf_token(), auth_required=True,
                                   authenticated=False,
                                   login_error="Muitas tentativas. Tente novamente em 15 minutos."), 429
        recent.append(time.time())
        login_attempts[key] = recent
    if not hmac.compare_digest(request.form.get("access_key", ""), ACCESS_KEY):
        return render_template("index.html", csrf_token=csrf_token(), auth_required=True,
                               authenticated=False, login_error="Chave de acesso incorreta."), 401
    with registry_lock:
        login_attempts.pop(key, None)
    session.clear()
    session["authenticated"] = True
    owner_id()
    csrf_token()
    session.permanent = True
    return redirect(url_for("index"), code=303)


@app.post("/logout")
def logout():
    if not check_csrf():
        return error_response("Sessão inválida.", 403)
    session.clear()
    return redirect(url_for("index"), code=303)


def run_job(job: Job) -> None:
    outputs: list[Path] = []
    with registry_lock:
        job.status = "running"
        job.stage = "Verificando requisitos"
    try:
        deadline = time.monotonic() + MAX_JOB_SECONDS
        for index, video in enumerate(job.videos, 1):
            if job.cancel_event.is_set():
                raise CancelledError()
            with registry_lock:
                job.current = index
                job.percent = None
                job.stage = f"Preparando vídeo {index} de {len(job.videos)}"
                video["status"] = "running"
            def report(stage: str, percent: float | None):
                with registry_lock:
                    job.stage = stage
                    job.percent = percent
            try:
                video_file = download_video(
                    video["url"], job.mode, job.folder / f"video_{index:02d}",
                    job.folder, job.cancel_event, deadline, MAX_BYTES,
                    MAX_SINGLE_BYTES, report,
                )
                with registry_lock:
                    video["status"] = "completed"
                    video["message"] = "Arquivo preparado"
                outputs.append(video_file)
            except CancelledError:
                raise
            except ResourceLimitError:
                with registry_lock:
                    video["status"] = "error"
                    video["message"] = "Arquivo excedeu o limite de tamanho ou tempo."
                shutil.rmtree(job.folder / f"video_{index:02d}", ignore_errors=True)
                if time.monotonic() >= deadline or total_disk_bytes(job.folder) > MAX_BYTES:
                    raise
            except Exception as exc:
                logger.warning("Falha no vídeo %d: %s", index, type(exc).__name__)
                with registry_lock:
                    video["status"] = "error"
                    video["message"] = error_for_user(exc)
                shutil.rmtree(job.folder / f"video_{index:02d}", ignore_errors=True)
        if job.cancel_event.is_set():
            raise CancelledError()
        if not outputs:
            with registry_lock:
                job.error = "Nenhum vídeo pôde ser obtido. Confira os avisos de cada link."
                job.status = "failed"
            return
        with registry_lock:
            job.stage = "Organizando os arquivos"
            job.percent = None
        if len(outputs) == 1:
            output = outputs[0]
        else:
            # ZIP sem compactação: precisamos manter origem e destino ao mesmo tempo.
            if total_disk_bytes(job.folder) + sum(p.stat().st_size for p in outputs) > MAX_BYTES:
                raise ResourceLimitError("espaço insuficiente para gerar ZIP")
            output = job.folder / "meu_acervo.zip"
            create_zip(outputs, output)
        with registry_lock:
            job.output = output
            job.status = "completed"
            job.stage = "Arquivos prontos para salvar"
    except CancelledError:
        with registry_lock:
            job.status = "cancelled"
            job.stage = "Processamento cancelado"
            job.error = "Solicitação cancelada."
    except ResourceLimitError:
        with registry_lock:
            job.status = "failed"
            job.error = "Limite de tempo ou espaço atingido. Tente menos vídeos de cada vez."
    except Exception:
        logger.exception("Erro inesperado na tarefa")
        with registry_lock:
            job.status = "failed"
            job.error = "Ocorreu um erro inesperado. Tente novamente."
    finally:
        with registry_lock:
            job.finished = time.time()
            failed = job.status != "completed"
        if failed:
            shutil.rmtree(job.folder, ignore_errors=True)


@app.post("/api/jobs")
def create_job():
    guard_auth()
    if not check_csrf():
        return error_response("Sessão inválida. Atualize a página.", 403)
    if request.form.get("formato") not in ("mp3", "mp4"):
        return error_response("Escolha MP3 ou MP4.")
    try:
        videos, duplicates = parse_links(request.form.get("links", ""))
    except UserInputError as exc:
        return error_response(str(exc))
    owner = owner_id()
    with registry_lock:
        active = [j for j in jobs.values() if j.status in ("queued", "running")]
        if len(active) >= MAX_RUNNING + MAX_PENDING:
            return error_response("Servidor ocupado. Tente novamente em alguns minutos.", 429)
        if any(j.owner == owner for j in active):
            return error_response("Você já tem um processamento em andamento.", 409)
        ident = uuid.uuid4().hex
        folder = STORE / ident
        folder.mkdir(mode=0o700)
        job = Job(id=ident, owner=owner, mode=request.form["formato"],
                  videos=[dict(v, status="pending") for v in videos], folder=folder,
                  duplicates=duplicates)
        jobs[ident] = job
        executor.submit(run_job, job)
    return jsonify({"job_id": ident}), 202


def get_own_job(job_id: str) -> Job:
    guard_auth()
    if not (len(job_id) == 32 and all(c in "0123456789abcdef" for c in job_id)):
        abort(404)
    with registry_lock:
        job = jobs.get(job_id)
        if not job or not hmac.compare_digest(job.owner, owner_id()):
            abort(404)
        return job


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    job = get_own_job(job_id)
    with registry_lock:
        return jsonify(job.snapshot())


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    job = get_own_job(job_id)
    if not check_csrf():
        return error_response("Sessão inválida. Atualize a página.", 403)
    with registry_lock:
        if job.status in ("queued", "running"):
            job.cancel_event.set()
            job.stage = "Cancelamento solicitado"
        return jsonify(job.snapshot())


@app.get("/api/jobs/<job_id>/download")
def get_download(job_id: str):
    job = get_own_job(job_id)
    with registry_lock:
        if job.status != "completed" or job.output is None or not job.output.is_file():
            abort(404)
        output = job.output
        job.readers += 1

    def finish_download() -> None:
        with registry_lock:
            job.readers = max(0, job.readers - 1)

    try:
        response = send_file(output, as_attachment=True, download_name=safe_filename(output.name),
                             mimetype="application/zip" if output.suffix == ".zip" else "application/octet-stream",
                             conditional=True)
        response.call_on_close(finish_download)
        return response
    except Exception:
        finish_download()
        raise


if __name__ == "__main__":
    if NETWORK_MODE:
        raise RuntimeError("Não utilize o servidor Flask de desenvolvimento em rede. Use um servidor WSGI e HTTPS.")
    app.run(host=APP_HOST, port=int(os.environ.get("APP_PORT", "5000")), debug=False, threaded=True)
