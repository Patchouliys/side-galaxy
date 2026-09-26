const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const selected = new Set();
let token = '', boards = [], batches = [], evidence = null, refreshing = false, pendingIntent = null;
const labels = {ready:'就绪',busy:'实验中',offline:'离线',quarantined:'已隔离',queued:'排队中',running:'运行中',cancelling:'取消中',succeeded:'已完成',failed:'失败',cancelled:'已取消',lost:'失联'};
const titles = {'cpu-contention':'CPU 竞争实验','memory-copy':'内存拷贝实验','kvm-affinity':'KVM 在线绑核'};
const active = s => ['queued','running','cancelling'].includes(s);
const status = s => `<span class="status ${esc(s)}">${esc(labels[s] || s)}</span>`;
async function api(path, method='GET', body, key) {
  const response = await fetch('/api'+path, {method,headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body?{'Content-Type':'application/json'}:{}),...(key?{'Idempotency-Key':key}:{})},body:body?JSON.stringify(body):undefined});
  const data = await response.json();
  if (!response.ok) { if(response.status===401 && !$('auth-dialog').open) $('auth-dialog').showModal(); throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)); }
  return data;
}
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').hidden=true,5000); }
function selection() { $('selected-count').textContent=selected.size+' 块板卡'; }
function renderBoards() {
  const query=$('search').value.toLowerCase();
  const markup=boards.filter(b=>[b.name,b.board_profile,b.system_profile].join(' ').toLowerCase().includes(query)).map(b=>{
    const d=b.description;
    return `<article class="board ${selected.has(b.id)?'selected':''}"><div class="board-top"><input type="checkbox" id="b-${esc(b.id)}" data-board="${esc(b.id)}" ${selected.has(b.id)?'checked':''} ${b.status==='ready'?'':'disabled'} aria-label="选择 ${esc(b.name)}"><label for="b-${esc(b.id)}"><span class="board-symbol">▦</span><h3>${esc(b.name)}<small>${esc(b.board_profile)} / ${esc(b.system_profile)}</small></h3></label>${status(b.status)}</div><div class="board-facts"><span class="tag ${d?.mode==='synthetic'?'synthetic':''}">${d?.mode==='synthetic'?'SIMULATED':esc(d?.mode || 'AWAITING AGENT')}</span><span class="tag">${d?.cpus.length || 0} CORES</span><span class="tag">${esc(d?.name || '等待能力探测')}</span></div><div class="cpu-row"><span>核心拓扑 / ${esc(d?.module_sha256.slice(0,8) || '--------')}</span><div class="cores">${(d?.cpus || []).slice(0,16).map(c=>`<span class="core ${d.reserved_cpus.includes(c)?'reserved':''}" title="CPU ${c}${d.reserved_cpus.includes(c)?' 管理保留':''}">${c}</span>`).join('')}</div></div></article>`;
  }).join('') || '<p class="empty">暂无匹配板卡。使用 sg enroll 注册代理。</p>';
  if(renderBoards.markup!==markup) { $('boards').innerHTML=markup; renderBoards.markup=markup; }
  $('board-count').textContent=boards.length;
  selection();
}
function batchRows(items) {
  return items.map(b=>{
    const running=b.runs.some(r=>active(r.state));
    const state=running?(b.runs.some(r=>r.state==='cancelling')?'cancelling':'running'):b.runs.every(r=>r.state==='succeeded')?'succeeded':b.runs.some(r=>['failed','lost'].includes(r.state))?'failed':'cancelled';
    return `<article class="run-row"><span class="run-icon">⌁</span><div class="run-label">${esc(titles[b.plan.template] || b.plan.template)}<small>${esc(b.id.slice(0,8))} · ${b.runs.length} BOARDS · ${b.plan.duration_seconds}s · ${new Date(b.created*1000).toLocaleTimeString('zh-CN')}</small></div>${status(state)}<button class="quiet" data-result="${esc(b.id)}">查看记录 ↗</button>${running?`<button class="quiet" data-cancel="${esc(b.id)}">取消</button>`:''}</article>`;
  }).join('') || '<p class="empty">暂无实验记录。</p>';
}
function renderModules() {
  const markup=boards.map(b=>`<article class="module-item"><div><h3>${esc(b.name)}</h3><p>${esc(b.system_profile)} → ${esc(b.description?.name || '等待探测')}<br><code>${esc(b.description?.module_sha256.slice(0,20) || '未连接')}</code><br>${esc((b.description?.capabilities || []).join(' / '))}<br>${b.reload_error?esc(b.reload_error):b.reload_requested>b.reload_ack?'重载已请求，等待空闲边界':'模块就绪 · 新实验固定当前版本'}</p></div>${status(b.status)}<button class="secondary" data-reload="${esc(b.id)}">↻ 热重载</button></article>`).join('');
  if(renderModules.markup!==markup) { $('module-list').innerHTML=markup; renderModules.markup=markup; }
}
async function refresh() {
  if (refreshing) return;
  refreshing=true;
  try {
    [boards,batches]=await Promise.all([api('/boards'),api('/batches')]);
    for(const id of selected) if(!boards.some(b=>b.id===id && b.status==='ready')) selected.delete(id);
    renderBoards(); renderModules();
    const online=boards.filter(b=>!['offline','quarantined'].includes(b.status));
    $('metric-online').textContent=String(online.length).padStart(2,'0'); $('metric-total').textContent=boards.length+' 块板卡已注册';
    $('metric-cores').textContent=String(online.reduce((n,b)=>n+(b.description?.cpus.filter(c=>!b.description.reserved_cpus.includes(c)).length || 0),0)).padStart(2,'0');
    const runs=batches.flatMap(b=>b.runs);
    $('metric-active').textContent=String(runs.filter(r=>active(r.state)).length).padStart(2,'0'); $('metric-complete').textContent=String(runs.filter(r=>r.state==='succeeded').length).padStart(2,'0');
    $('nav-count').textContent=batches.length; $('recent-runs').innerHTML=batchRows(batches.slice(0,4)); $('all-runs').innerHTML=batchRows(batches); $('connection').textContent='● 控制面在线';
    const templates=[...new Set(boards.flatMap(b=>b.description?.templates || []))];
    for(const name of templates) if(![...$('template').options].some(o=>o.value===name)) $('template').add(new Option(name,name));
  } catch(error) { $('connection').textContent='连接待恢复'; $('feedback').textContent=error.message; }
  finally { refreshing=false; }
}
function plan() {
  const cores=id=>$(id).value.trim()?$(id).value.split(',').map(s=>{if(!/^\d+$/.test(s.trim())) throw new Error('核心请用逗号分隔的非负整数');return Number(s.trim());}):[];
  if(!selected.size) throw new Error('请先选择至少一块就绪板卡。');
  return {boards:[...selected].sort(),template:$('template').value,cpus:cores('cpus'),interference_cpus:cores('noise'),memory_mib:$('memory').disabled?null:Number($('memory').value),duration_seconds:Number($('duration').value),bandwidth_percent:null};
}
async function launch(submit) {
  $('launch').disabled=true; $('preflight').disabled=true;
  try {
    // Confirm an unknown previous submission before allowing a new intent.
    if (submit && pendingIntent) {
      const batch=await api('/batches','POST',pendingIntent.payload,pendingIntent.key); pendingIntent=null; toast('已确认实验批次 '+batch.id.slice(0,8)); await refresh(); return;
    }
    const payload=plan();
    const check=await api('/preflight','POST',payload);
    if(!check.valid) throw new Error(check.errors.map(e=>e.reasons.join('；')).join(' / '));
    $('feedback').textContent='预检通过 · '+check.targets.length+' 块板卡 · '+check.plan_sha256.slice(0,12);
    if(submit) {
      pendingIntent={payload,key:crypto.randomUUID()};
      const batch=await api('/batches','POST',payload,pendingIntent.key); pendingIntent=null;
      $('feedback').textContent='实验已提交 · '+batch.id.slice(0,8); toast('已提交，共 '+batch.runs.length+' 个目标'); await refresh();
    }
  } catch(error) { $('feedback').textContent=error.message; }
  finally { $('launch').disabled=false; $('preflight').disabled=false; }
}
function switchView(view) { for(const element of document.querySelectorAll('.view')) element.hidden=element.id!==view; for(const element of document.querySelectorAll('.nav')) element.classList.toggle('active',element.dataset.view===view); $('page-name').textContent={overview:'板卡',experiments:'实验',modules:'模块'}[view]; }
document.addEventListener('click',async event=>{
  const button=event.target.closest('button'); if(!button) return;
  try {
    if(button.dataset.view) switchView(button.dataset.view);
    if(button.dataset.cancel) { await api('/batches/'+button.dataset.cancel+'/cancel','POST'); toast('取消已请求，等待代理清理'); await refresh(); }
    if(button.dataset.reload) { await api('/boards/'+button.dataset.reload+'/reload','POST'); toast('重载已请求，运行中的实验继续使用原版本'); await refresh(); }
    if(button.dataset.result) { evidence=await api('/batches/'+button.dataset.result); $('result-content').textContent=JSON.stringify(evidence,null,2); $('result-dialog').showModal(); }
  } catch(error) { toast(error.message); }
});
$('boards').addEventListener('change',event=>{const id=event.target.dataset.board;if(id){event.target.checked?selected.add(id):selected.delete(id);renderBoards();}});
$('select-all').onclick=()=>{const ready=boards.filter(b=>b.status==='ready');const all=ready.every(b=>selected.has(b.id));selected.clear();if(!all)ready.forEach(b=>selected.add(b.id));renderBoards();};
$('search').oninput=renderBoards; $('refresh').onclick=refresh;
$('experiment-form').onsubmit=event=>{event.preventDefault();launch(true);}; $('preflight').onclick=()=>launch(false);
$('template').onchange=()=>{const kvm=$('template').value==='kvm-affinity';$('noise').value=kvm?'':'2';$('noise').disabled=kvm;$('memory').disabled=kvm;$('plan-note').textContent=kvm?'调整指定 VM 的 vCPU affinity，采集后恢复；不更改 VM 内存。':'每块板卡同时运行一个实验；实验内部可以包含干扰进程。';};
$('auth-button').onclick=()=>$('auth-dialog').showModal();$('auth-close').onclick=()=>$('auth-dialog').close();
$('auth-form').onsubmit=event=>{event.preventDefault();token=$('token').value;$('token').value='';$('auth-dialog').close();loadCatalog();refresh();};
$('result-close').onclick=()=>$('result-dialog').close();
$('export').onclick=()=>{if(!evidence)return;const url=URL.createObjectURL(new Blob([JSON.stringify(evidence,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='side-galaxy-'+evidence.id+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
fetch('/healthz').then(r=>r.json()).then(h=>{$('mode').textContent=h.demo?'DEMO · SYNTHETIC':'CONTROL PLANE';$('evidence-note').textContent=h.demo?'模拟模式的数值为合成数据，不代表硬件测量。':'执行能力以代理探测为准。硬件隔离与真实实验须逐板验收。';});
function loadCatalog() { return api('/catalog').then(c=>{$('profiles').innerHTML=[...c.boards,...c.systems].map(p=>`<article class="profile-card"><code>${esc(p.id)}</code><h3>${esc(p.name)}</h3><p>${esc(p.soc || p.requires)}</p></article>`).join('');}).catch(()=>{}); }
loadCatalog();
refresh(); setInterval(refresh,2000);
