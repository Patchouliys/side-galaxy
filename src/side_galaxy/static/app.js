const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const selected = new Set();
let token = '', boards = [], batches = [], artifacts = [], environments = [], labs = [], workspace = null, catalog = {boards:[],systems:[]};
const reloadRequests = new Set(), labRequests = new Set(), lifecycleErrors = new Map();
let workspaceChanging = false, workspaceRevision = 0;
let evidence = null, inspectedBoard = null, resultTab = 'logs';
let monitorData = null, monitorLoading = false, monitorLastRequest = 0, monitorError = '';
let liveLogs = null, environmentUploading = false, environmentLoading = false, environmentError = '';
let refreshing = false, uploading = false, authPrompted = false, pendingIntent = null, checkedPlan = null;
const labels = {ready:'就绪',busy:'占用',maintenance:'维护中',reloading:'重载中',offline:'离线',quarantined:'隔离',waiting:'等待资源',queued:'已分配',running:'运行中',cancelling:'取消中',succeeded:'已完成',failed:'失败',cancelled:'已取消',lost:'失联'};
const titles = {'cpu-contention':'CPU 竞争实验','memory-copy':'内存拷贝实验','kvm-affinity':'KVM 在线绑核',workload:'自定义实验'};
const modeNames = {synthetic:'模拟', 'linux-process':'Linux 进程', kvm:'KVM guest', 'qemu-environment':'离线 QEMU 环境', 'qemu-kvm':'QEMU / KVM 加速', 'qemu-hvf':'QEMU / HVF 加速', 'qemu-tcg':'QEMU / TCG 仿真'};
const capabilityNames = {'cpu-affinity':'CPU 绑核','memory-limit':'进程内存限制',interference:'干扰负载','bandwidth-limit':'带宽控制','environment-bundle':'离线环境包','workload-bundle':'实验代码包','process-tree-limits':'进程组资源限额'};
const reasonNames = {'Earlier waiting batch shares a target':'更早的排队批次需要同一目标','unknown board':'设备不存在','demo mode disabled; synthetic admission is blocked':'演示模式已关闭，不能提交到模拟设备','board restart maintenance is pending':'设备正在重启维护，等待恢复确认','module reload pending or failed; await a successful acknowledgement':'模块重载待确认或已失败，请等待成功确认后重试','board offline':'设备离线','board quarantined; verify cleanup before recovery':'设备已隔离，请确认清理后恢复','board lease occupied':'设备正在执行其他任务','CPU unavailable':'CPU 不在设备可用集合内','management CPU reserved':'使用了管理保留核','template unsupported':'执行模块不支持此实验类型','CPU affinity unsupported':'不支持 CPU affinity','module requires a memory limit':'该模块要求设置内存预算','memory limit unsupported or exceeds available budget':'内存策略不受支持或超过设备预算','hardware bandwidth control unsupported':'不支持硬件带宽控制','module does not support interferers':'不支持内置干扰负载','artifact unavailable; upload again':'制品不可用，请重新上传','Operator token required':'需要操作者令牌','Authentication required':'请提供访问令牌'};
const active = state => ['waiting','queued','running','cancelling'].includes(state);
const status = state => `<span class="status ${esc(state)}">${esc(labels[state] || state)}</span>`;
const size = value => !Number.isFinite(value) ? '—' : value < 1024 ? `${value} B` : value < 1048576 ? `${(value/1024).toFixed(1)} KiB` : `${(value/1048576).toFixed(1)} MiB`;
const memorySize = value => !Number.isFinite(value) ? '—' : value >= 1024 ? `${(value/1024).toFixed(value%1024 ? 1 : 0)} GiB` : `${value} MiB`;
const boardName = id => boards.find(board => board.id === id)?.name || id || '实验计划';
const artifactName = sha => artifacts.find(artifact => artifact.sha256 === sha)?.manifest.name || '自定义实验';
const batchName = batch => batch.plan.artifact_sha256 ? artifactName(batch.plan.artifact_sha256) : titles[batch.plan.template] || batch.plan.template;
const hostKey = board => board.physical_host_key || board.physical_host_id || board.id;
function boardState(board) {
  if (board.status==='offline') return 'offline';
  if (board.host_quarantined || board.status==='quarantined') return 'quarantined';
  if (board.host_maintenance || board.status==='maintenance') return 'maintenance';
  if (board.host_reload_pending || board.status==='reloading') return 'reloading';
  return board.host_active_run ? 'busy' : board.status;
}
const selectable = board => ['ready','busy'].includes(boardState(board));
const freeCpus = board => (board.description?.cpus || []).filter(cpu => !(board.description?.reserved_cpus || []).includes(cpu));
const modeName = mode => modeNames[mode] || mode || '未探测';
const vmMemory = info => Boolean(info?.capabilities?.includes('environment-bundle'));
const memoryCaption = info => vmMemory(info)?'虚拟机内存预算':info?.capabilities?.includes('memory-limit')?'可设置进程上限':'不支持进程上限';
const capabilityName = (cap, info) => cap==='memory-limit'&&vmMemory(info)?'虚拟机内存预算':capabilityNames[cap] || cap;
function translate(text) {
  if (reasonNames[text]) return reasonNames[text];
  return text.replace('execution environment unknown; update or reload the target module','尚未探测执行环境，请更新或重载目标模块')
    .replace(/^execution architecture mismatch: requires (.+); target (.+)$/,'CPU 架构不匹配：要求 $1，目标为 $2')
    .replace(/^execution OS mismatch: requires (.+); target (.+)$/,'操作系统不匹配：要求 $1，目标为 $2')
    .replace('required execution command missing: ','目标缺少必需命令：')
    .replace('required command not confirmed (incomplete inventory): ','命令清单不完整，尚未确认：');
}
const fullDate = value => value ? new Date(value*1000).toLocaleString('zh-CN',{hour12:false}) : '—';
function duration(seconds) { seconds=Math.max(0,Math.floor(seconds)); return seconds<60 ? `${seconds}s` : seconds<3600 ? `${Math.floor(seconds/60)}m ${seconds%60}s` : `${Math.floor(seconds/3600)}h ${Math.floor(seconds%3600/60)}m`; }
function since(value) { if (!value) return '未收到心跳'; const seconds=Math.max(0,Date.now()/1000-value); return seconds<3 ? '刚刚' : duration(seconds)+' 前'; }
function runElapsed(run) { return run.started ? duration((run.finished || Date.now()/1000)-run.started) : '未开始'; }
function batchState(batch) {
  if (batch.runs.some(run => active(run.state))) return batch.runs.some(run => run.state==='cancelling') ? 'cancelling' : batch.runs.some(run=>run.state==='running') ? 'running' : batch.runs.some(run=>run.state==='queued') ? 'queued' : 'waiting';
  return batch.runs.every(run=>run.state==='succeeded') ? 'succeeded' : batch.runs.some(run=>run.state==='lost') ? 'lost' : batch.runs.some(run=>run.state==='failed') ? 'failed' : 'cancelled';
}
function batchElapsed(batch) { const started=batch.runs.map(run=>run.started).filter(Boolean); if (!started.length) return '等待开始'; const end=batch.runs.some(run=>active(run.state)) ? Date.now()/1000 : Math.max(...batch.runs.map(run=>run.finished || run.started || batch.created)); return duration(end-Math.min(...started)); }
function setMarkup(id, markup) {
  const element=$(id); if (element.renderedMarkup===markup) return;
  const focus=element.contains(document.activeElement) ? document.activeElement.id : null;
  const opened=[...element.querySelectorAll('details[open][data-detail]')].map(detail=>detail.dataset.detail);
  element.innerHTML=markup; element.renderedMarkup=markup;
  for (const detail of element.querySelectorAll('details[data-detail]')) if (opened.includes(detail.dataset.detail)) detail.open=true;
  if (focus) $(focus)?.focus({preventScroll:true});
}
function syncSelect(id, options, firstLabel) {
  const element=$(id), current=element.value;
  const markup=`<option value="all">${esc(firstLabel)}</option>`+options.map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join('');
  if (element.optionMarkup!==markup) { element.innerHTML=markup; element.optionMarkup=markup; if (options.some(([value])=>value===current)) element.value=current; }
}
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').hidden=true,6000); }
function saveBlob(blob, filename) { const url=URL.createObjectURL(blob), link=document.createElement('a'); link.href=url; link.download=filename; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); }
async function request(path, options={}) {
  const response=await fetch('/api'+path,{...options,headers:{...(token?{Authorization:'Bearer '+token}:{}),...options.headers}});
  if (!response.ok) {
    if (response.status===401 && !authPrompted) { authPrompted=true; $('auth-dialog').showModal(); }
    const data=await response.json().catch(()=>({}));
    const detail=Array.isArray(data.detail) ? data.detail.map(item=>`${(item.loc || []).filter(part=>part!=='body').join('.')}：${item.msg}`).join('；') : data.detail;
    const error=new Error(translate(typeof detail==='string' ? detail : `请求失败 (${response.status})`)); error.status=response.status; throw error;
  }
  return response;
}
async function api(path, method='GET', body, key) { return (await request(path,{method,headers:{...(body!==undefined?{'Content-Type':'application/json'}:{}),...(key?{'Idempotency-Key':key}:{})},body:body!==undefined?JSON.stringify(body):undefined})).json(); }
async function download(path, filename) { saveBlob(await (await request(path)).blob(),filename); }
async function copy(text) { try { await navigator.clipboard.writeText(text); toast('已复制'); } catch { toast('浏览器未允许复制，请选中文本复制。'); } }

