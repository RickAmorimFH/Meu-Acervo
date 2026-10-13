FROM python:3.12-slim
# Runtime JS requerido pelas versões recentes do yt-dlp para desafios do YouTube.
COPY --from=denoland/deno:bin-2.9.7 /deno /usr/local/bin/deno
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_HOST=0.0.0.0 ACERVO_PUBLIC_MODE=1 APP_PORT=8000
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt
COPY app.py downloader.py ./
COPY templates ./templates
COPY static ./static
RUN mkdir -p /data && chown -R nobody:nogroup /data /app
USER nobody
ENV ACERVO_STORAGE=/data DENO_DIR=/tmp/deno
EXPOSE 8000
# IMPORTANTE: 1 worker: fila/estado da tarefa vivem na memoria do processo.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "120", "app:app"]
