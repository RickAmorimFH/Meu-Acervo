# Meu Acervo — Recuperador de Vídeos

Site em português, responsivo e **local por padrão**, criado com Python, Flask, yt-dlp, FFmpeg e Deno. Ajuda a baixar **vídeos públicos disponíveis no YouTube que são seus ou que você tem autorização para salvar**. Não recupera vídeos excluídos, privados ou arquivos apagados do computador.

## O que o projeto oferece

- Interface mobile-first, adaptada para computador, tablet e celular, incluindo navegação por teclado e preferência por reduzir movimento.
- Até **10 links por solicitação**, com checagem de formato, validação no navegador e no servidor e remoção de repetidos por ID.
- Vídeo MP4 (imagem + som) ou áudio MP3 (qualidade de até 192 kbps conforme origem).
- **Tarefas em segundo plano**, para manter a página respondendo. Consulta periódica de status; porcentagens são mostradas **somente quando calculadas a partir dos dados reais informados pelo yt-dlp**.
- Resultado por vídeo: sucesso, falha individual ou fila. Se parte falhar, o arquivo dos demais pode ser entregue.
- Download individual ou arquivo ZIP com nomes distintos e seguros.
- Isolamento de tarefas, controles de fila e limite de tamanho, cancelamento cooperativo e exclusão de arquivos temporários.
- Proteções para sessão, autenticação opcional por chave, token CSRF, lista estrita de URLs, headers seguros e configuração via variáveis de ambiente.

## Iniciar no Windows (recomendado)

1. Instale **Python 3.11 ou superior** em https://www.python.org/downloads/ — marque **Add Python to PATH**.
2. Instale FFmpeg e FFprobe (vêm no mesmo pacote). Exemplo no PowerShell: `winget install Gyan.FFmpeg`.
3. Instale **Deno 2.3 ou superior**, necessário nas versões atuais do yt-dlp para resolver desafios JavaScript do YouTube: `winget install -e --id DenoLand.Deno`. Depois, **feche e reabra** o terminal.
4. Descompacte este projeto e abra a pasta `recuperador-videos`.
5. Dê duplo clique em **`INICIAR.bat`**. Ele verifica as ferramentas, cria `.venv`, instala as dependências e inicia o servidor.
6. Acesse <http://127.0.0.1:5000> em seu navegador.
7. Cole os links, escolha MP4 ou MP3 e clique em **Preparar meus arquivos**. Ao terminar, clique no botão verde para salvar.

Se o navegador abrir antes de o servidor terminar de iniciar, atualize a página. Para fechar o servidor, use `Ctrl+C` na janela do terminal.