function applyWorkspace(value) {
  if (!value.demo) {
    const synthetic=new Set(boards.filter(board=>board.description?.mode==='synthetic').map(board=>board.id));
    for (const id of synthetic) selected.delete(id);
    if (evidence?.runs.length && evidence.runs.every(run=>synthetic.has(run.board_id)||run.result?.synthetic===true)) { $('result-dialog').close(); evidence=null; }
  }
  workspace=value; $('demo-toggle').checked=value.demo; $('demo-toggle').disabled=workspaceChanging;
  $('mode').textContent=value.demo?'含演示设备':'真实工作区'; $('mode').classList.toggle('demo',value.demo);
  $('mode').title=value.local_access?'仅本机访问':'令牌保护的工作区';
  $('workspace-label').textContent=value.demo?'真实设备 + 演示设备':'真实设备与实验';
}
async function toggleDemo() {
  if (!workspace || workspaceChanging) return;
  const enabled=$('demo-toggle').checked;
  if (!enabled && boards.some(board=>board.description?.mode==='synthetic'&&board.active_run) && !confirm('关闭演示设备将中断正在执行的模拟实验，并隐藏模拟设备与纯模拟记录。真实设备及实验不受影响。继续关闭？')) { $('demo-toggle').checked=workspace.demo; return; }
  workspaceChanging=true; workspaceRevision++; $('demo-toggle').disabled=true; $('mode').textContent='切换中…';
  try { applyWorkspace(await api('/workspace','PUT',{demo:enabled})); invalidateCheck(); }
  catch (error) { applyWorkspace(workspace); toast(error.message); }
  finally { workspaceChanging=false; $('demo-toggle').disabled=false; await refresh(); }
}
function reloadState(board) {
  return board.reload_error || (board.reload_requested>board.reload_ack ? '重载待确认；新任务暂停受理':'版本已确认');
}
function reloadControls(board) {
  const waiting=reloadRequests.has(board.id), blocked=waiting || boardState(board)==='maintenance';
  return `<div class="lifecycle-buttons"><button class="secondary" data-reload="${esc(board.id)}" ${blocked||board.reload_requested>board.reload_ack?'disabled':''}>${waiting?'请求中…':'空闲时重载'}</button><button class="secondary danger" data-reload="${esc(board.id)}" data-force="true" ${blocked?'disabled':''}>强制重载</button></div>`;
}
const labStages = {preparing:'准备镜像',booting:'启动系统',installing:'安装组件','starting-agent':'连接代理',ready:'代理已就绪',restarting:'正在重启','restarting-guest':'正在重启','restart-failed':'重启失败',stopped:'已停止'};
function labControls(lab) {
  const pending=labRequests.has(lab.instance_id) || lab.operation?.state==='running', error=lifecycleErrors.get('lab:'+lab.instance_id) || lab.operation?.error || (lab.operation?.state==='failed'?'重启失败，请检查实例与代理状态。':null);
  const text=pending?'正在重启，等待新系统启动并恢复代理连接…':error?String(error):lab.operation?.state==='succeeded'?'重启完成，已确认系统重新启动与代理连接。':labStages[lab.stage] || lab.stage || lab.status;
  return `<div class="lab-control"><div class="lab-state"><span class="tag ${pending?'pending':error?'failure':'success'}">${pending?'重启中':error?'操作失败':lab.status==='running'?'QEMU 运行中':esc(lab.status || '未知')}</span><code>${esc(lab.instance_id.slice(0,8))}</code></div><p class="lifecycle-note ${error?'error-text':''}" role="status">${esc(text)}</p><div class="lifecycle-buttons"><button class="secondary" data-lab-restart="${esc(lab.instance_id)}" ${pending||lab.status!=='running'?'disabled':''}>软重启 QEMU</button><button class="secondary danger" data-lab-restart="${esc(lab.instance_id)}" data-force="true" ${pending||lab.status!=='running'?'disabled':''}>强制复位</button></div></div>`;
}
function renderLabs() {
  setMarkup('managed-labs',labs.length?labs.map(lab=>`<article><h3>${esc(boardName(lab.board_id))}</h3>${labControls(lab)}</article>`).join(''):'<p class="small muted">未发现受管 QEMU 实例。现有板卡的模块操作可在设备详情中查看。</p>');
}
function renderLifecycle() { renderModules(); renderLabs(); if ($('device-dialog').open) renderDevice(); }
async function reloadBoard(id, force) {
  const board=boards.find(item=>item.id===id); if (!board || reloadRequests.has(id)) return;
  if (force && !confirm(`强制重载「${board.name}」的执行模块？当前实验将被中断，新任务需等待清理和模块版本确认。这不会重启设备操作系统。`)) return;
  reloadRequests.add(id); lifecycleErrors.delete('board:'+id); renderLifecycle();
  try { await api('/boards/'+encodeURIComponent(id)+'/reload'+(force?'?force=true':''),'POST'); toast(force?'强制重载已请求，等待实验中断、清理与模块确认':'重载已请求，将在空闲边界验证新版本'); }
  catch (error) { lifecycleErrors.set('board:'+id,error.message); toast(error.message); }
  finally { reloadRequests.delete(id); await refresh(); renderLifecycle(); }
}
async function restartLab(id, force) {
  const lab=labs.find(item=>item.instance_id===id); if (!lab || labRequests.has(id) || lab.operation?.state==='running') return;
  const name=boardName(lab.board_id);
  if (!confirm(force?`强制复位「${name}」的 QEMU guest？正在运行的实验会中断，尚未落盘的数据可能丢失。虚拟磁盘会保留，系统重新启动及代理连接确认前无法提交新实验。`:`软重启「${name}」的 QEMU guest？当前实验将中断，平台会先停止代理并清理任务，再重启系统。虚拟磁盘会保留，代理重新连接前无法提交新实验。`)) return;
  labRequests.add(id); lifecycleErrors.delete('lab:'+id); renderLifecycle();
  try { const operation=await api('/labs/'+encodeURIComponent(id)+'/restart','POST',{force}); lab.operation={id:operation.operation_id,state:operation.state}; toast('重启请求已受理，设备详情将显示恢复进度。'); }
  catch (error) { lifecycleErrors.set('lab:'+id,error.message); toast(error.message); }
  finally { labRequests.delete(id); renderLifecycle(); await refresh(); }
}

