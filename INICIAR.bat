@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo =====================================
echo       MEU ACERVO - INICIAR
echo =====================================
where python >nul 2>&1
if errorlevel 1 (
  echo [ERRO] Python nao encontrado. Instale Python 3.11 ou superior.
  echo Marque a opcao Add Python to PATH.
  pause & exit /b 1
)
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo [ERRO] FFmpeg nao esta no PATH.
  echo Instale com: winget install Gyan.FFmpeg
  echo Feche e reabra o terminal depois de instalar.
  pause & exit /b 1
)
where ffprobe >nul 2>&1
if errorlevel 1 (
  echo [ERRO] FFprobe nao esta no PATH. Reinstale o pacote FFmpeg completo.
  pause & exit /b 1
)
where deno >nul 2>&1
if errorlevel 1 (
  echo [ERRO] Deno nao esta instalado. O YouTube exige runtime JavaScript recente.
  echo Instale com: winget install -e --id DenoLand.Deno
  echo Depois feche e abra esta janela novamente.
  pause & exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente Python isolado...
  python -m venv .venv
  if errorlevel 1 (echo [ERRO] Falha ao criar ambiente. & pause & exit /b 1)
)
echo Instalando/atualizando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERRO] Nao foi possivel instalar Flask ou yt-dlp.
  echo Verifique conexao com internet e acesso ao PyPI.
  pause & exit /b 1
)
echo.
echo Site local: http://127.0.0.1:5000
echo Para encerrar pressione Ctrl+C nesta janela.
start "" "http://127.0.0.1:5000"
".venv\Scripts\python.exe" app.py
if errorlevel 1 (echo [ERRO] Servidor encerrado inesperadamente.)
pause
endlocal
