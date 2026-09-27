// Run from the repository root: node scripts/check_homepage_story.cjs
// Minimal DOM harness: verify differential orbit geometry and rendering lifecycle.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('src/side_galaxy/static/homepage.js','utf8');
function mount({width=1312,height=914,storyHeight=3000,header=86,intersection=true}={}){
  let now=0,top=header,rafId=0,labels=[],draws=0,renders=0,maxDraws=0;
  const rafs=new Map(),observers=[],winEvents={},docEvents={},motionEvents=[];
  function element(){const classes=new Set();return{attrs:{},style:{setProperty(key,value){this[key]=value}},children:[],appendChild(child){this.children.push(child);this.firstChild=this.children[0]},insertBefore(child){this.children.unshift(child)},classList:{add(x){classes.add(x)},remove(x){classes.delete(x)},toggle(x,on){if(on===undefined)on=!classes.has(x);on?classes.add(x):classes.delete(x);return on},contains(x){return classes.has(x)}},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},inert:false,offsetHeight:height,hidden:false};}
  function paint(main=false){const count=()=>{if(main)draws++};return{font:'10px monospace',createRadialGradient(){return{addColorStop(){}}},createLinearGradient(){return{addColorStop(){}}},setTransform(){},clearRect(){if(main){maxDraws=Math.max(maxDraws,draws);draws=0;labels=[];renders++}},save(){},restore(){},translate(){},rotate(){},fillRect:count,drawImage:count,beginPath(){},moveTo(){},lineTo(){},quadraticCurveTo(){},stroke:count,fill:count,arc(){},fillText(text,x,y){count();if(main)labels.push({text,x,y,width:this.measureText(text).width,height:parseFloat(this.font)})},measureText(text){return{width:text.length*parseFloat(this.font)*.6}}};}
  const panels=[element(),element(),element()],markers=[element(),element(),element()],root=element(),stage=element(),scene=element(),plane=element(),card=element();
  plane.parentElement=scene;scene.appendChild(plane);
  scene.getBoundingClientRect=()=>({width,height});
  const story={...element(),offsetHeight:storyHeight,getBoundingClientRect:()=>({top,bottom:top+storyHeight}),querySelector:()=>stage,querySelectorAll:selector=>selector==='.story-panel'?panels:markers};
  const mainContext=paint(true),canvas={...element(),parentElement:plane,getContext:()=>mainContext};
  const reduced={matches:false,addEventListener(type,callback){motionEvents.push(callback)}};
  const elements={'galaxy-canvas':canvas,'galaxy-story':story,'copy-start':element(),'start-command':{textContent:'uv sync --frozen\nuv run sg serve'}};
  const sandbox={console,Math,matchMedia:()=>reduced,devicePixelRatio:3,innerHeight:height+header,getComputedStyle:()=>({top:header+'px'}),requestAnimationFrame(callback){const id=++rafId;rafs.set(id,callback);return id},cancelAnimationFrame(id){rafs.delete(id)},performance:{now:()=>now},setTimeout(){},navigator:{clipboard:{writeText:async()=>{}}}};
  sandbox.document={hidden:false,documentElement:root,getElementById:id=>elements[id],createElement:tag=>tag==='canvas'?{...element(),getContext:()=>paint()}:element(),querySelectorAll:()=>[card],addEventListener(type,callback){docEvents[type]=callback}};
  sandbox.IntersectionObserver=class{constructor(callback){this.callback=callback;observers.push(this)}observe(target){this.target=target}unobserve(){}disconnect(){}};
  sandbox.ResizeObserver=class{observe(){}};
  sandbox.window={ResizeObserver:sandbox.ResizeObserver,addEventListener(type,callback){winEvents[type]=callback}};
  if(intersection)sandbox.window.IntersectionObserver=sandbox.IntersectionObserver;
  vm.runInNewContext(source,sandbox);
  const tick=(count,interval=1000/60)=>{for(let i=0;i<count;i++){now+=interval;const scheduled=[...rafs];rafs.clear();scheduled.forEach(([,callback])=>callback(now));}};
  const scroll=distance=>{top=header-distance;winEvents.scroll()};
  const hold=height*(width<=660?.4:.65),travel=storyHeight-height;
  return{sandbox,panels,root,scene,plane,canvas,rafs,tick,scroll,hold,travel,motion(value){reduced.matches=value;motionEvents.forEach(callback=>callback())},visible(value){observers.find(observer=>observer.target===story).callback([{isIntersecting:value}])},hidden(value){sandbox.document.hidden=value;docEvents.visibilitychange()},resize(){winEvents.resize()},get labels(){return labels},get renders(){return renders},get maxDraws(){return Math.max(maxDraws,draws)}};
}
for(const settings of [{},{width:284,height:580,storyHeight:1306.4,header:72}]){
  const page=mount(settings);page.tick(2);
  const disk=page.plane.children[0].children[0],nodes=page.plane.children[1].children.slice(1);
  const points=()=>nodes.map(node=>node.style.transform.match(/translate3d\(([^p]+)px,([^p]+)px/).slice(1).map(Number));
  const initial=points(),angle=()=>Number(disk.style.transform.match(/rotate\(([^r]+)rad/)[1]);
  const width=settings.width||1312,height=settings.height||914,mobile=width<=660;
  const radius=Math.min(width*(mobile?.325:.222),height*(mobile?.18:.38)),cx=width*(mobile?.5:.70),cy=height*(mobile?.65:.49);
  const unproject=([x,y])=>{x-=cx;y-=cy;return [ (x*Math.cos(-.28)+y*Math.sin(-.28))/radius,(-x*Math.sin(-.28)+y*Math.cos(-.28))/Math.cos(.78)/radius ];};
  const radii=initial.map(point=>Math.hypot(...unproject(point)));
  assert(Math.max(...radii)-Math.min(...radii)>.6,'opening stars must occupy different radii');
  const startAngle=angle(),renders=page.renders;page.tick(120);
  const moved=points(),delta=angle()-startAngle;
  assert(Math.abs(delta-Math.PI*2/22*.61)<.00001,'slow spiral pattern');
  const dustAngles=page.plane.children[0].children.slice(1).map(layer=>Number(layer.style.transform.match(/rotate\(([^r]+)rad/)[1]));
  assert(dustAngles[0]>dustAngles[1]&&dustAngles[1]>dustAngles[2],'inner dust must rotate faster');
  initial.forEach((point,i)=>{const [x,y]=unproject(point),[a,b]=unproject(moved[i]),turn=delta/.61/Math.hypot(radii[i],.32);assert(Math.abs(a-(x*Math.cos(turn)-y*Math.sin(turn)))<1e-6);assert(Math.abs(b-(x*Math.sin(turn)+y*Math.cos(turn)))<1e-6)});
  assert.equal(page.renders,renders,'orbit must not redraw canvas');
  for(const pause of ['visible','hidden']){page[pause](pause==='hidden');const frozen=angle(),positions=points();page.tick(90);assert.equal(page.rafs.size,0);assert.equal(angle(),frozen);assert.deepEqual(points(),positions);page[pause](pause!=='hidden');page.tick(2);assert(angle()>frozen)}
  const transition=page.travel-page.hold;page.scroll(transition);page.tick(100);
  assert.equal(page.rafs.size,0);assert.equal(page.plane.children[0].style.visibility,'hidden');
  const end=points();
  const center=end.reduce((acc,p)=>[acc[0]+p[0]/6,acc[1]+p[1]/6],[0,0]);
  assert(Math.abs(center[0]-width*(mobile?.5:.73))<1e-6,'final galaxy should be centered on the right on desktop');
  assert(Math.abs(center[1]-height*(mobile?.66:.50))<1e-6);
  const dx=end[1][0]-end[0][0],dy=end[1][1]-end[0][1];
  for(let i=1;i<6;i++){assert(Math.abs(end[i][0]-end[0][0]-i*dx)<1e-6);assert(Math.abs(end[i][1]-end[0][1]-i*dy)<1e-6)}
  const stopped=angle(),finalRenders=page.renders;
  page.scroll(page.travel-1);page.tick(120);assert.deepEqual(points(),end);assert.equal(angle(),stopped);assert.equal(page.renders,finalRenders);
  page.scroll(0);page.tick(100);assert.equal(page.panels[0].attrs['aria-hidden'],'false');assert.equal(page.rafs.size,1);
  page.motion(true);const reducedAngle=angle();page.tick(100);assert.equal(page.rafs.size,0);assert.equal(angle(),reducedAngle);assert(!page.scene.classList.contains('ambient-active'));
  page.motion(false);page.tick(100);assert.equal(page.rafs.size,1);
  const beforeResize=page.renders;page.resize();page.tick(5);assert.equal(page.renders,beforeResize);
  assert(page.maxDraws<=9);console.log(`PASS ${width}px: differential projected orbits; varied radii; equally spaced final line; zero idle Canvas redraws; pause/reverse/hold checks.`);
}
const fallback=mount({intersection:false});fallback.tick(2);fallback.scroll(9000);assert.equal(fallback.rafs.size,0);fallback.scroll(300);fallback.tick(100);assert.equal(fallback.rafs.size,1);
console.log('Galaxy orbit lifecycle checks passed.');
const css=fs.readFileSync('src/side_galaxy/static/homepage.css','utf8');assert(!css.includes('band-sway'),'final composition must not sway');