function filteredBoards() {
  const query=$('search').value.trim().toLowerCase(), filter=$('board-filter').value, mode=$('system-filter').value;
  return boards.filter(board=>(filter==='all' || filter==='selected' && selected.has(board.id) || filter===boardState(board)) && (mode==='all' || board.description?.mode===mode) && [board.id,board.name,board.board_profile,board.system_profile,board.description?.execution_environment?.architecture].join(' ').toLowerCase().includes(query));
}
function renderBoards() {
  syncSelect('system-filter',[...new Set(boards.map(board=>board.description?.mode).filter(Boolean))].sort().map(mode=>[mode,modeName(mode)]),'全部执行环境');
  const items=filteredBoards();
  setMarkup('boards',items.map(board=>{
    const info=board.description, current=batches.find(batch=>batch.runs.some(run=>run.id===(board.active_run || board.host_active_run)));
    return `<tr class="${selected.has(board.id)?'selected':''}"><td class="check-cell"><input type="checkbox" id="select-${esc(board.id)}" data-board="${esc(board.id)}" ${selected.has(board.id)?'checked':''} ${!selectable(board)&&!selected.has(board.id)?'disabled':''} aria-label="选择 ${esc(board.name)}"></td><td><button class="device-link" data-device="${esc(board.id)}">${esc(board.name)}</button><small>${esc(board.board_profile)} <span>·</span> ${esc(board.system_profile)}</small><span class="mode-label ${info?.mode==='synthetic'?'synthetic':''}">${esc(modeName(info?.mode))}${info?.execution_environment?.architecture?' · '+esc(info.execution_environment.architecture):''}</span></td><td>${status(boardState(board))}</td><td><strong class="cell-value">${freeCpus(board).length}<span> / ${info?.cpus.length || 0}</span></strong><small>可用 / 总核</small></td><td><strong class="cell-value">${memorySize(info?.memory_mib)}</strong><small>${memoryCaption(info)}</small></td><td>${current?`<button class="quiet task-link" data-result="${esc(current.id)}">${esc(current.id.slice(0,8))} ↗</button>`:'<span class="muted small">—</span>'}<small title="${esc(fullDate(board.seen))}">${esc(since(board.seen))}</small></td><td><button class="quiet" data-device="${esc(board.id)}">详情 ↗</button></td></tr>`;
  }).join('') || `<tr><td colspan="7" class="table-empty">${boards.length?'没有匹配设备，试试调整筛选条件。':'还没有设备。打开接入与帮助，注册物理板卡或启动本地 QEMU。'}</td></tr>`);
  $('board-count').textContent=boards.length; $('inventory-count').textContent=`显示 ${items.length} / ${boards.length} 台`;
  const ready=items.filter(board=>boardState(board)==='ready'); $('select-all').textContent=ready.length&&ready.every(board=>selected.has(board.id))?'取消选择当前设备':'选择当前可用设备';
  renderSelection();
}
function renderSelection() {
  const targets=[...selected].map(id=>boards.find(board=>board.id===id) || {id,name:id,status:'offline'}), available=targets.filter(board=>boardState(board)==='ready').length;
  $('selection-bar').hidden=!selected.size; $('selection-summary').textContent=`已选 ${selected.size} 台`;
  $('selection-names').textContent=targets.map(board=>board.name).join('、');
  $('selected-count').textContent=`${selected.size} 台`;
  $('target-health').textContent=selected.size ? `${available} 台就绪${targets.some(board=>boardState(board)==='busy')?` · ${targets.filter(board=>boardState(board)==='busy').length} 台占用，可排队`:''}${targets.some(board=>!selectable(board))?' · 含不可用设备':''}` : '尚未选择设备';
  setMarkup('composer-targets',boards.map(board=>`<label class="target-choice ${selected.has(board.id)?'chosen':''}"><input type="checkbox" id="target-${esc(board.id)}" data-board="${esc(board.id)}" ${selected.has(board.id)?'checked':''} ${!selectable(board)&&!selected.has(board.id)?'disabled':''}><span><b>${esc(board.name)}</b><small>${esc(modeName(board.description?.mode))} · ${freeCpus(board).length} 可用核 · ${memorySize(board.description?.memory_mib)}</small></span>${status(boardState(board))}</label>`).join('') || '<p class="empty compact-empty">连接板端代理后，在这里选择执行目标。</p>');
  updateResources();
}
function changeSelection(id, checked) {
  if (checked && !selected.has(id) && selected.size>=32) { toast('单个批次最多选择 32 台设备。'); renderBoards(); return; }
  checked?selected.add(id):selected.delete(id); invalidateCheck(); renderBoards();
  if ($('device-dialog').open) renderDevice();
}
function inspectBoard(id) { inspectedBoard=id; renderDevice(); $('device-dialog').showModal(); }
function detailRows(values) { return `<dl class="detail-grid">${values.map(([label,value])=>`<dt>${esc(label)}</dt><dd>${value}</dd>`).join('')}</dl>`; }
function renderDevice() {
  const board=boards.find(item=>item.id===inspectedBoard); if (!board) return;
  const info=board.description, env=info?.execution_environment, lab=labs.find(item=>item.board_id===board.id), profile=catalog.boards.find(item=>item.id===board.board_profile), current=batches.find(batch=>batch.runs.some(run=>run.id===(board.active_run || board.host_active_run)));
  $('device-title').textContent=board.name; $('device-subtitle').textContent=board.id;
  setMarkup('device-content',`<div class="device-actions">${status(boardState(board))}<div class="actions"><button class="secondary" data-monitor="${esc(board.id)}">查看监控</button><button class="secondary" data-toggle-device="${esc(board.id)}" ${!selectable(board)&&!selected.has(board.id)?'disabled':''}>${selected.has(board.id)?'移出执行目标':'加入执行目标'}</button>${current?`<button class="primary" data-result="${esc(current.id)}">查看当前任务</button>`:''}</div></div>${detailRows([['板型',esc(profile?.name || board.board_profile)],['物理宿主',board.physical_host_identity_known?`<code>${esc(board.physical_host_id?.slice(0,16))}</code>`:'身份未确认'],['系统配置',esc(board.system_profile)],['执行方式',esc(modeName(info?.mode))],['环境包',info?.environment_required?'必须选择离线环境包':'按实验选择'],['最后心跳',esc(fullDate(board.seen))],['内存预算',memorySize(info?.memory_mib)],['内存要求',info?.memory_limit_required?(vmMemory(info)?'必须设置虚拟机内存预算':'必须设置进程内存上限'):'按模块能力选择']])}<h3 class="detail-heading">CPU 资源 <small>可用 ${freeCpus(board).length} / 共 ${info?.cpus.length || 0}</small></h3><div class="core-grid">${(info?.cpus || []).map(cpu=>`<span class="core ${info.reserved_cpus.includes(cpu)?'reserved':''}" title="${info.reserved_cpus.includes(cpu)?'管理保留核':'可用于实验'}">${cpu}</span>`).join('') || '<span class="muted small">等待能力探测</span>'}</div><p class="hint">灰色为管理保留核；内存数值是模块上报的可配置预算。</p><h3 class="detail-heading">执行环境</h3>${env?detailRows([['操作系统',esc(env.os || '未知')],['CPU 架构',esc(env.architecture || '未知')],['命令探测',env.commands_complete?'完整清单':'部分清单']]):'<p class="small muted">代理尚未上报执行环境。</p>'}${env?.commands?.length?`<details data-detail="commands"><summary>可用命令 (${env.commands.length})</summary><div class="tag-list">${env.commands.map(command=>`<code class="tag">${esc(command)}</code>`).join('')}</div></details>`:''}<h3 class="detail-heading">能力与实验类型</h3><div class="tag-list">${(info?.capabilities || []).map(cap=>`<span class="tag" title="${esc(cap)}">${esc(capabilityName(cap,info))}</span>`).join('')}</div><div class="tag-list">${(info?.templates || []).map(template=>`<span class="tag">${esc(titles[template] || template)}</span>`).join('')}</div><h3 class="detail-heading">执行模块</h3>${detailRows([['名称',esc(info?.name || '未连接')],['版本摘要',`<code class="break-all">${esc(info?.module_sha256 || '—')}</code>`],['清理范围',esc(info?.cleanup_scope || '未上报')],['重载状态',`<span class="${board.reload_error?'error-text':''}">${esc(reloadState(board))}</span>`]])}${reloadControls(board)}${lifecycleErrors.has('board:'+board.id)?`<p class="lifecycle-note error-text" role="status">${esc(lifecycleErrors.get('board:'+board.id))}</p>`:''}${board.status==='quarantined'?`<div class="dialog-actions"><button class="secondary" data-recover="${esc(board.id)}">确认清理后恢复</button></div>`:''}${lab?`<h3 class="detail-heading">受管 QEMU 实例</h3>${labControls(lab)}`:''}`);
}

