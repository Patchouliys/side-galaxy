/* Run with node scripts/check_console_workflow.cjs; no browser dependencies. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {id, value:'', checked:false, textContent:'', innerHTML:'', options:[],
    classList:{add(){},remove(){}}, contains:()=>false, querySelectorAll:()=>[], reportValidity:()=>true,
    add(option){this.options.push(option);}, scrollTop:0, scrollHeight:500, clientHeight:100});
  return elements.get(id);
}
const context = vm.createContext({console, setTimeout:()=>0, clearTimeout(){}, crypto:{randomUUID:()=> 'retry-key'},
  document:{getElementById:element, hidden:false}, Option:function(label,value){this.label=label;this.value=value;}});
const source = fs.readFileSync(path.join(__dirname,'../src/side_galaxy/static/app.js'),'utf8');
vm.runInContext(source.split('// Native controls and one delegated handler')[0],context);
const run = code=>vm.runInContext(code,context);

(async()=>{
  assert.equal(run("batchState({runs:[{state:'waiting'},{state:'waiting'}]})"),'waiting');
  assert.equal(run("batchState({runs:[{state:'queued'},{state:'waiting'}]})"),'queued');
  assert.equal(run("active('waiting')"),true);
  assert.equal(run("selectable({status:'busy'})"),true);
  assert.equal(run("selectable({status:'quarantined'})"),false);
  run("liveLogs={runId:'run-1',events:[],sequence:0,length:0,truncated:false}");
  run("appendLiveEvents(liveLogs,{events:[{sequence:1,stream:'stdout',text:'first\\n'},{sequence:2,stream:'stderr',text:'<script>alert(1)</script>\\n'}],next_sequence:2})");
  run("appendLiveEvents(liveLogs,{events:[{sequence:2,stream:'stderr',text:'duplicate'},{sequence:3,stream:'stdout',text:'third\\n'}],next_sequence:3})");
  assert.equal(run('liveLogs.events.length'),3);
  assert.equal(run('liveLogs.sequence'),3);
  run("evidence={runs:[{id:'run-1',state:'running'}]}");
  element('log-stream').value='both';
  element('result-log').scrollTop=80;
  run('renderLogs()');
  assert.match(element('result-log').textContent,/<script>alert\(1\)<\/script>/);
  assert.equal(element('result-log').innerHTML,'', 'Log content must only use textContent');
  assert.equal(element('result-log').scrollTop,80,'Reading position must survive live updates');
  element('log-stream').value='stderr';
  assert.equal(run('resultLogs()'),'<script>alert(1)</script>\n');
  run("evidence.runs[0].result={stdout:'final stdout',stderr:'final stderr'}");
  assert.equal(run('resultLogs()'),'final stderr','Final evidence must replace transient live text');
  run("appendLiveEvents(liveLogs,{events:[{sequence:4,stream:'stdout',text:'x'.repeat(300000)}],next_sequence:4})");
  assert.ok(run('liveLogs.length<=262144'));
  assert.equal(run('liveLogs.truncated'),true);
  run("appendLiveEvents(liveLogs,{events:Array.from({length:3000},(_,i)=>({sequence:5+i,text:''})),next_sequence:3004})");
  assert.ok(run('liveLogs.events.length<=2048'),'Empty events must not grow the cache unbounded');

  run("boards=[{id:'board-1',status:'busy',description:{capabilities:['memory-limit']}}]; selected.add('board-1')");
  for (const [id,value] of Object.entries({source:'artifact',artifact:'a'.repeat(64),'execution-environment':'b'.repeat(64),
    'memory-mode':'auto',cpus:'1',noise:'',duration:'30',arguments:'[]',environment:'{}'})) element(id).value=value;
  assert.equal(run('plan().environment_sha256'),'b'.repeat(64));
  element('source').value='builtin';
  assert.equal(run('plan().environment_sha256'),null);
  element('source').value='artifact';
  run('renderEnvironments()');
  assert.equal(element('execution-environment').value,'b'.repeat(64),'Missing digest must not silently change runtime');
  assert.match(element('environment-summary').innerHTML,/不可用/);

  run("boards[0].description={mode:'qemu-kvm',environment_required:true,capabilities:['environment-bundle','memory-limit']}");
  assert.equal(run("modeName('qemu-kvm')"),'QEMU / KVM 加速');
  assert.equal(run("modeName('qemu-hvf')"),'QEMU / HVF 加速');
  assert.equal(run("modeName('qemu-tcg')"),'QEMU / TCG 仿真');
  assert.equal(run('memoryCaption(boards[0].description)'),'虚拟机内存预算');
  assert.equal(run("capabilityName('memory-limit',boards[0].description)"),'虚拟机内存预算');
  element('execution-environment').value='';
  element('execution-environment').options=[{value:'',textContent:'使用目标现有系统'}];
  element('memory-mode').options=[{value:'auto'},{value:'limit'}];
  run('updateResources()');
  assert.equal(element('execution-environment').required,true);
  assert.match(element('execution-environment').options[0].textContent,/目标必需/);
  assert.match(element('plan-note').textContent,/256 MiB 虚拟机内存预算/);
  assert.equal(element('memory-mode').options[1].textContent,'指定虚拟机内存');
  assert.throws(()=>run('plan()'),/离线环境包/);
  element('source').value='builtin';
  assert.throws(()=>run('plan()'),/离线环境包/);
  element('source').value='artifact';
  element('execution-environment').value='b'.repeat(64);
  assert.equal(run('plan().environment_sha256'),'b'.repeat(64));
  run("boards[0].description={capabilities:['memory-limit']}; updateResources()");
  assert.equal(element('execution-environment').required,false);
  assert.equal(run('memoryCaption(boards[0].description)'),'可设置进程上限');
  assert.match(element('plan-note').textContent,/进程地址空间上限/);

  run("environments=[{sha256:'b'.repeat(64),size:4096,manifest:{name:'Tools <script>',architecture:'aarch64',runtime:{os:'linux',commands:['cc','make','tool<tag>']}}}]; renderEnvironmentList()");
  assert.match(element('environment-list').innerHTML,/Tools &lt;script&gt;/);
  assert.match(element('environment-list').innerHTML,/tool&lt;tag&gt;/);
  assert.match(element('environment-list').innerHTML,/aarch64/);
  assert.match(element('environment-list').innerHTML,/4\.0 KiB/);
  assert.match(element('environment-list').innerHTML,/data-use-environment/);
  element('artifact-search').value='make';
  run('renderEnvironmentList()');
  assert.match(element('environment-list').innerHTML,/使用此环境/);
  element('artifact-search').value='missing-tool';
  run('renderEnvironmentList()');
  assert.match(element('environment-list').innerHTML,/没有匹配/);
  element('artifact-search').value='';
  run("environmentLoading=true; renderEnvironmentList()");
  assert.match(element('environment-list').innerHTML,/正在读取/);
  run("environmentLoading=false; environmentError='Network <failed>'; renderEnvironmentList()");
  assert.match(element('environment-list').innerHTML,/Network &lt;failed&gt;/);
  assert.match(element('environment-list').innerHTML,/data-refresh-environments/);
  run("environmentError=''; const realSwitchView=switchView; let chosenView=''; switchView=view=>{chosenView=view}; useEnvironment('b'.repeat(64)); switchView=realSwitchView");
  assert.equal(run('chosenView'),'composer');
  assert.equal(element('execution-environment').value,'b'.repeat(64));
  assert.equal(element('artifact').value,'a'.repeat(64),'Choosing an environment must retain experiment selection');
  run('environments=[]; renderEnvironmentList()');
  assert.match(element('environment-list').innerHTML,/还没有环境包/);

  // Fail the first submission after server acceptance could have happened, then
  // change the UI policy: the retry must keep the original payload/key/policy.
  context.calls=[];
  run(`let submissionAttempts=0;
    api=async(path,method,payload,key)=>{calls.push({path,method,payload,key});
      if(path.startsWith('/preflight'))return {valid:true,targets:[],errors:[],plan_sha256:'digest',waiting_reason:'board lease occupied'};
      if(submissionAttempts++===0)throw new Error('Connection lost');
      return {id:'batch-1',runs:[{state:'waiting'}]};};
    refresh=async()=>{};`);
  element('enqueue').checked=true;
  await run('launch(true)');
  assert.equal(context.calls[0].path,'/preflight?enqueue=true');
  assert.equal(context.calls[1].path,'/batches?enqueue=true');
  element('enqueue').checked=false;
  element('cpus').value='2';
  await run('launch(true)');
  assert.equal(context.calls[2].path,'/batches?enqueue=true');
  assert.equal(context.calls[2].key,context.calls[1].key);
  assert.equal(JSON.stringify(context.calls[2].payload),JSON.stringify(context.calls[1].payload));
  console.log('Console workflow checks passed: queue retry, environment pinning, bounded live logs, escaping, scroll and final evidence.');
})().catch(error=>{console.error(error);process.exitCode=1;});
