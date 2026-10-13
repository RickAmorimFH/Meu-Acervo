"""Links YouTube estritos e processamento isolado por vídeo com yt-dlp."""
from __future__ import annotations

import re
import shutil
import time
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yt_dlp

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
MAX_LINKS = 10


class UserInputError(ValueError):
    pass


class CancelledError(Exception):
    pass


class ResourceLimitError(Exception):
    pass


def normalize_link(link: str) -> tuple[str, str]:
    """Retorna (ID, URL canônica). Nunca entrega URLs arbitrárias ao extrator."""
    if len(link) > 500 or any(ord(ch) < 32 for ch in link):
        raise UserInputError("Endereço inválido ou muito longo.")
    try:
        url = urlsplit(link)
        if url.scheme.lower() != "https" or (url.hostname or "").lower() not in ALLOWED_HOSTS:
            raise UserInputError("Use links HTTPS do YouTube.")
        if url.username or url.password or url.port is not None:
            raise UserInputError("Endereço com usuário ou porta não é permitido.")
        path = url.path.rstrip("/")
        if url.hostname.lower() == "youtu.be":
            video_id = path.lstrip("/")
        elif path == "/watch":
            ids = parse_qs(url.query, keep_blank_values=True).get("v", [])
            if len(ids) != 1:
                raise UserInputError("Falta o identificador do vídeo.")
            video_id = ids[0]
        elif path.startswith(("/shorts/", "/live/")):
            video_id = path.split("/")[-1] if path.count("/") == 2 else ""
        else:
            raise UserInputError("Use o link direto de um vídeo, Short ou transmissão publicada.")
        if not VIDEO_ID.fullmatch(video_id):
            raise UserInputError("O identificador do vídeo não é válido.")
        return video_id, f"https://www.youtube.com/watch?v={video_id}"
    except ValueError as exc:
        if isinstance(exc, UserInputError):
            raise
        raise UserInputError("Endereço inválido.") from exc


def parse_links(raw: str) -> tuple[list[dict[str, str]], int]:
    lines = [s.strip() for s in raw.splitlines() if s.strip()]
    if not 1 <= len(lines) <= MAX_LINKS:
        raise UserInputError(f"Informe de 1 a {MAX_LINKS} links, um por linha.")
    seen = set()
    videos = []
    duplicates = 0
    for n, link in enumerate(lines, 1):
        try:
            ident, url = normalize_link(link)
        except UserInputError as exc:
            raise UserInputError(f"Linha {n}: {exc}") from exc
        if ident in seen:
            duplicates += 1
            continue
        seen.add(ident)
        videos.append({"id": ident, "url": url})
    return videos, duplicates


def safe_filename(name: str, limit: int = 130) -> str:
    """Base name segura para entradas ZIP, inclusive no Windows."""
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f\x7f]", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    name = name[:limit].rstrip(" .")
    return name if name not in ("", ".", "..") else "video"


def total_disk_bytes(directory: Path) -> int:
    total = 0
    for p in directory.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except FileNotFoundError:
            # Arquivos .part podem ser renomeados pelo yt-dlp/FFmpeg durante a leitura.
            continue
    return total


def error_for_user(exc: Exception) -> str:
    if isinstance(exc, CancelledError):
        return "Processamento cancelado."
    if isinstance(exc, ResourceLimitError):
        return "O vídeo ultrapassou o limite de espaço ou de tempo deste aplicativo."
    msg = str(exc).lower()
    if "ffmpeg" in msg or "ffprobe" in msg:
        return "A conversão falhou. Verifique a instalação do FFmpeg."
    if any(k in msg for k in ("private video", "private", "login required", "sign in")):
        return "Este vídeo exige acesso ou está privado."
    if any(k in msg for k in ("video unavailable", "not available", "removed", "deleted")):
        return "O vídeo está indisponível ou foi removido."
    if any(k in msg for k in ("timed out", "timeout", "429", "http error 403")):
        return "A plataforma não respondeu ou limitou a solicitação. Tente novamente depois."
    return "Não foi possível obter este vídeo. Confirme se ele ainda está disponível."


def download_video(
    url: str,
    mode: str,
    folder: Path,
    root: Path,
    cancel_event,
    deadline: float,
    max_total_bytes: int,
    max_single_bytes: int,
    progress_callback,
) -> Path:
    """Baixa um único vídeo. Limites são conferidos em callbacks reais."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("FFmpeg/FFprobe não encontrado")
    folder.mkdir(parents=True, exist_ok=False)
    latest_update = 0.0

    def check_limits() -> None:
        if cancel_event.is_set():
            raise CancelledError()
        if time.monotonic() >= deadline:
            raise ResourceLimitError("tempo esgotado")
        if total_disk_bytes(root) > max_total_bytes:
            raise ResourceLimitError("espaço total esgotado")
        if total_disk_bytes(folder) > max_single_bytes * 2:
            # Arquivos intermediários (áudio + vídeo + mux) requerem alguma folga.
            raise ResourceLimitError("espaço por vídeo esgotado")

    def progress(info: dict) -> None:
        nonlocal latest_update
        check_limits()
        state = info.get("status")
        if state == "downloading":
            downloaded = info.get("downloaded_bytes") or 0
            total = info.get("total_bytes") or info.get("total_bytes_estimate")
            if downloaded > max_single_bytes or (total and total > max_single_bytes):
                raise ResourceLimitError("arquivo grande")
            now = time.monotonic()
            if now - latest_update > 0.35:
                percent = round(100 * downloaded / total, 1) if total and total > 0 else None
                progress_callback("Baixando", percent)
                latest_update = now
        if state == "finished":
            progress_callback("Convertendo e finalizando", None)

    def postprocess(info: dict) -> None:
        check_limits()
        if info.get("status") == "started":
            progress_callback("Convertendo e finalizando", None)

    check_limits()
    opts = {
        "format": "bestaudio/best" if mode == "mp3" else "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "outtmpl": str(folder / "%(title).110B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "allowed_extractors": ["youtube"],
        "restrictfilenames": True,
        "max_filesize": max_single_bytes,
        "socket_timeout": 15,
        "retries": 1,
        "fragment_retries": 1,
        "skip_unavailable_fragments": False,
        "continuedl": False,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress],
        "postprocessor_hooks": [postprocess],
        "merge_output_format": "mp4" if mode == "mp4" else None,
        "postprocessors": (
            [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
            if mode == "mp3"
            else [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]
        ),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)
    check_limits()
    media = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == f".{mode}"]
    if not media:
        raise RuntimeError("Nenhum arquivo final encontrado")
    media.sort(key=lambda p: p.stat().st_size, reverse=True)
    result = media[0]
    if result.stat().st_size <= 0 or result.stat().st_size > max_single_bytes:
        raise ResourceLimitError("tamanho inválido")
    return result


def create_zip(paths: list[Path], destination: Path) -> None:
    """Entradas somente basenames, com prefixo numérico e sem colisões."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for index, path in enumerate(paths, 1):
            name = safe_filename(path.name)
            archive.write(path, arcname=f"{index:02d}_{name}")