function batchRows(items) {
  return items.map(batch=>{
    const state=batchState(batch), finished=batch.runs.filter(run=>!active(run.state)).length, failed=batch.runs.filter(run=>['failed','lost'].includes(run.state)).length;
    return `<article class="run-row"><div class="run-main"><button class="run-title" data-result="${esc(batch.id)}">${esc(batchName(batch))}</button><small>${esc(batch.id.slice(0,8))} · ${esc(fullDate(batch.created))}</small><span class="run-targets">${esc(batch.runs.map(run=>boardName(run.board_id)).join('、'))}</span></div><div class="run-progress"><span>${finished} / ${batch.runs.length} 已结束${failed?` · ${failed} 失败`:''}</span><progress value="${finished}" max="${batch.runs.length}" aria-label="${finished}个目标已结束，共${batch.runs.length}个"></progress></div><div class="run-state">${status(state)}<small>${state==='waiting'?esc(queueSummary(batch)):batchElapsed(batch)}</small></div><div class="row-actions"><button class="secondary compact" data-result="${esc(batch.id)}">查看结果</button><button class="quiet" data-reuse="${esc(batch.id)}">复用</button>${active(state)?`<button class="quiet" data-cancel="${esc(batch.id)}">取消</button>`:''}</div></article>`;
  }).join('') || '<p class="empty">没有匹配的实验记录。</p>';
}
function renderHistory() {
  syncSelect('history-board',boards.map(board=>[board.id,board.name]),'全部设备');
  const query=$('history-search').value.trim().toLowerCase(), filter=$('history-filter').value, board=$('history-board').value;
  const items=batches.filter(batch=>{
    const state=batchState(batch);
    return (filter==='all' || filter==='active' && active(state) || filter==='failed' && ['failed','lost'].includes(state) || filter===state) && (board==='all' || batch.runs.some(run=>run.board_id===board)) && [batchName(batch),batch.id,batch.plan.artifact_sha256,...batch.runs.map(run=>boardName(run.board_id))].join(' ').toLowerCase().includes(query);
  });
  $('history-count').textContent=`${items.length} 个批次`; setMarkup('all-runs',batchRows(items)); setMarkup('recent-runs',batchRows(batches.slice(0,3)));
}
function renderModules() {
  setMarkup('module-list',boards.map(board=>`<article class="module-item panel"><div><button class="device-link" data-device="${esc(board.id)}">${esc(board.name)}</button><p>${esc(board.system_profile)} · ${esc(board.description?.name || '等待探测')}</p><code>${esc(board.description?.module_sha256 || '未连接')}</code><div class="tag-list">${(board.description?.capabilities || []).map(cap=>`<span class="tag">${esc(capabilityName(cap,board.description))}</span>`).join('')}</div><p class="${board.reload_error?'error-text':''}">${esc(reloadState(board))}</p>${lifecycleErrors.has('board:'+board.id)?`<p class="error-text">${esc(lifecycleErrors.get('board:'+board.id))}</p>`:''}</div>${status(boardState(board))}${reloadControls(board)}</article>`).join('') || '<p class="empty">接入设备后查看其模块。</p>');
}
function queueSummary(value) {
  const waiting=value.runs?.find(run=>run.state==='waiting') || value;
  const position=value.queue_position ?? waiting.queue_position;
  const reason=value.waiting_reason || waiting.waiting_reason;
  return `${position?`队列第 ${position} 位 · `:''}${reason?translate(String(reason)):'等待目标释放资源'}`;
}
function renderMonitorSelector() {
  syncSelect('monitor-device',boards.map(board=>[board.id,board.name+' · '+modeName(board.description?.mode)]),'选择执行目标');
  if (!boards.some(board=>board.id===$('monitor-device').value)) $('monitor-device').value=(boards.find(board=>board.description?.mode!=='synthetic') || boards[0])?.id || 'all';
}
const measured = (value, unit='', digits=1) => Number.isFinite(value)?value.toFixed(digits)+unit:'不可用';
function usedPercent(available, total) {
  return Number.isFinite(available)&&Number.isFinite(total)&&total>0&&available>=0&&available<=total ? 100*(total-available)/total : null;
}
function monitorFreshness(data, now=Date.now()/1000) {
  if (!data?.latest || data.latest.source!=='linux') return 'unavailable';
  const received=data.latest.received_at;
  return !Number.isFinite(received)||now-received>(data.stale_after_seconds || 20)?'stale':'current';
}
function trendChart(history, valueOf, label, maximum=100, gapSeconds=15) {
  const samples=(history || []).slice(-60), points=samples.map(sample=>({time:sample.received_at,value:sample.source==='linux'?valueOf(sample):null}));
  const valid=points.filter(point=>Number.isFinite(point.time)&&Number.isFinite(point.value));
  if (valid.length<2) return '<p class="chart-empty">等待至少两次有效采样</p>';
  const from=Math.min(...valid.map(point=>point.time)), to=Math.max(...valid.map(point=>point.time));
  const ceiling=Math.max(maximum,...valid.map(point=>point.value)), floor=Math.min(0,...valid.map(point=>point.value));
  const paths=[]; let segment=[], previousTime=null;
  for (const point of points) {
    if (!Number.isFinite(point.time)||!Number.isFinite(point.value)) { if(segment.length) paths.push(segment);segment=[];previousTime=null;continue; }
    if (previousTime!==null && point.time-previousTime>gapSeconds) { if(segment.length) paths.push(segment);segment=[]; }
    const x=4+(point.time-from)/Math.max(1,to-from)*292, y=84-(point.value-floor)/Math.max(1,ceiling-floor)*76;
    segment.push([x.toFixed(2),y.toFixed(2)]);previousTime=point.time;
  }
  if (segment.length) paths.push(segment);
  return `<svg class="monitor-chart" viewBox="0 0 300 90" preserveAspectRatio="none" role="img" aria-label="${esc(label)}，${valid.length} 次实测采样"><path class="chart-grid" d="M4 8H296 M4 46H296 M4 84H296"/>${paths.map(path=>path.length===1?`<circle class="chart-dot" cx="${path[0][0]}" cy="${path[0][1]}" r="2"/>`:`<path class="chart-line" d="M${path.map(point=>point.join(',')).join(' L')}"/>`).join('')}</svg><div class="chart-period"><span>${esc(new Date(from*1000).toLocaleTimeString('zh-CN',{hour12:false}))}</span><span>${esc(new Date(to*1000).toLocaleTimeString('zh-CN',{hour12:false}))}</span></div>`;
}
function renderMonitor() {
  const board=boards.find(item=>item.id===$('monitor-device').value), data=monitorData?.board_id===board?.id?monitorData:null;
  $('monitor-error').hidden=!monitorError; $('monitor-error').textContent=monitorError?'监控读取失败：'+monitorError:'';
  if (!board) {
    $('monitor-status').textContent='接入设备后查看实际采样。';
    for (const id of ['monitor-cards','monitor-host','monitor-allocations','monitor-cores']) setMarkup(id,'');
    return;
  }
  const freshness=monitorFreshness(data), sample=data?.latest?.source==='linux'?data.latest:null, history=data?.history || [];
  const age=Number.isFinite(data?.latest?.received_at)?since(data.latest.received_at):'尚未收到';
  const stateLabel=freshness==='current'?'实测数据':freshness==='stale'?'采样已过期 · 以下为最后数据':monitorLoading?'正在读取监控':'暂无可用采样';
  setMarkup('monitor-status',`${status(boardState(board))}<span class="tag ${freshness==='stale'?'failure':''}">${stateLabel}</span><span>心跳 ${esc(since(board.seen))} · 采样 ${esc(age)}</span>${data?.latest?.unavailable_reason?`<span>${esc(data.latest.unavailable_reason)}</span>`:''}`);
  const cards=[
    ['CPU 使用率',measured(sample?.cpu_percent,'%'),`频率 ${measured(sample?.cpu_frequency_mhz,' MHz',0)} · ${sample?.throttled===true?'正在限频':sample?.throttled===false?'未报告限频':'限频状态不可用'}`,item=>item.cpu_percent],
    ['温度',measured(sample?.temperature_celsius,' °C'),'板端温度传感器',item=>item.temperature_celsius],
    ['内存使用率',measured(usedPercent(sample?.memory_available_mib,sample?.memory_total_mib),'%'),`可用 ${memorySize(sample?.memory_available_mib)} / 共 ${memorySize(sample?.memory_total_mib)}`,item=>usedPercent(item.memory_available_mib,item.memory_total_mib)],
    ['磁盘使用率',measured(usedPercent(sample?.disk_available_bytes,sample?.disk_total_bytes),'%'),`可用 ${memorySize(Number.isFinite(sample?.disk_available_bytes)?sample.disk_available_bytes/1048576:null)} / 共 ${memorySize(Number.isFinite(sample?.disk_total_bytes)?sample.disk_total_bytes/1048576:null)} · 代理工作目录所在文件系统`,item=>usedPercent(item.disk_available_bytes,item.disk_total_bytes)]
  ];
  setMarkup('monitor-cards',cards.map(([label,value,note,metric])=>`<article class="panel monitor-card ${freshness==='stale'?'stale':''}"><h2>${label}</h2><strong>${esc(value)}</strong><p>${esc(note)}</p>${trendChart(history,metric,label,100,3*(data?.sample_interval_seconds || 5))}</article>`).join(''));
  const related=board.physical_host_identity_known?boards.filter(item=>hostKey(item)===hostKey(board)):[board];
  setMarkup('monitor-host',`<div class="section-heading"><h2>物理宿主与执行目标</h2><span class="tag">${board.physical_host_identity_known?'宿主身份已确认':'宿主身份未确认'}</span></div>${board.physical_host_identity_known?`<code class="break-all">${esc(board.physical_host_id || data?.physical_host_id)}</code>`:'<p class="hint">未识别的目标分别计数，不推断它们是否属于同一块板。</p>'}<div class="monitor-targets">${related.map(item=>`<button class="secondary compact" data-device="${esc(item.id)}">${esc(item.name)} · ${esc(labels[boardState(item)] || boardState(item))}</button>`).join('')}</div><p class="hint">同一物理宿主同时受理一个实验。cgroup 委派：${sample?.cgroup_available===true?'可用':sample?.cgroup_available===false?'不可用':'尚未探测'}。</p>`);
  const allocations=data?.allocations;
  setMarkup('monitor-allocations',`<div class="section-heading"><h2>当前资源分配</h2><span class="small muted">计划预算 · 与上方实测用量分别显示</span></div>${!allocations?'<p class="empty">等待资源分配信息。</p>':allocations.length?`<div class="table-scroll"><table class="allocation-table"><thead><tr><th>执行目标</th><th>状态</th><th>CPU</th><th>内存预算</th><th>实验</th></tr></thead><tbody>${allocations.map(item=>`<tr><td><button class="device-link" data-device="${esc(item.board_id)}">${esc(boardName(item.board_id))}</button></td><td>${status(item.state)}</td><td>${esc((item.cpus || []).join(', ') || '—')}${item.interference_cpus?.length?`<small>干扰 ${esc(item.interference_cpus.join(', '))}</small>`:''}</td><td>${memorySize(item.memory_mib)}${item.memory_overhead_mib?`<small>宿主额外 ${memorySize(item.memory_overhead_mib)}</small>`:''}</td><td>${item.batch_id?`<button class="quiet" data-result="${esc(item.batch_id)}">${esc(item.batch_id.slice(0,8))} ↗</button>`:`<code>${esc(item.run_id?.slice(0,8) || '—')}</code>`}</td></tr>`).join('')}</tbody></table></div>`:`<p class="empty">${board.host_quarantined?'宿主存在未确认清理，仍禁止分配新实验。':board.host_reload_pending||board.host_maintenance?'宿主正在维护或等待重载确认。':'当前没有已分配的实验。'}</p>`}`);
  setMarkup('monitor-cores',sample?.per_cpu?.length?`<div class="section-heading"><h2>各核实测</h2></div><div class="monitor-core-grid">${sample.per_cpu.slice(0,1024).map(cpu=>`<div><span>CPU ${esc(cpu.id)}</span><strong>${esc(measured(cpu.percent,'%'))}</strong><small>${esc(measured(cpu.frequency_mhz,' MHz',0))}</small></div>`).join('')}</div>`:'');
}
async function pollMonitor(force=false) {
  if (document.hidden || $('monitor').hidden || monitorLoading) return;
  const id=$('monitor-device').value;
  if (!boards.some(board=>board.id===id) || !force&&Date.now()-monitorLastRequest<5000) return;
  monitorLoading=true;monitorLastRequest=Date.now();renderMonitor();
  const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),8000);
  try {
    const data=await (await request('/boards/'+encodeURIComponent(id)+'/telemetry?limit=60',{signal:controller.signal})).json();
    if (data.board_id!==id) throw new Error('返回的监控目标不匹配');
    if ($('monitor-device').value===id) { monitorData={...data,history:(data.history || []).slice(-60)};monitorError=''; }
  } catch (error) { if ($('monitor-device').value===id) monitorError=error.name==='AbortError'?'请求超时，请重试。':error.message; }
  finally { clearTimeout(timeout);monitorLoading=false;if (!$('monitor').hidden) renderMonitor(); }
}
async function refresh() {
  if (refreshing || workspaceChanging) return; refreshing=true; const revision=workspaceRevision;
  try {
    const [mode,nextBoards,nextBatches,nextLabs]=await Promise.all([api('/workspace'),api('/boards'),api('/batches'),api('/labs')]);
    if (workspaceChanging || revision!==workspaceRevision) return;
    applyWorkspace(mode); boards=nextBoards; batches=nextBatches; labs=nextLabs.filter(lab=>lab.instance_id); renderLabs();
    // Keep unavailable selected targets visible so preflight can explain their state.
    renderBoards(); renderModules(); renderHistory();
    const ready=boards.filter(board=>boardState(board)==='ready'), availableCores=new Set(ready.flatMap(board=>freeCpus(board).map(cpu=>hostKey(board)+':'+cpu)));
    $('metric-online').textContent=ready.length; $('metric-total').textContent=`共 ${boards.length} 个执行目标`;
    $('metric-cores').textContent=availableCores.size;
    $('metric-active').textContent=new Set(boards.filter(board=>board.active_run || board.host_active_run).map(hostKey)).size;
    $('metric-attention').textContent=boards.filter(board=>['offline','quarantined','maintenance','reloading'].includes(boardState(board))).length;
    $('nav-count').textContent=batches.length; $('connection').textContent='控制面在线'; $('connection-error').hidden=true;
    $('last-refresh').textContent='更新于 '+new Date().toLocaleTimeString('zh-CN',{hour12:false})+' · 每 2 秒';
    const templates=[...new Set(boards.flatMap(board=>board.description?.templates || []))].filter(name=>name!=='workload');
    for (const name of templates) if (![...$('template').options].some(option=>option.value===name)) $('template').add(new Option(titles[name] || name,name));
    if ($('device-dialog').open) { if (boards.some(board=>board.id===inspectedBoard)) renderDevice(); else { $('device-dialog').close(); inspectedBoard=null; } }
    if ($('result-dialog').open && evidence?.runs.some(run=>active(run.state))) { evidence=await api('/batches/'+encodeURIComponent(evidence.id)); renderResult(); }
    pollLiveLogs();
    if (!$('monitor').hidden) { renderMonitorSelector(); renderMonitor(); pollMonitor(); }
  } catch (error) { $('connection').textContent='连接待恢复'; $('connection-error').textContent=error.message; $('connection-error').hidden=false; }
  finally { refreshing=false; }
}

