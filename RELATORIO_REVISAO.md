# Relatório de revisão — Meu Acervo

**Data:** 12 de outubro de 2026  
**Origem:** `meu-acervo-site (1).zip` enviado pelo usuário  
**Status:** versão local revisada com base de hospedagem restrita; **implantação pública e downloads reais NÃO validados**.

## Auditoria do projeto original

Foram inspecionados `app.py`, `templates/index.html`, `static/style.css`, `requirements.txt`, `README.md` e `INICIAR.bat` presentes no ZIP. Foram identificados:

1. `POST /baixar` síncrono: um download longo mantinha a requisição ocupada e não havia progresso real visível.
2. Mensagens com conteúdo de exceções retornadas diretamente à tela, com possível exposição de informações internas.
3. Chave Flask com valor padrão constante e nenhuma proteção explícita contra CSRF.
4. Armazenamento por pasta de tarefa existente, porém sem associação do arquivo a uma sessão autenticada nem limpeza de arquivos de tarefas imediatamente após falha do último arquivo.
5. Verificação de limite tardia: `max_filesize` por mídia não garantia o volume total de intermediários; ZIP poderia duplicar uso do disco.
6. Falhas individuais não eram apresentadas separadamente e o resultado não mostrava os links bem-sucedidos.
7. Falta de limite de tarefas paralelas, fila, cancelamento e controle por sessão.
8. Interface básica com responsividade inicial, sem tratamento de andamento por arquivo, validação em tempo real, foco e avisos detalhados.
9. Execução local sem isolamento em `.venv`, sem Deno/EJS e sem verificação suficiente dos pré-requisitos atuais.
10. Nenhuma suíte de testes ou pipeline de CI no projeto original.

## Implementação realizada

- Separação entre servidor (`app.py`) e lógica de download (`downloader.py`).
- Validação estrita de URLs `https` YouTube de vídeo individual e normalização para link canônico com ID de 11 caracteres. Entrada malformada, domínio parecido, porta e credenciais são rejeitados. **Isso não é isolamento absoluto da rede: veja os riscos abaixo.**
- Gestão de tarefas com dois workers de threads, até quatro tarefas em espera e uma tarefa ativa por sessão.
- Status por vídeo consultado em API; progresso do `yt-dlp` apenas com dados fornecidos pelo downloader.
- Cancelamento cooperativo e gerenciamento de exceções com mensagens seguras para a interface.
- Pasta única por tarefa, produção de MP3 ou MP4, limpeza de arquivos com falhas, nomes seguros com índices em arquivos ZIP, exclusão de tarefas expiradas.
- Sessão Flask gerada com chave aleatória local (ou configurada externamente para hospedagem), CSRF em POST, checagem de posse das tarefas e autenticação por chave configurável.
- Restrição de acesso local a loopback, checagem de `TRUSTED_HOSTS` quando exposto, cookies e cabeçalhos de segurança, exigência de HTTPS para rede.
- Interface reorganizada com foco no uso por celular, estados de botões, validação e avisos, acompanhamento, ZIP e possibilidade de cancelamento.
- Instruções e iniciador Windows atualizados; `requirements.txt` usa `yt-dlp[default]` para incluir EJS, exigindo Deno.
- Arquivos de CI, Dockerfile de referência, `.gitignore`, `.env.example` e testes.

## Testes efetivamente executados neste ambiente

Comandos:

```text
python -m compileall -q app.py downloader.py tests
node --check static/app.js
python -m pytest -q
```

**Resultado:** 10 testes aprovados; 2 módulos de testes ignorados na coleta por falta de `flask` e `yt_dlp` neste ambiente. Esses módulos contêm testes adicionais de rotas, proteção entre sessões, ZIP, limites, formatos, limpeza, cancelamento e falhas parciais. Eles devem ser executados com as dependências instaladas.

Os dez testes efetivamente executados cobrem normalização, rejeição de URLs maliciosas, limite de links, tratamento de duplicatas e linhas inválidas, geração/validação de ZIP e nomes, simulações de opções e callbacks do `yt-dlp` para MP4 e MP3, limite por progresso, cancelamento, prazo excedido e isolamento de tarefas simultâneas. A sintaxe Python e JavaScript foi validada. Os testes são sem rede e não comprovam compatibilidade de download com o YouTube.

**Não executado aqui:** inicialização efetiva do Flask, instalação de dependências Python, `docker build`, testes HTTP completos, processamento real com yt-dlp/FFmpeg/Deno, varredura de dependências vulneráveis, teste de layout em navegador real e testes de carga. A tentativa de instalação via pip falhou por falta de resolução de rede/PyPI.

## Riscos e limitações remanescentes

- **SSRF indireto:** o usuário fornece somente ID de vídeo e URL HTTPS canônica; mesmo assim o extrator pode solicitar hosts auxiliares ou seguir redirecionamentos. Uma implantação pública exige **controle de egress em nível de rede**, inclusive sobre resolução DNS, não apenas validação do texto do link.
- **Timeout/cancelamento não rígidos:** durante FFmpeg ou uma operação de rede sem callbacks, a tarefa pode demorar a interromper. Para publicar em larga escala, isole trabalho em processos com supervisor, timeout rígido, cgroups e cotas efetivas.
- **Fila e estado em memória:** apenas um processo Gunicorn/instância. Sem persistência após reiniciar, sem distribuição entre replicas e sem retomada automática.
- **Limites temporários:** arquivos intermediários podem elevar consumo de disco entre verificações; a carga real depende da duração, quantidade e formatos dos vídeos.
- **Autenticação:** chave compartilhada é apropriada para ferramenta pessoal de acesso restrito, não serviço multiusuário. Para acesso público, implementar contas individuais, limites de banda e taxa no proxy, auditoria e antiautomação.
- **Disponibilidade:** o YouTube pode limitar tráfego por IP, exigir JavaScript, alterar seus mecanismos ou indisponibilizar formatos. Os downloads não foram executados neste ambiente.
- **Hospedagem:** `Dockerfile` é uma base **não testada aqui**. Antes de publicação: executar build, configurar HTTPS reverso, domínio, `SECRET_KEY`, `MEU_ACERVO_ACCESS_KEY`, `TRUSTED_HOSTS`, armazenamento privado e cotas de infraestrutura.
- **Interface:** CSS mobile-first e atributos de acessibilidade foram aplicados, mas não houve avaliação visual real em iOS/Android/Safari/Chrome.
- **Segurança de bibliotecas:** dependências listadas com intervalos, não há auditoria CVE nem lockfile resolvido nesta entrega. Revise e fixe versões validadas antes de produção.

## Próximo passo prático

Abra a pasta em VS Code, execute `INICIAR.bat` após instalar Python, FFmpeg e Deno, e rode `python -m pytest -q` no ambiente virtual para confirmar a integração. Envie o conteúdo da pasta ao repositório GitHub. Após isso, decida entre uso local e hospedagem com HTTPS e proteção por chave.

**Referências de requisitos atuais:**
- https://github.com/yt-dlp/yt-dlp/wiki/EJS
- https://flask.palletsprojects.com/en/stable/web-security/
- https://flask.palletsprojects.com/en/stable/deploying/
