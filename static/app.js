'use strict';
(() => {
  const form = document.querySelector('#download-form');
  if (!form) return;
  const links = document.querySelector('#links');
  const count = document.querySelector('#link-count');
  const submitButton = document.querySelector('#submit-button');
  const alertBox = document.querySelector('#form-alert');
  const panel = document.querySelector('#job-panel');
  const state = document.querySelector('#job-state');
  const title = document.querySelector('#job-title');
  const stage = document.querySelector('#job-stage');
  const track = document.querySelector('#progress-track');
  const value = document.querySelector('#progress-value');
  const caption = document.querySelector('#progress-caption');
  const results = document.querySelector('#result-list');
  const downloadLink = document.querySelector('#download-link');
  const cancelButton = document.querySelector('#cancel-button');
  const csrf = form.querySelector('[name=csrf_token]').value;
  let currentJob = null;
  let timer = null;

  const lines = () => links.value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  function updateCount() {
    const number = lines().length;
    count.textContent = `${number} / 10 links`;
    count.classList.toggle('over', number > 10);
  }
  links.addEventListener('input', updateCount);

  function message(text, success = false) {
    alertBox.textContent = text;
    alertBox.classList.toggle('success', success);
    alertBox.classList.toggle('is-hidden', !text);
  }
  function validate() {
    const all = lines();
    if (!all.length || all.length > 10) return 'Informe entre 1 e 10 links, um por linha.';
    const seen = new Set();
    let duplicates = 0;
    for (let n = 0; n < all.length; n++) {
      try {
        const url = new URL(all[n]);
        const validHost = ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'].includes(url.hostname.toLowerCase());
        const parts = url.pathname.split('/').filter(Boolean);
        const videoId = url.hostname.toLowerCase() === 'youtu.be' ? (parts.length === 1 ? parts[0] : '')
          : url.pathname === '/watch' ? url.searchParams.get('v')
            : (parts.length === 2 && ['shorts', 'live'].includes(parts[0])) ? parts[1] : '';
        if (url.protocol !== 'https:' || !validHost || url.username || url.password || url.port || !/^[A-Za-z0-9_-]{11}$/.test(videoId || '')) {
          return `Linha ${n+1}: use um link HTTPS direto de um vídeo do YouTube.`;
        }
        if (seen.has(videoId)) duplicates++;
        seen.add(videoId);
      } catch (_) { return `Linha ${n+1}: o endereço informado não é válido.`; }
    }
    return duplicates ? `${duplicates} link(s) repetido(s) serão ignorados.` : '';
  }
  async function readJson(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'O servidor não respondeu como esperado.');
    return data;
  }
  function setProgress(percent) {
    const hasPercent = typeof percent === 'number' && Number.isFinite(percent) && percent >= 0;
    track.classList.toggle('indeterminate', !hasPercent);
    if (hasPercent) {
      const amount = Math.max(0, Math.min(100, percent));
      value.style.width = `${amount}%`;
      track.setAttribute('aria-valuenow', String(Math.round(amount)));
      caption.textContent = `${amount.toFixed(1).replace('.', ',')}% do arquivo atual baixado`;
    } else {
      value.style.width = '40%';
      track.removeAttribute('aria-valuenow');
      caption.textContent = 'Preparando arquivo — percentual indisponível nesta etapa.';
    }
  }
  function render(data) {
    panel.classList.remove('is-hidden');
    const complete = data.status === 'completed';
    const finished = complete || data.status === 'failed' || data.status === 'cancelled';
    title.textContent = complete ? 'Seu acervo está pronto!' : data.status === 'failed' ? 'Nem tudo saiu como esperado' : data.status === 'cancelled' ? 'Processamento cancelado' : 'Preparando seus arquivos';
    state.textContent = complete ? 'Concluído' : data.status === 'running' ? 'Processando' : data.status === 'queued' ? 'Na fila' : data.status === 'cancelled' ? 'Cancelado' : 'Falhou';
    state.className = `job-state${complete ? ' complete' : data.status === 'failed' || data.status === 'cancelled' ? ' error' : ''}`;
    stage.textContent = data.error || `${data.stage} · ${data.current} de ${data.total} vídeo(s)`;
    setProgress(data.percent);
    results.replaceChildren();
    data.results.forEach((item, index) => {
      const row = document.createElement('li');
      row.className = item.status === 'completed' ? 'done' : item.status === 'error' ? 'error' : '';
      const dot = document.createElement('span'); dot.className = 'result-dot'; dot.setAttribute('aria-hidden', 'true');
      const content = document.createElement('span');
      const id = document.createElement('span'); id.className = 'result-id'; id.textContent = `Vídeo ${index+1} · ${item.id}`;
      const summary = document.createElement('span'); summary.className = 'result-message';
      summary.textContent = item.message || (item.status === 'pending' ? 'Aguardando' : item.status === 'running' ? 'Em processamento' : 'Aguardando resultado');
      content.append(id, summary); row.append(dot, content); results.append(row);
    });
    downloadLink.classList.toggle('is-hidden', !data.can_download);
    if (data.can_download) downloadLink.href = `/api/jobs/${encodeURIComponent(data.id)}/download`;
    cancelButton.classList.toggle('is-hidden', finished);
    submitButton.disabled = !finished;
    if (finished) {
      clearTimeout(timer);
      currentJob = null;
      if (complete) {
        const failed = data.results.filter(r => r.status === 'error').length;
        message(failed ? `${failed} vídeo(s) não puderam ser obtidos. Os arquivos válidos estão disponíveis.` : 'Tudo pronto! Clique para salvar seus arquivos.', true);
      } else {
        message(data.error || 'A tarefa terminou sem arquivos para salvar.');
      }
    }
  }
  async function poll(id) {
    try {
      const result = await readJson(await fetch(`/api/jobs/${encodeURIComponent(id)}`, {cache: 'no-store'}));
      if (currentJob !== id) return;
      render(result);
      if (currentJob === id) timer = setTimeout(() => poll(id), 1300);
    } catch (err) {
      message(`${err.message} Atualize a página para tentar novamente.`);
      submitButton.disabled = false;
      cancelButton.classList.add('is-hidden');
      currentJob = null;
    }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (currentJob) return;
    const warning = validate();
    if (warning && !warning.includes('repetido(s)')) {message(warning); links.focus(); return;}
    message(warning);
    submitButton.disabled = true;
    panel.classList.remove('is-hidden');
    title.textContent = 'Enviando solicitação…';
    stage.textContent = 'Validando links';
    downloadLink.classList.add('is-hidden');
    cancelButton.classList.add('is-hidden');
    results.replaceChildren();
    setProgress(null);
    try {
      const data = await readJson(await fetch('/api/jobs', {method: 'POST', body: new FormData(form), cache: 'no-store'}));
      currentJob = data.job_id;
      cancelButton.classList.remove('is-hidden');
      poll(currentJob);
    } catch (err) {
      submitButton.disabled = false;
      panel.classList.add('is-hidden');
      message(err.message);
    }
  });
  cancelButton.addEventListener('click', async () => {
    if (!currentJob) return;
    cancelButton.disabled = true;
    try {
      await readJson(await fetch(`/api/jobs/${encodeURIComponent(currentJob)}/cancel`, {method: 'POST', headers: {'X-CSRF-Token': csrf}}));
      stage.textContent = 'Cancelamento solicitado. Finalizando a etapa atual…';
    } catch (err) {message(err.message);} finally {cancelButton.disabled = false;}
  });
  updateCount();
})();