function requirementTags(requires) {
  if (!requires) return '<span class="muted small">未声明环境要求</span>';
  return [...(requires.architectures || []),requires.os,...(requires.commands || []).map(command=>'cmd: '+command)].filter(Boolean).map(value=>`<span class="tag">${esc(value)}</span>`).join('') || '<span class="muted small">未声明环境要求</span>';
}
function renderArtifacts(preferred) {
  const current=preferred || $('artifact').value;
  $('artifact').innerHTML='<option value="">选择实验包版本</option>'+artifacts.map(artifact=>`<option value="${artifact.sha256}">${esc(artifact.manifest.name)} · ${artifact.sha256.slice(0,10)}</option>`).join('');
  if (artifacts.some(artifact=>artifact.sha256===current)) $('artifact').value=current;
  $('artifact-count').textContent=artifacts.length; renderArtifactList(); updateArtifactSummary(); renderHistory();
}
function renderArtifactList() {
  const query=$('artifact-search').value.toLowerCase();
  setMarkup('artifact-list',artifacts.filter(artifact=>[artifact.sha256,artifact.manifest.name,artifact.manifest.description].join(' ').toLowerCase().includes(query)).map(artifact=>`<article class="artifact-card panel"><div class="artifact-header"><div><h3>${esc(artifact.manifest.name)}</h3>${artifact.manifest.description?`<p>${esc(artifact.manifest.description)}</p>`:''}<code class="break-all">${artifact.sha256}</code></div><span class="tag">${size(artifact.size)}</span></div><div class="tag-list">${requirementTags(artifact.manifest.requires)}</div><pre class="command-preview">${esc(JSON.stringify(artifact.manifest.run))}</pre><div class="artifact-actions"><button class="primary compact" data-use-artifact="${artifact.sha256}">配置实验 →</button><button class="quiet" data-download-artifact="${artifact.sha256}">下载 ZIP</button><span class="small muted">${artifact.manifest.setup?.length || 0} 个准备步骤 · ${artifact.manifest.outputs?.length || 0} 个输出</span></div><details data-detail="artifact-${artifact.sha256}"><summary>完整清单</summary><pre>${esc(JSON.stringify(artifact.manifest,null,2))}</pre></details></article>`).join('') || '<p class="empty">没有匹配的实验包。上传 ZIP 后可按版本分发到设备。</p>');
}
async function loadArtifacts(preferred) { try { artifacts=await api('/artifacts'); renderArtifacts(preferred); } catch (error) { setMarkup('artifact-list',`<p class="empty">${esc(error.message)}</p>`); } }
function renderEnvironments(preferred) {
  const current=preferred ?? $('execution-environment').value;
  $('execution-environment').innerHTML='<option value="">使用目标现有系统</option>'+environments.map(item=>`<option value="${esc(item.sha256)}">${esc(item.manifest.name)} · ${esc(item.manifest.architecture)} · ${esc(item.sha256.slice(0,10))}</option>`).join('');
  if (current && !environments.some(item=>item.sha256===current)) $('execution-environment').add(new Option('环境不可用 · '+current.slice(0,12),current));
  $('execution-environment').value=current;
  renderEnvironmentSummary(); renderEnvironmentList();
}
function renderEnvironmentList() {
  $('environment-count').textContent=environmentError?'—':environments.length;
  if (environmentLoading) { setMarkup('environment-list','<p class="empty" role="status">正在读取环境包…</p>'); return; }
  if (environmentError) { setMarkup('environment-list',`<div class="notice error" role="status">环境列表读取失败：${esc(environmentError)} <button class="quiet" data-refresh-environments>重试</button></div>`); return; }
  const query=$('artifact-search').value.trim().toLowerCase();
  const items=environments.filter(item=>[item.sha256,item.manifest.name,item.manifest.architecture,...(item.manifest.runtime?.commands || [])].join(' ').toLowerCase().includes(query));
  setMarkup('environment-list',items.map(item=>`<article class="artifact-card panel"><div class="artifact-header"><div><h3>${esc(item.manifest.name)}</h3><code class="break-all">${esc(item.sha256)}</code></div><span class="tag">${size(item.size)}</span></div><div class="tag-list"><span class="tag">${esc(item.manifest.architecture)}</span><span class="tag">${esc(item.manifest.runtime?.os || 'linux')}</span><span class="tag">每次使用独立写入层</span></div><p>镜像声明的工具</p><div class="tag-list">${item.manifest.runtime?.commands?.length?item.manifest.runtime.commands.map(command=>`<code class="tag">${esc(command)}</code>`).join(''):'<span class="small muted">未声明工具清单</span>'}</div><div class="artifact-actions"><button class="primary compact" data-use-environment="${esc(item.sha256)}">使用此环境 →</button><span class="small muted">与实验代码包配合运行</span></div><details data-detail="environment-${esc(item.sha256)}"><summary>环境清单</summary><pre>${esc(JSON.stringify(item.manifest,null,2))}</pre></details></article>`).join('') || `<p class="empty">${environments.length?'没有匹配的环境包，请调整筛选条件。':'还没有环境包。上传包含系统与依赖的环境 ZIP 后，可在新建实验中选择。'}</p>`);
}
function useEnvironment(digest) {
  if (!environments.some(item=>item.sha256===digest)) { toast('环境包不可用，请刷新列表。'); return; }
  $('source').value='artifact'; renderEnvironments(digest); updateSource(); invalidateCheck(); switchView('composer');
}
function environmentStatus(message) {
  for (const id of ['environment-status','environment-upload-status']) $(id).textContent=message;
}
function renderEnvironmentSummary() {
  const digest=$('execution-environment').value, item=environments.find(value=>value.sha256===digest);
  const required=boards.some(board=>selected.has(board.id)&&board.description?.environment_required);
  $('execution-environment').required=required&&$('source').value==='artifact';
  $('execution-environment').disabled=$('source').value!=='artifact';
  if ($('execution-environment').options[0]) $('execution-environment').options[0].textContent=required?'请选择离线环境包（目标必需）':'使用目标现有系统';
  setMarkup('environment-summary',!digest?(required?'<p class="error-text small">所选目标需要离线环境包，请选择或上传准备好的环境。</p>':'<p class="hint">直接使用所选目标的系统与已安装工具。</p>'):!item?'<p class="error-text small">所选环境包不可用，请重新上传相同版本或选择其他环境。</p>':`<div class="artifact-identity"><code>${esc(item.sha256.slice(0,16))}</code><span>${size(item.size)}</span></div><div class="tag-list"><span class="tag">${esc(item.manifest.architecture)}</span><span class="tag">每次使用独立写入层</span></div><p class="hint">需要支持离线环境包的目标。系统与依赖来自准备好的镜像，实验代码单独上传。</p>`);
}
async function loadEnvironments() {
  if (environmentLoading) return;
  environmentLoading=true; environmentError=''; renderEnvironmentList();
  try { environments=await api('/environments'); renderEnvironments(); if (!environmentUploading) environmentStatus(''); }
  catch (error) { environmentError=error.message; if (!environmentUploading) environmentStatus('环境列表读取失败：'+error.message); }
  finally { environmentLoading=false; renderEnvironmentList(); }
}
async function uploadEnvironment(file) {
  if (!file || environmentUploading) return;
  environmentUploading=true; const buttons=document.querySelectorAll('[data-upload-environment]');
  buttons.forEach(button=>{button.disabled=true;button.dataset.label=button.textContent;button.textContent='上传中…';});
  environmentStatus('正在传输环境包并校验镜像，请保留此页面。');
  try {
    const item=await (await request('/environments',{method:'POST',headers:{'Content-Type':'application/zip'},body:file})).json();
    environmentError=''; environments=[item,...environments.filter(value=>value.sha256!==item.sha256)]; renderEnvironments(item.sha256); invalidateCheck();
    environmentStatus('已保存 '+item.manifest.name+' · '+size(item.size));
  } catch (error) { environmentStatus('环境上传失败：'+error.message); }
  finally { environmentUploading=false;buttons.forEach(button=>{button.disabled=false;button.textContent=button.dataset.label;});$('environment-file').value=''; }
}
function updateArtifactSummary() {
  const artifact=artifacts.find(item=>item.sha256===$('artifact').value); $('upload-zone').hidden=Boolean(artifact);
  setMarkup('artifact-summary',artifact?`<div class="artifact-identity"><code>${artifact.sha256.slice(0,16)}</code><span>${size(artifact.size)}</span></div><pre class="command-preview">${esc(JSON.stringify(artifact.manifest.run))}</pre><div class="tag-list">${requirementTags(artifact.manifest.requires)}</div><details data-detail="selected-manifest"><summary>准备步骤、默认环境与输出</summary><pre>${esc(JSON.stringify({setup:artifact.manifest.setup || [],env:artifact.manifest.env || {},outputs:artifact.manifest.outputs || []},null,2))}</pre></details>`:'');
}
async function uploadArtifact(file) {
  if (!file || uploading) return;
  if (file.size>16*1024*1024) { toast('ZIP 压缩包不能超过 16 MiB。'); return; }
  uploading=true; const buttons=document.querySelectorAll('[data-upload]'); buttons.forEach(button=>{button.disabled=true;button.dataset.label=button.textContent;button.textContent='上传中…';});
  try {
    const artifact=await (await request('/artifacts',{method:'POST',headers:{'Content-Type':'application/zip'},body:file})).json();
    artifacts=[artifact,...artifacts.filter(item=>item.sha256!==artifact.sha256)]; renderArtifacts(artifact.sha256); $('source').value='artifact'; updateSource(); invalidateCheck(); toast('已保存 '+artifact.manifest.name+' · '+artifact.sha256.slice(0,12));
  } catch (error) { toast(error.message); }
  finally { uploading=false; buttons.forEach(button=>{button.disabled=false;button.textContent=button.dataset.label;}); $('artifact-file').value=''; }
}
function updateSource() {
  const custom=$('source').value==='artifact'; $('artifact-fields').hidden=!custom; $('builtin-fields').hidden=custom; $('parameter-section').hidden=!custom; $('environment-fields').hidden=!custom;
  $('arguments').disabled=!custom; $('environment').disabled=!custom;
  $('duration').max=custom?86400:120; if (!custom && Number($('duration').value)>120) $('duration').value=120;
  $('noise-field').hidden=custom || $('template').value==='kvm-affinity'; $('noise').disabled=$('noise-field').hidden; updateResources();
}
function updateResources() {
  $('memory-field').hidden=$('memory-mode').value!=='limit'; $('memory').disabled=$('memory-field').hidden; $('resource-summary').textContent=`CPU ${$('cpus').value || '—'} · ${$('duration').value || '—'} s`;
  const targets=boards.filter(board=>selected.has(board.id)), memoryCapable=targets.filter(board=>board.description?.capabilities.includes('memory-limit'));
  const policy=$('memory-mode').value;
  const virtual=targets.filter(board=>vmMemory(board.description)), allVirtual=targets.length>0&&virtual.length===targets.length;
  const memoryKind=allVirtual?'虚拟机内存预算':virtual.length?'内存预算（虚拟机 RAM / 进程地址空间）':'进程地址空间上限';
  const limitOption=[...$('memory-mode').options].find(option=>option.value==='limit');
  if (limitOption) limitOption.textContent='指定'+(allVirtual?'虚拟机内存':virtual.length?'内存预算':'进程地址空间上限');
  $('plan-note').textContent=policy==='limit' ? `指定 ${$('memory').value || '—'} MiB ${memoryKind}。${allVirtual?'QEMU 宿主开销另计。':''}` : policy==='none' ? '不设置内存预算；要求内存预算的目标会在预检中被拒绝。' : targets.length && !memoryCapable.length ? '目标不支持设置内存预算；自动模式不设置限制，现有 VM 内存保持不变。' : targets.length && memoryCapable.length!==targets.length ? '目标的内存能力不同。请分批运行，或设置满足全部目标的策略后预检。' : `自动模式使用 256 MiB ${memoryKind}；可按实验需要调整。${allVirtual?'QEMU 宿主开销另计。':''}`;
  const overhead=[...new Set(virtual.map(board=>board.description?.memory_overhead_mib).filter(value=>Number.isFinite(value)&&value>0))];
  if (overhead.length) $('plan-note').textContent+=' 宿主额外预算：'+overhead.map(memorySize).join(' / ')+'（按目标声明）。';
  const unsupported=targets.filter(board=>!board.description?.capabilities?.includes('process-tree-limits'));
  $('resource-policy-note').textContent=$('resource-policy').value==='cgroup'?(unsupported.length?`${unsupported.map(board=>board.name).join('、')} 未上报进程组限额能力，预检将拒绝。`:'要求已委派的 cgroup CPU 与进程树内存控制。'):'优先使用已委派的进程组限额，实际生效的控制方式记录于执行结果。';
  const common=targets.length?freeCpus(targets[0]).filter(cpu=>targets.every(board=>freeCpus(board).includes(cpu))):[];
  const chosen=$('cpus').value.split(',').map(value=>Number(value.trim()));
  setMarkup('common-cpus',targets.length?`<span class="small muted">共同可用核</span><div class="core-grid">${common.map(cpu=>`<button type="button" class="core ${chosen.includes(cpu)?'picked':''}" data-cpu="${cpu}" aria-pressed="${chosen.includes(cpu)}">${cpu}</button>`).join('') || '<span class="small error-text">无共同可用 CPU，请调整目标</span>'}</div>`:'<span class="hint">选择目标后可直接点击共同可用 CPU。</span>');
  renderEnvironmentSummary();
}
function invalidateCheck() {
  if (checkedPlan) { $('preflight-state').textContent='配置已更改'; $('preflight-state').className='tag'; $('preflight-results').classList.add('stale'); }
}
function parseJSON(id, label) {
  let value; try { value=JSON.parse($(id).value); } catch { const error=new Error(label+'不是有效 JSON。'); error.field=id; throw error; }
  const invalid=id==='arguments' ? !Array.isArray(value) || value.some(item=>typeof item!=='string') : !value || Array.isArray(value) || typeof value!=='object' || Object.values(value).some(item=>typeof item!=='string');
  if (invalid) { const error=new Error(id==='arguments'?'附加参数必须是字符串数组，例如 ["--samples", "1000"]。':'环境变量必须是字符串键值对象，例如 {"MODE": "baseline"}。'); error.field=id; throw error; }
  return value;
}
function plan() {
  const cores=id=>$(id).value.trim()?$(id).value.split(',').map(value=>{if (!/^\d+$/.test(value.trim())) { const error=new Error('CPU 请用逗号分隔的非负整数。');error.field=id;throw error;}return Number(value.trim());}):[];
  if (!selected.size) throw new Error('请先选择至少一台执行目标。');
  const custom=$('source').value==='artifact', memoryMode=$('memory-mode').value;
  if (custom&&!$('artifact').value) throw new Error('请上传或选择一个实验包版本。');
  const targets=boards.filter(board=>selected.has(board.id));
  if (targets.some(board=>board.description?.environment_required)&&(!custom||!$('execution-environment').value)) {
    const error=new Error('所选目标需要实验代码包与离线环境包，请先选择两者。'); error.field=custom?'execution-environment':'source'; throw error;
  }
  const memory=memoryMode==='none' || memoryMode==='auto'&&targets.some(board=>!board.description?.capabilities.includes('memory-limit'))?null:memoryMode==='auto'?256:Number($('memory').value);
  return {boards:[...selected].sort(),template:custom?'workload':$('template').value,cpus:cores('cpus'),interference_cpus:$('noise').disabled?[]:cores('noise'),memory_mib:memory,duration_seconds:Number($('duration').value),bandwidth_percent:null,resource_policy:$('resource-policy').value || 'auto',artifact_sha256:custom?$('artifact').value:null,environment_sha256:custom?$('execution-environment').value || null:null,arguments:custom?parseJSON('arguments','附加参数'):[],environment:custom?parseJSON('environment','环境变量'):{}};
}
function renderPreflight(check, payload) {
  checkedPlan=JSON.stringify(payload); $('preflight-results').classList.remove('stale'); $('preflight-state').textContent=check.valid?'通过':'未通过'; $('preflight-state').className='tag '+(check.valid?'success':'failure');
  const errors=new Map(check.errors.map(error=>[error.board_id,error.reasons]));
  setMarkup('preflight-results',`<div class="preflight-summary">${check.valid?`全部 ${check.targets.length} 台目标可受理`:`${check.errors.reduce((count,error)=>count+error.reasons.length,0)} 项检查未通过`}</div>${check.valid&&check.waiting_reason?`<p class="hint">将排队：${esc(translate(check.waiting_reason))}</p>`:''}${errors.has(null)?`<p class="error-text small">${esc(errors.get(null).map(translate).join('；'))}</p>`:''}${payload.boards.map(id=>{const target=check.targets.find(item=>item.board_id===id), reasons=errors.get(id);return `<div class="preflight-target ${reasons?'rejected':'passed'}"><span class="check-symbol">${reasons?'!':'✓'}</span><div><strong>${esc(boardName(id))}</strong>${reasons?`<ul>${reasons.map(reason=>`<li>${esc(translate(reason))}</li>`).join('')}</ul>`:`<small>${esc(modeName(target?.mode))} · ${esc(target?.module_sha256?.slice(0,10) || '—')}</small>`}</div></div>`;}).join('')}<code class="check-hash">${esc(check.plan_sha256.slice(0,16))}</code>`);
}
async function launch(submit) {
  if (!(submit&&pendingIntent) && !$('experiment-form').reportValidity()) return;
  $('launch').disabled=true; $('preflight').disabled=true; $('feedback').textContent='';
  try {
    if (submit&&pendingIntent) { const batch=await api('/batches'+(pendingIntent.enqueue?'?enqueue=true':''),'POST',pendingIntent.payload,pendingIntent.key); pendingIntent=null; submitted(batch); await refresh(); return; }
    const payload=plan(), enqueue=$('enqueue').checked, check=await api('/preflight'+(enqueue?'?enqueue=true':''),'POST',payload); renderPreflight(check,payload);
    if (!check.valid) { $('feedback').textContent='按上方原因调整目标或配置，然后重新检查。'; return; }
    if (submit) { pendingIntent={payload,key:crypto.randomUUID(),enqueue}; const batch=await api('/batches'+(enqueue?'?enqueue=true':''),'POST',payload,pendingIntent.key); pendingIntent=null; submitted(batch); await refresh(); }
  } catch (error) {
    if (error.status>=400&&error.status<500&&![408,429].includes(error.status)) pendingIntent=null;
    $('feedback').textContent=error.message+(pendingIntent?'；请确认上次提交，安全重试同一批次。':'');
    if (error.field) { $(error.field).setCustomValidity(error.message); $(error.field).reportValidity(); }
  } finally { $('launch').disabled=false; $('preflight').disabled=false; $('launch').textContent=pendingIntent?'确认上次提交':'预检并运行 ↗'; }
}
function submitted(batch) { $('feedback').innerHTML=`<strong>已提交 ${esc(batch.id.slice(0,8))}</strong><button class="quiet" type="button" data-result="${esc(batch.id)}">查看执行状态 →</button>`; toast(batch.runs.some(run=>run.state==='waiting')?'已加入队列，等待资源':`已提交到 ${batch.runs.length} 台设备`); }
async function reuseBatch(id) {
  if (pendingIntent) { toast('请先确认上一笔提交结果，再复用其他计划。'); return; }
  const batch=await api('/batches/'+encodeURIComponent(id)), source=batch.plan;
  for (const field of $('experiment-form').querySelectorAll('input,textarea')) field.setCustomValidity('');
  if (!selected.size) source.boards.forEach(board=>selected.add(board));
  $('source').value=source.artifact_sha256?'artifact':'builtin';
  if (source.artifact_sha256&&!artifacts.some(item=>item.sha256===source.artifact_sha256)) await loadArtifacts();
  if (source.environment_sha256&&!environments.some(item=>item.sha256===source.environment_sha256)) await loadEnvironments();
  renderEnvironments(source.environment_sha256 || ''); $('artifact').value=source.artifact_sha256 || ''; $('template').value=source.template;
  if (!$('template').value && !source.artifact_sha256) { $('template').add(new Option(source.template,source.template)); $('template').value=source.template; }
  $('cpus').value=source.cpus.join(','); $('noise').value=source.interference_cpus.join(','); $('duration').value=source.duration_seconds;
  $('resource-policy').value=source.resource_policy || 'auto';
  $('memory-mode').value=source.memory_mib===null?'none':'limit'; if (source.memory_mib!==null) $('memory').value=source.memory_mib;
  $('arguments').value=JSON.stringify(source.arguments || [],null,2); $('environment').value=JSON.stringify(source.environment || {},null,2);
  $('reuse-banner').hidden=false; $('reuse-banner').textContent=`复用批次 ${batch.id.slice(0,8)} 的代码版本与参数。目标为当前所选设备，提交前会重新预检。`;
  $('feedback').textContent=''; checkedPlan=null; $('preflight-state').textContent='未检查'; $('preflight-state').className='tag'; setMarkup('preflight-results','<p class="small muted">复用计划需要重新检查目标能力和资源。</p>');
  updateSource(); updateArtifactSummary(); renderBoards(); $('result-dialog').close(); switchView('composer');
  if (source.artifact_sha256&&!$('artifact').value) { $('reuse-banner').textContent+=' 原制品不可用，请重新上传相同版本。'; }
}

