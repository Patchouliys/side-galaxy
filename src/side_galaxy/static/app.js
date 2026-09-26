const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const selected = new Set();
let token = '', boards = [], batches = [], artifacts = [], evidence = null;
let refreshing = false, uploading = false, authPrompted = false, pendingIntent = null;
const labels = {ready:'就绪',busy:'实验中',offline:'离线',quarantined:'已隔离',queued:'排队中',running:'运行中',cancelling:'取消中',succeeded:'已完成',failed:'失败',cancelled:'已取消',lost:'失联'};
const titles = {'cpu-contention':'CPU 竞争实验','memory-copy':'内存拷贝实验','kvm-affinity':'KVM 在线绑核',workload:'自定义实验'};
const active = value => ['queued','running','cancelling'].includes(value);
const status = value => `<span class="status ${esc(value)}">${esc(labels[value] || value)}</span>`;
const size = value => value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / 1048576).toFixed(1)} MiB`;
const boardName = id => boards.find(board => board.id === id)?.name || id;
const artifactName = sha => artifacts.find(artifact => artifact.sha256 === sha)?.manifest.name || '自定义实验';

async function request(path, options = {}) {
  const response = await fetch('/api' + path, {...options, headers:{...(token ? {Authorization:'Bearer ' + token} : {}), ...options.headers}});
  if (!response.ok) {
    if (response.status === 401 && !authPrompted) { authPrompted = true; $('auth-dialog').showModal(); }
    const data = await response.json().catch(() => ({}));
    const error = new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || `请求失败 (${response.status})`));
    error.status = response.status;
    throw error;
  }
  return response;
}
async function api(path, method = 'GET', body, key) {
  return (await request(path, {method, headers:{...(body !== undefined ? {'Content-Type':'application/json'} : {}), ...(key ? {'Idempotency-Key':key} : {})}, body:body !== undefined ? JSON.stringify(body) : undefined})).json();
}
function toast(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, 6000);
}
function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function download(path, name) { saveBlob(await (await request(path)).blob(), name); }
function setMarkup(id, markup) {
  // Compare source markup, since browsers normalize checked/disabled attributes.
  const element = $(id);
  if (element.renderedMarkup !== markup) { element.innerHTML = markup; element.renderedMarkup = markup; }
}

function renderBoards() {
  const query = $('search').value.toLowerCase();
  const markup = boards.filter(board => [board.name, board.board_profile, board.system_profile].join(' ').toLowerCase().includes(query)).map(board => {
    const description = board.description, cpus = description?.cpus || [], reserved = description?.reserved_cpus || [];
    return `<article class="board ${selected.has(board.id) ? 'selected' : ''}"><div class="board-top"><input type="checkbox" id="b-${esc(board.id)}" data-board="${esc(board.id)}" ${selected.has(board.id) ? 'checked' : ''} ${board.status === 'ready' ? '' : 'disabled'} aria-label="选择 ${esc(board.name)}"><label for="b-${esc(board.id)}"><span class="board-symbol" aria-hidden="true">▦</span><span class="board-name">${esc(board.name)}<small>${esc(board.board_profile)} / ${esc(board.system_profile)}</small></span></label>${status(board.status)}</div><div class="board-facts"><span class="tag ${description?.mode === 'synthetic' ? 'synthetic' : ''}">${description?.mode === 'synthetic' ? 'SIMULATED' : esc(description?.mode || '等待代理')}</span><span class="tag">${cpus.length} CORES</span><span class="tag">${esc(description?.name || '等待能力探测')}</span></div><div class="cpu-row"><span title="模块版本">${esc(description?.module_sha256?.slice(0, 12) || '未连接')}</span><div class="cores">${cpus.slice(0, 16).map(cpu => `<span class="core ${reserved.includes(cpu) ? 'reserved' : ''}" title="CPU ${cpu}${reserved.includes(cpu) ? ' 管理保留' : ''}">${cpu}</span>`).join('')}${cpus.length > 16 ? `<span class="tag">+${cpus.length - 16}</span>` : ''}</div></div></article>`;
  }).join('') || '<p class="empty">暂无匹配板卡。使用 sg enroll 注册代理。</p>';
  setMarkup('boards', markup);
  $('board-count').textContent = boards.length;
  $('selected-count').textContent = selected.size + ' 块板卡';
  updateResources();
}
function batchRows(items) {
  return items.map(batch => {
    const running = batch.runs.some(run => active(run.state));
    const state = running ? (batch.runs.some(run => run.state === 'cancelling') ? 'cancelling' : batch.runs.every(run => run.state === 'queued') ? 'queued' : 'running') : batch.runs.every(run => run.state === 'succeeded') ? 'succeeded' : batch.runs.some(run => ['failed','lost'].includes(run.state)) ? 'failed' : 'cancelled';
    const name = batch.plan.artifact_sha256 ? artifactName(batch.plan.artifact_sha256) : titles[batch.plan.template] || batch.plan.template;
    return `<article class="run-row"><span class="run-icon" aria-hidden="true">⌁</span><div class="run-label">${esc(name)}<small>${esc(batch.id.slice(0, 8))} · ${batch.runs.length} 块板卡 · ${batch.plan.duration_seconds}s · ${new Date(batch.created * 1000).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}</small></div>${status(state)}<button class="quiet" data-result="${esc(batch.id)}">日志与结果 ↗</button>${running ? `<button class="quiet" data-cancel="${esc(batch.id)}">取消</button>` : ''}</article>`;
  }).join('') || '<p class="empty">暂无实验记录。上传实验包并选择目标后发起一次实验。</p>';
}
function renderModules() {
  setMarkup('module-list', boards.map(board => `<article class="module-item"><div><h3>${esc(board.name)}</h3><p>${esc(board.system_profile)} → ${esc(board.description?.name || '等待探测')}<br><code>${esc(board.description?.module_sha256?.slice(0, 20) || '未连接')}</code><br>${esc((board.description?.capabilities || []).join(' / '))}<br>${board.reload_error ? esc(board.reload_error) : board.reload_requested > board.reload_ack ? '重载已请求，等待空闲边界' : '模块就绪'}</p></div>${status(board.status)}<button class="secondary" data-reload="${esc(board.id)}">↻ 热重载</button></article>`).join('') || '<p class="empty">连接板端代理后显示执行模块。</p>');
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    [boards, batches] = await Promise.all([api('/boards'), api('/batches')]);
    for (const id of selected) if (!boards.some(board => board.id === id && board.status === 'ready')) selected.delete(id);
    renderBoards(); renderModules();
    const online = boards.filter(board => !['offline','quarantined'].includes(board.status)), runs = batches.flatMap(batch => batch.runs);
    $('metric-online').textContent = String(online.length).padStart(2, '0');
    $('metric-total').textContent = boards.length + ' 块板卡已注册';
    $('metric-cores').textContent = String(online.reduce((count, board) => count + (board.description?.cpus.filter(cpu => !board.description.reserved_cpus.includes(cpu)).length || 0), 0)).padStart(2, '0');
    $('metric-active').textContent = String(runs.filter(run => active(run.state)).length).padStart(2, '0');
    $('metric-complete').textContent = String(runs.filter(run => run.state === 'succeeded').length).padStart(2, '0');
    $('nav-count').textContent = batches.length;
    setMarkup('recent-runs', batchRows(batches.slice(0, 4))); setMarkup('all-runs', batchRows(batches));
    $('connection').textContent = '● 控制面在线';
    const templates = [...new Set(boards.flatMap(board => board.description?.templates || []))].filter(name => name !== 'workload');
    for (const name of templates) if (![...$('template').options].some(option => option.value === name)) $('template').add(new Option(titles[name] || name, name));
    if ($('result-dialog').open && evidence?.runs.some(run => active(run.state))) {
      evidence = await api('/batches/' + evidence.id); renderResult();
    }
  } catch (error) { $('connection').textContent = '连接待恢复'; $('feedback').textContent = error.message; }
  finally { refreshing = false; }
}

function renderArtifacts(preferred) {
  const current = preferred || $('artifact').value;
  $('artifact').innerHTML = '<option value="">选择实验包版本</option>' + artifacts.map(artifact => `<option value="${artifact.sha256}">${esc(artifact.manifest.name)} · ${artifact.sha256.slice(0, 8)}</option>`).join('');
  if (artifacts.some(artifact => artifact.sha256 === current)) $('artifact').value = current;
  $('artifact-count').textContent = artifacts.length;
  setMarkup('artifact-list', artifacts.map(artifact => `<article class="artifact-card"><div class="artifact-header"><div><h3>${esc(artifact.manifest.name)}</h3><p>${esc(artifact.manifest.description || '自定义实验包')}</p><code>SHA-256 ${artifact.sha256}</code></div><span class="tag">${size(artifact.size)}</span></div><div class="artifact-actions"><button class="secondary compact" data-use-artifact="${artifact.sha256}">使用此版本 ↗</button><button class="quiet" data-download-artifact="${artifact.sha256}">下载 ZIP</button><span class="hint">${artifact.manifest.setup?.length || 0} 个准备步骤 · ${artifact.manifest.outputs?.length || 0} 个输出</span></div><details><summary>查看实验清单</summary><pre>${esc(JSON.stringify(artifact.manifest, null, 2))}</pre></details></article>`).join('') || '<p class="empty">还没有实验包。上传 ZIP 后，板卡和 AI 可使用同一个 SHA-256 版本。</p>');
  updateArtifactSummary();
}
async function loadArtifacts(preferred) {
  try { artifacts = await api('/artifacts'); renderArtifacts(preferred); }
  catch (error) { setMarkup('artifact-list', `<p class="empty">${esc(error.message)}</p>`); }
}
function updateArtifactSummary() {
  const artifact = artifacts.find(item => item.sha256 === $('artifact').value);
  $('artifact-summary').innerHTML = artifact ? `<code>${artifact.sha256.slice(0, 12)}</code> · ${size(artifact.size)} · ${artifact.manifest.outputs?.length || 0} 个输出<span class="manifest-command">${esc(JSON.stringify(artifact.manifest.run))}</span>` : 'ZIP 中包含 experiment.json、代码及实验所需文件。';
}
async function uploadArtifact(file) {
  if (!file || uploading) return;
  if (file.size > 16 * 1024 * 1024) { toast('ZIP 压缩包不能超过 16 MiB。'); return; }
  uploading = true;
  const buttons = document.querySelectorAll('[data-upload]');
  buttons.forEach(button => { button.disabled = true; button.dataset.label = button.textContent; button.textContent = '上传中…'; });
  try {
    const artifact = await (await request('/artifacts', {method:'POST',headers:{'Content-Type':'application/zip'},body:file})).json();
    artifacts = [artifact, ...artifacts.filter(item => item.sha256 !== artifact.sha256)];
    renderArtifacts(artifact.sha256); $('source').value = 'artifact'; updateSource();
    toast('已保存 ' + artifact.manifest.name + ' · ' + artifact.sha256.slice(0, 12));
  } catch (error) { toast(error.message); }
  finally { uploading = false; buttons.forEach(button => { button.disabled = false; button.textContent = button.dataset.label; }); $('artifact-file').value = ''; }
}
function updateSource() {
  const custom = $('source').value === 'artifact';
  $('artifact-fields').hidden = !custom; $('builtin-fields').hidden = custom;
  $('duration').max = custom ? 86400 : 120;
  if (!custom && Number($('duration').value) > 120) $('duration').value = 120;
  $('noise-field').hidden = custom || $('template').value === 'kvm-affinity';
  $('noise').disabled = $('noise-field').hidden;
  updateResources();
}
function updateResources() {
  const explicit = $('memory-mode').value === 'limit';
  $('memory-field').hidden = !explicit;
  $('resource-summary').textContent = `CPU ${$('cpus').value || '—'} · ${$('duration').value || '—'} s`;
  const targets = boards.filter(board => selected.has(board.id));
  const memoryCapable = targets.filter(board => board.description?.capabilities.includes('memory-limit'));
  $('plan-note').textContent = targets.length && !memoryCapable.length ? '所选目标不支持进程内存预算；自动模式不更改 VM 内存。' : targets.length && memoryCapable.length !== targets.length ? '所选目标的内存能力不同；建议将进程实验与 VM 实验分批执行。' : '支持进程内存限制时使用 256 MiB；KVM 保持 VM 内存不变。';
}
function parseJSON(id, kind) {
  let value;
  try { value = JSON.parse($(id).value); } catch { throw new Error(`${kind}不是有效 JSON。`); }
  if (id === 'arguments' && (!Array.isArray(value) || value.some(item => typeof item !== 'string'))) throw new Error('附加参数必须是字符串数组，例如 ["--samples", "1000"]。');
  if (id === 'environment' && (!value || Array.isArray(value) || typeof value !== 'object' || Object.values(value).some(item => typeof item !== 'string'))) throw new Error('环境变量必须是字符串键值对象，例如 {"MODE": "baseline"}。');
  return value;
}
function plan() {
  const cores = id => $(id).value.trim() ? $(id).value.split(',').map(value => { if (!/^\d+$/.test(value.trim())) throw new Error('核心请用逗号分隔的非负整数。'); return Number(value.trim()); }) : [];
  if (!selected.size) throw new Error('请先选择至少一块就绪板卡。');
  const custom = $('source').value === 'artifact', memoryMode = $('memory-mode').value;
  if (custom && !$('artifact').value) throw new Error('请先上传或选择一个实验包。');
  const targets = boards.filter(board => selected.has(board.id));
  const memory = memoryMode === 'none' || memoryMode === 'auto' && targets.some(board => !board.description?.capabilities.includes('memory-limit')) ? null : memoryMode === 'auto' ? 256 : Number($('memory').value);
  return {boards:[...selected].sort(), template:custom ? 'workload' : $('template').value, cpus:cores('cpus'), interference_cpus:$('noise').disabled ? [] : cores('noise'), memory_mib:memory, duration_seconds:Number($('duration').value), bandwidth_percent:null, artifact_sha256:custom ? $('artifact').value : null, arguments:custom ? parseJSON('arguments', '附加参数') : [], environment:custom ? parseJSON('environment', '环境变量') : {}};
}
async function launch(submit) {
  $('launch').disabled = true; $('preflight').disabled = true;
  try {
    // A lost response can mean an accepted batch. Retry the original intent key first.
    if (submit && pendingIntent) {
      const batch = await api('/batches', 'POST', pendingIntent.payload, pendingIntent.key);
      pendingIntent = null; $('feedback').textContent = '已确认实验批次 ' + batch.id.slice(0, 8); await refresh(); return;
    }
    const payload = plan(), check = await api('/preflight', 'POST', payload);
    if (!check.valid) throw new Error(check.errors.map(error => `${boardName(error.board_id || error.board || '')}：${error.reasons.join('；')}`).join(' / '));
    $('feedback').textContent = `预检通过 · ${check.targets.length} 块板卡 · ${check.plan_sha256.slice(0, 12)}`;
    if (submit) {
      pendingIntent = {payload, key:crypto.randomUUID()};
      const batch = await api('/batches', 'POST', payload, pendingIntent.key); pendingIntent = null;
      $('feedback').textContent = '实验已提交 · ' + batch.id.slice(0, 8); toast('已提交，共 ' + batch.runs.length + ' 个目标'); await refresh();
    }
  } catch (error) {
    if (error.status >= 400 && error.status < 500 && ![408,429].includes(error.status)) pendingIntent = null;
    $('feedback').textContent = error.message + (pendingIntent ? '；点击“确认上次提交”安全重试同一批次。' : '');
  } finally {
    $('launch').disabled = false; $('preflight').disabled = false;
    $('launch').textContent = pendingIntent ? '确认上次提交' : '预检并运行 ↗';
  }
}
function renderResult() {
  $('result-meta').textContent = `${evidence.id} · ${evidence.runs.length} 块板卡`;
  $('result-content').textContent = JSON.stringify(evidence, null, 2);
  setMarkup('result-runs', evidence.runs.map(run => {
    const result = run.result, outputs = result?.outputs || [];
    return `<article class="result-run"><div class="section-heading"><h3>${esc(boardName(run.board_id))}</h3>${status(run.state)}</div>${result ? `<div class="result-facts"><span class="tag ${result.synthetic ? 'synthetic' : ''}">${result.synthetic ? 'SYNTHETIC · 非硬件测量' : esc(result.mode || '执行结果')}</span>${result.exit_code !== undefined ? `<span class="tag">EXIT ${esc(result.exit_code ?? '—')}</span>` : ''}${result.cleanup_ok !== undefined ? `<span class="tag">${result.cleanup_ok ? '清理已确认' : '清理待确认'}</span>` : ''}</div>${result.error ? `<p class="error-note">${esc(result.error)}</p>` : ''}${result.note ? `<p>${esc(result.note)}</p>` : ''}${result.stdout !== undefined ? `<div class="log-label">STDOUT</div><pre>${esc(result.stdout || '（无输出）')}</pre>` : ''}${result.stderr ? `<div class="log-label">STDERR</div><pre>${esc(result.stderr)}</pre>` : ''}${outputs.length ? `<div class="log-label">输出文件</div><div class="output-list">${outputs.map((output, index) => `<div class="output-file"><span>${esc(output.path)}<small>${size(output.size)} · ${esc(output.sha256?.slice(0, 12))}</small></span><button class="quiet" data-output-run="${esc(run.id)}" data-output-index="${index}" data-output-name="${esc(output.path)}">下载 ↓</button></div>`).join('')}</div>` : ''}${result.metrics || result.samples ? `<details><summary class="hint">指标数据</summary><pre>${esc(JSON.stringify(result.metrics || result.samples, null, 2))}</pre></details>` : ''}` : '<p class="result-empty">任务尚未返回结果。最终日志与文件在结束后回传。</p>'}</article>`;
  }).join(''));
}
function switchView(view) {
  if (!['overview','artifacts','experiments','modules','help'].includes(view)) return;
  for (const element of document.querySelectorAll('.view')) element.hidden = element.id !== view;
  for (const element of document.querySelectorAll('.nav')) { element.classList.toggle('active', element.dataset.view === view); element.setAttribute('aria-current', element.dataset.view === view ? 'page' : 'false'); }
  $('page-name').textContent = {overview:'工作区',artifacts:'制品库',experiments:'实验记录',modules:'模块管理',help:'接入与帮助'}[view];
  history.replaceState(null, '', '#' + view);
  if (view === 'artifacts') loadArtifacts();
}

document.addEventListener('click', async event => {
  const button = event.target.closest('button'); if (!button) return;
  try {
    if (button.dataset.view) switchView(button.dataset.view);
    if (button.hasAttribute('data-upload')) $('artifact-file').click();
    if (button.dataset.useArtifact) { $('source').value = 'artifact'; $('artifact').value = button.dataset.useArtifact; updateSource(); updateArtifactSummary(); switchView('overview'); $('arguments').focus(); }
    if (button.dataset.downloadArtifact) await download('/artifacts/' + button.dataset.downloadArtifact + '/download', 'experiment-' + button.dataset.downloadArtifact.slice(0, 12) + '.zip');
    if (button.dataset.outputRun) await download('/runs/' + encodeURIComponent(button.dataset.outputRun) + '/outputs/' + button.dataset.outputIndex, button.dataset.outputName.split('/').pop());
    if (button.dataset.cancel) { await api('/batches/' + button.dataset.cancel + '/cancel', 'POST'); toast('取消已请求，等待代理清理'); await refresh(); }
    if (button.dataset.reload) { await api('/boards/' + button.dataset.reload + '/reload', 'POST'); toast('重载已请求，将在空闲边界验证新版本'); await refresh(); }
    if (button.dataset.result) { evidence = await api('/batches/' + button.dataset.result); renderResult(); $('result-dialog').showModal(); }
  } catch (error) { toast(error.message); }
});
$('boards').addEventListener('change', event => { const id = event.target.dataset.board; if (id) { event.target.checked ? selected.add(id) : selected.delete(id); renderBoards(); } });
$('select-all').onclick = () => { const ready = boards.filter(board => board.status === 'ready'), all = ready.every(board => selected.has(board.id)); selected.clear(); if (!all) ready.forEach(board => selected.add(board.id)); renderBoards(); };
$('search').oninput = renderBoards;
$('refresh').onclick = () => { refresh(); loadArtifacts(); loadCatalog(); };
$('experiment-form').onsubmit = event => { event.preventDefault(); launch(true); };
$('preflight').onclick = () => launch(false);
$('source').onchange = updateSource;
$('template').onchange = updateSource;
$('artifact').onchange = updateArtifactSummary;
$('artifact-file').onchange = event => uploadArtifact(event.target.files[0]);
for (const id of ['memory-mode','cpus','duration']) $(id).addEventListener('input', updateResources);
$('auth-button').onclick = () => $('auth-dialog').showModal();
$('auth-close').onclick = () => $('auth-dialog').close();
$('auth-form').onsubmit = event => { event.preventDefault(); token = $('token').value; $('token').value = ''; authPrompted = false; $('auth-dialog').close(); loadCatalog(); loadArtifacts(); refresh(); };
$('result-close').onclick = () => $('result-dialog').close();
$('export').onclick = () => { if (evidence) saveBlob(new Blob([JSON.stringify(evidence, null, 2)], {type:'application/json'}), 'side-galaxy-' + evidence.id + '.json'); };
document.addEventListener('keydown', event => { if (event.key === '/' && !event.ctrlKey && !event.metaKey && !['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName) && !document.querySelector('dialog[open]')) { event.preventDefault(); switchView('overview'); $('search').focus(); } });
async function loadCatalog() {
  try { const catalog = await api('/catalog'); $('profiles').innerHTML = [...catalog.boards, ...catalog.systems].map(profile => `<article class="profile-card"><code>${esc(profile.id)}</code><h3>${esc(profile.name)}</h3><p>${esc(Array.isArray(profile.requires) ? profile.requires.join(' / ') : profile.soc || profile.requires)}</p></article>`).join(''); }
  catch (error) { $('profiles').innerHTML = `<p class="empty">${esc(error.message)}</p>`; }
}
fetch('/healthz').then(response => response.json()).then(health => { $('mode').textContent = health.demo ? 'DEMO · SYNTHETIC' : 'CONTROL PLANE'; $('evidence-note').textContent = health.demo ? '模拟设备只验证分发，不执行上传代码，不产生硬件测量。' : '执行能力以代理探测为准；请仅运行受信任的实验包。'; }).catch(() => { $('mode').textContent = 'OFFLINE'; });
updateSource(); switchView(location.hash.slice(1) || 'overview'); loadCatalog(); loadArtifacts(); refresh(); setInterval(refresh, 2000);