### Iniciar pelo terminal (Windows, Linux ou macOS)

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
# Linux/macOS, em vez dos dois comandos acima:
# .venv/bin/python -m pip install -r requirements.txt
# .venv/bin/python app.py
```

Em Linux, `ffmpeg`, `ffprobe` e `deno` precisam estar no `PATH` (`sudo apt install ffmpeg` instala os dois primeiros). Para instalar Deno, consulte https://docs.deno.com/runtime/getting_started/installation/.

### Atualizar o yt-dlp

```powershell
.venv\Scripts\python -m pip install -U "yt-dlp[default]"
```

O pacote `yt-dlp[default]` instala também o componente `yt-dlp-ejs` necessário nos vídeos que dependem dos desafios JavaScript; o Deno é o runtime recomendado. O YouTube altera frequentemente o funcionamento de seus sistemas; alguns vídeos podem deixar de funcionar independentemente do código. Downloads sujeitos às regras da plataforma.

## Enviar para o GitHub (repositório próprio)

1. No GitHub, crie um repositório **privado** chamado `Meu-Acervo`, sem inicializar README.
2. Abra **o terminal na pasta `recuperador-videos`** (onde está `app.py`) e execute:

```bash
git init
git branch -M main
git add .
git commit -m "Meu Acervo - versão revisada"
git remote add origin https://github.com/SEU-USUARIO/Meu-Acervo.git
git push -u origin main
```

Substitua `SEU-USUARIO`. Se o repositório já existir e não estiver vazio, integre cuidadosamente as alterações antes de dar push (não use `--force` por padrão).

**Importante:** `.gitignore` evita enviar arquivos baixados, `.venv` e `.env`; **nunca** publique `SECRET_KEY`, senhas ou chaves de acesso reais no GitHub. O workflow `.github/workflows/tests.yml` testa automaticamente as alterações no GitHub Actions, onde as dependências podem ser instaladas.

## Arquitetura e APIs

- `app.py`: rotas Flask, autenticação, sessão, fila em memória, limite de usuários, status e limpeza.
- `downloader.py`: validação e normalização estrita de links, execução do yt-dlp, acompanhamento e ZIP.
- `templates/index.html`: interface com formulário, progresso e resultados.
- `static/style.css`, `static/app.js`: visual adaptável e comunicação real com a API.
- `tests/`: testes unitários e de integração (downloads simulados).
- `GET /`: interface; `POST /api/jobs`: inicia; `GET /api/jobs/<id>`: acompanha; `POST /api/jobs/<id>/cancel`: pede cancelamento; `GET /api/jobs/<id>/download`: envia arquivo ao dono da sessão.

As solicitações em processamento têm status em **memória de um único processo**. Uma reinicialização perde os status e interrompe tarefas, mas os diretórios órfãos são removidos por manutenção posterior. Evite executar o servidor com vários processos/replicas sem migrar a fila para um serviço compartilhado.

## Configurações e limites

Padrões:

| Configuração | Valor |
| --- | --- |
| Endereço local | `APP_HOST=127.0.0.1`, `APP_PORT=5000` |
| Processamentos simultâneos | 2 |
| Aguardando na fila | Até 4 |
| Tarefas ativas por sessão | 1 |
| Vídeos por solicitação | Até 10 |
| Limite de um vídeo | 750 MB |
| Ocupação máxima durante a tarefa | 1,5 GB (ver ressalva abaixo) |
| Prazo-alvo por processamento | 30 min, ver limitação de cancelamento |
| Retenção dos arquivos prontos | Até 1 hora |
| Retenção de falhas para consulta | Até 15 min |

Variáveis opcionais: `ACERVO_STORAGE`, `ACERVO_MAX_TOTAL_BYTES`, `ACERVO_MAX_VIDEO_BYTES`.

**Ressalvas sobre recursos:** os tamanhos são fiscalizados pelos callbacks do downloader e verificação de arquivos; transcodificação pelo FFmpeg pode criar arquivos intermediários entre as verificações. O prazo não é um limite rígido se uma chamada de rede ou o FFmpeg travar sem emitir callbacks. O ZIP exige espaço adicional temporário, razão pela qual há verificação antes de gerá-lo. **Use limites de CPU/memória/disco da hospedagem/contêiner para impor quotas reais.**

## Testes

Instale dependências de desenvolvimento e rode os testes completos:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Os testes simulam downloads, sem acessar YouTube. Cobrem: página inicial, autenticação/CSRF, autorização por sessão, links falsificados, formatos inválidos, duplicados, limite de dez, processamento individual, falhas parciais, ZIP, nomes, limpeza, fila, cancelamento e limites de espaço. `tests/test_offline.py` cobre a validação e ZIP sem as dependências externas.

**Não substituem** teste de downloads reais, inspeção em navegadores/dispositivos específicos, verificação de vulnerabilidades em dependências nem testes de carga.

## Modo hospedado (para uso pessoal com autenticação)

**GitHub não hospeda o backend Python; GitHub Pages e Netlify estático não executam yt-dlp/FFmpeg.** Para publicar online, use uma hospedagem que execute Python e FFmpeg com armazenamento temporário suficiente, suporte a processos longos, rede de saída e proxy HTTPS. Muitos planos gratuitos têm suspensão automática, timeout ou armazenamento efêmero.

O projeto contém um `Dockerfile` de referência com FFmpeg, Deno e **Gunicorn de um único worker**, exigindo configuração explícita de rede e autenticação. Antes de ativar o modo online:

1. Gere **duas chaves diferentes**, aleatórias, e configure-as **no ambiente do servidor** (não nos arquivos enviados ao GitHub): `SECRET_KEY` (32+ caracteres) e `MEU_ACERVO_ACCESS_KEY` (16+ caracteres). Exemplo para gerar valores: `python -c "import secrets; print(secrets.token_urlsafe(48))"` — rode duas vezes.
2. Configure `ACERVO_PUBLIC_MODE=1`, `APP_HOST=0.0.0.0` e `TRUSTED_HOSTS=seu-dominio.example`.
3. Posicione o aplicativo **atrás de um proxy HTTPS** e nunca exponha o servidor Flask de desenvolvimento diretamente. Cookies da sessão exigem HTTPS nesse modo.
4. Configure cotas no contêiner/servidor, monitoramento, política de rede de saída (egress), limite de banda e o tempo máximo de requisição do proxy. Os arquivos devem permanecer em volume privado, inacessível diretamente por URL.
5. Restrinja acesso à aplicação; não ofereça um downloader público sem controle adicional. Avalie termos de uso do YouTube e eventuais limites de IP do provedor.

Exemplo ilustrativo (primeiro configure as variáveis `SECRET_KEY` e `MEU_ACERVO_ACCESS_KEY` em seu terminal; não as salve no repositório):

```bash
docker build -t meu-acervo .
docker run --rm -p 127.0.0.1:8000:8000 \
  --cpus=2 --memory=2g --pids-limit=128 \
  -e SECRET_KEY -e MEU_ACERVO_ACCESS_KEY \
  -e TRUSTED_HOSTS=seu-dominio.example \
  -v meu_acervo_data:/data meu-acervo