async function openResult(id) { evidence=await api('/batches/'+encodeURIComponent(id)); $('result-target').value=''; $('log-search').value=''; resultTab='logs'; renderResult(); $('result-dialog').showModal(); pollLiveLogs(); }
function currentRun() { return evidence?.runs.find(run=>run.id===$('result-target').value) || evidence?.runs[0]; }
function resultLogs(filtered=true) {
  const run=currentRun(), result=run?.result;
  const stream=$('log-stream').value;
  let text=result ? (stream==='stdout'?result.stdout || '':stream==='stderr'?result.stderr || '':`${result.stdout || ''}${result.stderr?`\n[stderr]\n${result.stderr}`:''}`) : liveLogs?.runId===run?.id ? liveLogs.events.filter(event=>stream==='both'||event.stream===stream).map(event=>(stream==='both'&&event.stream!=='stdout'?`[${event.stream}] `:'')+event.text).join('') : '';
  const query=filtered?$('log-search').value.trim().toLowerCase():''; if (query) text=text.split('\n').filter(line=>line.toLowerCase().includes(query)).join('\n'); return text;
}
function renderResult() {
  const previous=$('result-target').value;
  $('result-title').textContent=batchName(evidence); $('result-meta').textContent=`${evidence.id} · ${fullDate(evidence.created)}`;
  $('result-target').innerHTML=evidence.runs.map(run=>`<option value="${esc(run.id)}">${esc(boardName(run.board_id))} · ${esc(labels[run.state] || run.state)}</option>`).join('');
  if (evidence.runs.some(run=>run.id===previous)) $('result-target').value=previous;
  const finished=evidence.runs.filter(run=>!active(run.state)).length;
  $('result-progress').textContent=`${finished} / ${evidence.runs.length} 目标已结束 · ${batchElapsed(evidence)}`;
  $('reuse-result').textContent=selected.size?`复用到已选 ${selected.size} 台`:'复用原计划'; $('result-cancel').hidden=!evidence.runs.some(run=>active(run.state));
  setMarkup('result-plan',`<span>CPU <b>${esc(evidence.plan.cpus.join(','))}</b></span><span>内存 <b>${evidence.plan.memory_mib===null?'不设置':memorySize(evidence.plan.memory_mib)}</b></span><span>时限 <b>${duration(evidence.plan.duration_seconds)}</b></span><span>资源控制 <b>${evidence.plan.resource_policy==='cgroup'?'要求 cgroup':'自动'}</b></span>${evidence.plan.environment_sha256?`<span>环境 <code>${esc(evidence.plan.environment_sha256.slice(0,12))}</code></span>`:''}${evidence.plan.artifact_sha256?`<span>制品 <code>${evidence.plan.artifact_sha256.slice(0,12)}</code></span>`:''}`);
  renderRunResult();
}
function renderRunResult() {
  const run=currentRun(); if (!run) return;
  const result=run.result, outputs=result?.outputs || [];
  setMarkup('result-run-meta',`<div class="result-run-status">${status(run.state)}<span class="small muted">${run.started?'开始 '+esc(fullDate(run.started)):'尚未开始'} · ${runElapsed(run)}</span>${result?.mode?`<span class="tag ${result.synthetic?'synthetic':''}">${esc(modeName(result.mode))}</span>`:''}${result?.accelerator?`<span class="tag">${esc(String(result.accelerator).toUpperCase())}</span>`:''}${result?.exit_code!==undefined?`<span class="tag">EXIT ${esc(result.exit_code ?? '—')}</span>`:''}${result?.cleanup_ok!==undefined?`<span class="tag ${result.cleanup_ok?'success':'failure'}">${result.cleanup_ok?'清理已确认':'清理待确认'}</span>`:''}</div>${run.state==='waiting'?`<p class="notice">${esc(queueSummary(evidence))}；尚未占用资源。</p>`:''}${result?.error?`<p class="notice error">${esc(result.error)}</p>`:''}`);
  $('output-count').textContent=outputs.length;
  setMarkup('result-files',outputs.length?`<div class="output-list">${outputs.map((output,index)=>`<div class="output-file"><div><strong>${esc(output.path)}</strong><small>${size(output.size)} · SHA-256 ${esc(output.sha256)}</small></div><button class="secondary compact" data-output-run="${esc(run.id)}" data-output-index="${index}" data-output-name="${esc(output.path)}">下载 ↓</button></div>`).join('')}</div>`:`<p class="empty">${result?'该目标没有回传输出文件。':'任务结束后显示声明的输出文件。'}</p>`);
  $('result-content').textContent=JSON.stringify({run,plan:evidence.plan,plan_sha256:evidence.sha256},null,2);
  renderLogs(); switchResultTab(resultTab);
}
function renderLogs() {
  const run=currentRun(), result=run?.result; if (!run) return;
  const live=liveLogs?.runId===run.id?liveLogs:null;
  $('log-note').textContent=result ? result.synthetic?'模拟目标只验证分发，不执行上传代码。':result.logs_truncated?'最终日志超过保留上限，以下内容已截断。':result.note || '最终日志' : run.state==='waiting'?'等待资源，尚未开始执行。':live?.error?'实时日志读取失败：'+live.error:live?.truncated?'实时日志达到保留上限，部分内容已截断。':active(run.state)?'实时输出 · 每 2 秒更新；程序自身的输出缓冲可能延迟显示。':'任务已结束，尚未返回最终日志。';
  if (result?.live_logs_truncated) $('log-note').textContent+=' · 实时传输曾截断，此处显示最终日志。';
  else if (result?.live_logs_delivery_pending) $('log-note').textContent+=' · 任务结束时实时传输尚待确认，此处以最终结果为准。';
  const element=$('result-log'), position=element.scrollTop, follow=element.scrollHeight-element.clientHeight-position<32;
  const text=resultLogs() || (result?'（没有匹配的日志内容）':run.state==='waiting'?'等待资源…':'等待输出…');
  if (element.textContent!==text) { element.textContent=text; element.scrollTop=follow?element.scrollHeight:position; }
  $('copy-log').disabled=!result&&!live?.events.length; $('download-log').disabled=$('copy-log').disabled;
}
function appendLiveEvents(cache, response) {
  for (const event of response.events || []) {
    if (!Number.isSafeInteger(event.sequence) || event.sequence<=cache.sequence || typeof event.text!=='string') continue;
    const text=event.text.slice(-262144);
    cache.events.push({sequence:event.sequence,stream:String(event.stream || 'stdout'),text}); cache.length+=text.length; cache.sequence=event.sequence;
    if (text.length!==event.text.length) cache.truncated=true;
  }
  // Keep only the selected run's recent text, bounded even during long experiments.
  while (cache.length>262144 || cache.events.length>2048) { cache.length-=cache.events.shift().text.length;cache.truncated=true; }
  if (Number.isSafeInteger(response.next_sequence)) cache.sequence=Math.max(cache.sequence,response.next_sequence);
  cache.truncated ||= Boolean(response.truncated); cache.error='';
}
async function pollLiveLogs() {
  const run=currentRun();
  if (document.hidden || !$('result-dialog').open || resultTab!=='logs' || !run || run.result || !['running','cancelling'].includes(run.state)) return;
  if (liveLogs?.runId!==run.id) liveLogs={runId:run.id,events:[],sequence:0,length:0,truncated:false,error:'',loading:false};
  const cache=liveLogs; if (cache.loading) return; cache.loading=true;
  try {
    const response=await api('/runs/'+encodeURIComponent(run.id)+'/logs?after='+cache.sequence);
    if (liveLogs===cache) appendLiveEvents(cache,response);
  } catch (error) { cache.error=error.message; }
  finally { cache.loading=false; if ($('result-dialog').open && currentRun()?.id===cache.runId) renderLogs(); }
}
function switchResultTab(tab) {
  resultTab=tab; for (const value of ['logs','outputs','details']) $('result-'+value).hidden=value!==tab;
  for (const button of document.querySelectorAll('[data-result-tab]')) { const chosen=button.dataset.resultTab===tab; button.setAttribute('aria-selected',String(chosen)); button.tabIndex=chosen?0:-1; }
}
function switchView(view) {
  const names={overview:'设备',monitor:'设备监控',composer:'新建实验',experiments:'实验记录',artifacts:'制品库',modules:'模块与配置',help:'接入与帮助'};
  if (!names[view]) return;
  for (const element of document.querySelectorAll('.view')) element.hidden=element.id!==view;
  for (const element of document.querySelectorAll('.nav')) { element.classList.toggle('active',element.dataset.view===view); element.setAttribute('aria-current',element.dataset.view===view?'page':'false'); }
  $('page-name').textContent=names[view]; history.replaceState(null,'','#'+view);
  if (view==='artifacts') { loadArtifacts(); loadEnvironments(); }
  if (view==='composer') loadEnvironments();
  if (view==='monitor') { renderMonitorSelector(); renderMonitor(); pollMonitor(true); }
}
async function loadCatalog() {
  try { catalog=await api('/catalog'); setMarkup('profiles',[...catalog.boards,...catalog.systems].map(profile=>`<article class="profile-card panel"><code>${esc(profile.id)}</code><h3>${esc(profile.name)}</h3><p>${esc(profile.soc || profile.requires || '')}</p><div class="tag-list">${[profile.architecture,profile.module].filter(Boolean).map(value=>`<span class="tag">${esc(value)}</span>`).join('')}</div></article>`).join('')); }
  catch (error) { setMarkup('profiles',`<p class="empty">${esc(error.message)}</p>`); }
}

// Native controls and one delegated handler keep the inventory, drawer and composer consistent.
document.addEventListener('click',async event=>{
  const button=event.target.closest('button'); if (!button) return;
  try {
    if (button.dataset.view) switchView(button.dataset.view);
    if (button.dataset.close) $(button.dataset.close).close();
    if (button.hasAttribute('data-lab')) $('lab-dialog').showModal();
    if (button.hasAttribute('data-copy')) await copy(button.dataset.copy);
    if (button.hasAttribute('data-upload-environment')) $('environment-file').click();
    if (button.hasAttribute('data-refresh-environments')) await loadEnvironments();
    if (button.hasAttribute('data-upload')) $('artifact-file').click();
    if (button.dataset.device) inspectBoard(button.dataset.device);
    if (button.dataset.monitor) { $('device-dialog').close(); renderMonitorSelector(); $('monitor-device').value=button.dataset.monitor; monitorData=null; monitorLastRequest=0; switchView('monitor'); }
    if (button.dataset.toggleDevice) changeSelection(button.dataset.toggleDevice,!selected.has(button.dataset.toggleDevice));
    if (button.dataset.result) { if ($('device-dialog').open) $('device-dialog').close(); await openResult(button.dataset.result); }
    if (button.dataset.reuse) await reuseBatch(button.dataset.reuse);
    if (button.dataset.resultTab) switchResultTab(button.dataset.resultTab);
    if (button.dataset.cpu!==undefined) { const current=new Set($('cpus').value.split(',').map(value=>value.trim()).filter(Boolean)); current.has(button.dataset.cpu)?current.delete(button.dataset.cpu):current.add(button.dataset.cpu); $('cpus').value=[...current].sort((a,b)=>Number(a)-Number(b)).join(','); invalidateCheck(); updateResources(); }
    if (button.dataset.useArtifact) { $('source').value='artifact'; $('artifact').value=button.dataset.useArtifact; updateSource(); updateArtifactSummary(); invalidateCheck(); switchView('composer'); }
    if (button.dataset.useEnvironment) useEnvironment(button.dataset.useEnvironment);
    if (button.dataset.downloadArtifact) await download('/artifacts/'+button.dataset.downloadArtifact+'/download','experiment-'+button.dataset.downloadArtifact.slice(0,12)+'.zip');
    if (button.dataset.outputRun) await download('/runs/'+encodeURIComponent(button.dataset.outputRun)+'/outputs/'+button.dataset.outputIndex,button.dataset.outputName.split('/').pop());
    if (button.dataset.cancel) { await api('/batches/'+encodeURIComponent(button.dataset.cancel)+'/cancel','POST'); toast('取消已请求，等待代理确认清理'); await refresh(); }
    if (button.dataset.reload) await reloadBoard(button.dataset.reload,button.dataset.force==='true');
    if (button.dataset.labRestart) await restartLab(button.dataset.labRestart,button.dataset.force==='true');
    if (button.dataset.recover && confirm('仅在确认该设备上的实验负载已停止、资源配置已恢复后继续。确认恢复设备？')) { await api('/boards/'+encodeURIComponent(button.dataset.recover)+'/recover?cleanup_confirmed=true','POST'); toast('已恢复设备'); await refresh(); }
  } catch (error) { toast(error.message); }
});
document.addEventListener('change',event=>{if (event.target.dataset.board) { changeSelection(event.target.dataset.board,event.target.checked); event.target.checked=selected.has(event.target.dataset.board); }});
$('demo-toggle').onchange=toggleDemo;
$('select-all').onclick=()=>{const ready=filteredBoards().filter(board=>boardState(board)==='ready'), all=ready.length&&ready.every(board=>selected.has(board.id)); if(all) ready.forEach(board=>selected.delete(board.id)); else for (const board of ready) { if(selected.size>=32) break; selected.add(board.id); } invalidateCheck(); renderBoards();};
for (const id of ['clear-selection','clear-targets']) $(id).onclick=()=>{selected.clear();invalidateCheck();renderBoards();};
for (const id of ['search','board-filter','system-filter']) $(id).addEventListener('input',renderBoards);
for (const id of ['history-search','history-filter','history-board']) $(id).addEventListener('input',renderHistory);
$('artifact-search').oninput=()=>{renderArtifactList();renderEnvironmentList();};
$('refresh').onclick=()=>{pollMonitor(true);refresh();loadArtifacts();loadEnvironments();loadCatalog();};
$('experiment-form').onsubmit=event=>{event.preventDefault();launch(true);}; $('preflight').onclick=()=>launch(false);
$('experiment-form').addEventListener('input',event=>{event.target.setCustomValidity?.('');invalidateCheck();});
$('source').onchange=()=>{updateSource();invalidateCheck();}; $('template').onchange=()=>{updateSource();invalidateCheck();};
$('artifact').onchange=()=>{updateArtifactSummary();invalidateCheck();};
for (const id of ['memory-mode','memory','cpus','duration']) $(id).addEventListener('input',updateResources);
$('execution-environment').onchange=()=>{renderEnvironmentSummary();invalidateCheck();};
$('environment-file').onchange=event=>uploadEnvironment(event.target.files[0]);
$('enqueue').onchange=invalidateCheck;
$('resource-policy').onchange=()=>{updateResources();invalidateCheck();};
$('monitor-device').onchange=()=>{monitorData=null;monitorError='';monitorLastRequest=0;renderMonitor();pollMonitor(true);};
$('monitor-refresh').onclick=()=>pollMonitor(true);
$('artifact-file').onchange=event=>uploadArtifact(event.target.files[0]);
$('upload-zone').onclick=()=>$('artifact-file').click();
$('upload-zone').onkeydown=event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();$('artifact-file').click();}};
$('upload-zone').ondragover=event=>{event.preventDefault();$('upload-zone').classList.add('dragging');};
$('upload-zone').ondragleave=()=>$('upload-zone').classList.remove('dragging');
$('upload-zone').ondrop=event=>{event.preventDefault();$('upload-zone').classList.remove('dragging');uploadArtifact(event.dataTransfer.files[0]);};
$('auth-button').onclick=()=>$('auth-dialog').showModal();
$('auth-form').onsubmit=event=>{event.preventDefault();token=$('token').value;$('token').value='';authPrompted=false;$('auth-dialog').close();loadCatalog();loadArtifacts();loadEnvironments();refresh();};
$('export-plan').onclick=()=>{try{saveBlob(new Blob([JSON.stringify(plan(),null,2)],{type:'application/json'}),'side-galaxy-plan.json');}catch(error){toast(error.message);}};
$('reuse-result').onclick=()=>reuseBatch(evidence.id).catch(error=>toast(error.message));
$('export').onclick=()=>{if(evidence)saveBlob(new Blob([JSON.stringify(evidence,null,2)],{type:'application/json'}),'side-galaxy-'+evidence.id+'.json');};
$('result-cancel').onclick=async()=>{try{evidence=await api('/batches/'+encodeURIComponent(evidence.id)+'/cancel','POST');renderResult();await refresh();}catch(error){toast(error.message);}};
$('result-target').onchange=()=>{$('log-search').value='';renderRunResult();pollLiveLogs();};
$('log-stream').onchange=renderLogs; $('log-search').oninput=renderLogs;
$('copy-log').onclick=()=>copy(resultLogs());
$('download-log').onclick=()=>saveBlob(new Blob([resultLogs(false)],{type:'text/plain;charset=utf-8'}),'side-galaxy-'+currentRun().id+'.log');
document.addEventListener('keydown',event=>{
  if (event.key==='/'&&!event.ctrlKey&&!event.metaKey&&!['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName)&&!document.querySelector('dialog[open]')) { event.preventDefault();switchView('overview');$('search').focus(); }
  if (event.target.dataset.resultTab && ['ArrowLeft','ArrowRight'].includes(event.key)) { event.preventDefault();const tabs=[...document.querySelectorAll('[data-result-tab]')],index=tabs.indexOf(event.target),next=tabs[(index+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length];switchResultTab(next.dataset.resultTab);next.focus(); }
});
$('evidence-note').textContent='模拟设备只验证分发；Linux / KVM 目标执行实际代码。';
updateSource();switchView(location.hash.slice(1)||'overview');loadCatalog();loadArtifacts();refresh();setInterval(()=>{if(!document.hidden){refresh();if(!$('monitor').hidden){renderMonitor();pollMonitor();}}},2000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