```

**Observação:** este comando expõe somente a porta local `8000` da máquina anfitriã, não cria domínio nem certificado e não torna o site acessível publicamente. `TRUSTED_HOSTS` deve corresponder ao `Host` enviado pelo proxy. Uma configuração HTTPS real varia conforme o provedor.

### Segurança: limites conhecidos

- Links são **normalizados a URLs canônicas de vídeos do YouTube**, rejeitando domínios externos, credenciais, portas e páginas genéricas. Isso evita que o usuário envie diretamente `localhost` ou URLs internas ao extrator. Entretanto **yt-dlp e os servidores da plataforma realizam acessos indiretos e podem seguir redirecionamentos**: para hospedagem pública, é necessária política efetiva de saída na infraestrutura contra SSRF/redirecionamento/DNS rebinding. A validação de links sozinha não fornece garantia completa.
- Autenticação por chave compartilhada é indicada para uso pessoal, **não** para multiusuários. Não há recuperação de senha nem cadastro de contas.
- Login tem limite simples de tentativas por endereço IP em memória; para acesso público, acrescente limite no proxy e, conforme o caso, proteção antiabuso de borda.
- O cancelamento é **cooperativo** e pode demorar durante conexões externas ou FFmpeg. Não há isolamento do subprocesso a nível de sistema operacional.
- Não há armazenamento permanente de vídeos. Downloads temporários expiram e tarefas em andamento se perdem ao reiniciar o processo.
- PDFs, vídeos privados, DRM, login com cookies, download de playlists, acesso a vídeos excluídos e recuperação forense de disco **não são funcionalidades** deste sistema.

## Problemas comuns

- **"Deno não encontrado" ou problemas com desafio JavaScript**: instale Deno 2.3+ e use `yt-dlp[default]` atualizado; confira `deno --version`.
- **"FFmpeg/FFprobe não encontrado"**: verifique `ffmpeg -version` e `ffprobe -version` no terminal; feche e abra novamente após instalar.
- **Vídeo indisponível**: confirme que ele está público e acessível no navegador; o app não contorna privacidade/remoção.
- **Erro 403 / 429 da plataforma**: podem ser limites de acesso; tente mais tarde e atualize yt-dlp.
- **Sem espaço**: baixe menos vídeos e garanta espaço livre; vídeo e áudio podem gerar arquivos intermediários.
- **"Acesso negado"**: se publicou em rede, configure as variáveis do modo público e o HTTPS corretamente. Uso local funciona em `127.0.0.1`.
- **Aplicativo fecha**: mantenha o terminal aberto para o processamento e consulte a mensagem mostrada nele.

## Direitos e privacidade

Faça downloads apenas quando possuir o conteúdo ou autorização para baixá-lo e de acordo com as regras aplicáveis. Este projeto não implementa acesso a conteúdo privado, evasão de DRM nem recuperação de conteúdo excluído. Os arquivos gerados ficam na pasta local de tarefas e são removidos automaticamente após o período de retenção.
