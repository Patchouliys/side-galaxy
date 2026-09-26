const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const clamp = value => Math.max(0,Math.min(1,value));
const mix = (start,end,amount) => start+(end-start)*amount;
const ease = (start,end,value) => { const t=clamp((value-start)/(end-start)); return t*t*(3-2*t); };

// ponytail: bake nebula detail once; scroll frames only project cached layers and six stars.
function mountGalaxy() {
  const canvas=document.getElementById('galaxy-canvas'), story=document.getElementById('galaxy-story');
  const context=canvas?.getContext('2d',{alpha:true}); if (!context || !story) return;
  const stage=story.querySelector('.story-stage'), scene=canvas.parentElement;
  const panels=[...story.querySelectorAll('.story-panel')], markers=[...story.querySelectorAll('.story-markers li')];
  const TAU=Math.PI*2, palette=['#a9dfec','#87b4eb','#b1a0e4','#d8eee8','#ffedc8'];
  let seed=7919;
  const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
  const normal=()=>Math.sqrt(-2*Math.log(Math.max(.00001,random())))*Math.cos(TAU*random());
  const sprites=['144,185,241','162,121,217','100,215,206','255,228,186'].map(rgb=>{
    const sprite=document.createElement('canvas');sprite.width=sprite.height=128;
    const paint=sprite.getContext('2d'), gradient=paint.createRadialGradient(64,64,0,64,64,64);
    gradient.addColorStop(0,`rgba(${rgb},.65)`);gradient.addColorStop(.18,`rgba(${rgb},.36)`);gradient.addColorStop(.5,`rgba(${rgb},.10)`);gradient.addColorStop(1,`rgba(${rgb},0)`);
    paint.fillStyle=gradient;paint.fillRect(0,0,128,128);return sprite;
  });
  function glow(paint,sprite,x,y,rx,ry,alpha=1) { paint.globalAlpha=alpha;paint.drawImage(sprites[sprite],x-rx,y-ry,rx*2,ry*2); }
  const disk=document.createElement('canvas');disk.width=disk.height=1024;
  const diskRadius=368, diskExtent=512/diskRadius;
  function bakeDisk() {
    const paint=disk.getContext('2d'), r=diskRadius;paint.translate(512,512);
    glow(paint,0,0,0,r*1.27,r*1.03,.28);
    glow(paint,1,-r*.24,r*.02,r*.83,r*.65,.36);
    glow(paint,2,r*.25,-r*.05,r*.83,r*.63,.34);
    for(let arm=0;arm<3;arm++) for(let knot=0;knot<12;knot++) {
      const distance=(.17+knot*.067)*r,angle=arm*TAU/3+Math.log(distance/r+.12)*2.85;
      glow(paint,arm,Math.cos(angle)*distance,Math.sin(angle)*distance,r*(.12+knot*.006),r*.15,.34);
    }
    for(let index=0;index<6100;index++) {
      const distance=Math.pow(random(),.63),arm=index%3,angle=arm*TAU/3+Math.log(distance+.12)*2.85+normal()*(.15+distance*.16);
      const size=.45+random()*1.15;
      paint.globalAlpha=.18+random()*.46;paint.fillStyle=palette[distance<.2?4:arm===0?1:arm===1?2:index%4];
      paint.fillRect(Math.cos(angle)*distance*r,Math.sin(angle)*distance*r,size,size);
    }
    paint.fillStyle='#fff0d1';
    for(let index=0;index<650;index++) {const size=.4+random();paint.globalAlpha=.16+random()*.38;paint.fillRect(normal()*.07*r,normal()*.06*r,size,size);}
    for(let index=0;index<14;index++) {
      const angle=index*2.399,distance=(.24+(index%8)*.085)*r,x=Math.cos(angle)*distance,y=Math.sin(angle)*distance;
      glow(paint,index%3,x,y,7,7,.55);paint.globalAlpha=.65;paint.fillStyle=index%2?'#dcd5ff':'#d0fff0';paint.fillRect(x-.6,y-.6,1.2,1.2);
    }
  }
  bakeDisk();
  const stars=Array.from({length:135},()=>({x:random(),y:random(),size:.4+random()*.8,alpha:.12+random()*.28}));
  const sky=document.createElement('canvas');
  const devices=[['Pi 4',-2.55,1.23],['Pi 5',-1.10,1.24],['QEMU',.03,1.15],['Linux',.93,1.23],['KVM guest',2.00,1.25],['Custom',2.92,1.18]].map(([name,angle,r],index)=>({name,x:Math.cos(angle)*r,y:Math.sin(angle)*r,color:index%2?'#bca7ee':'#a9e9e0'}));
  const ambient=document.createElement('div');ambient.className='galaxy-glints';ambient.setAttribute('aria-hidden','true');scene.appendChild(ambient);
  const coreGlint=document.createElement('span');coreGlint.className='core-glint';ambient.appendChild(coreGlint);
  const glints=devices.map(()=>{const element=document.createElement('span');element.className='star-glint';ambient.appendChild(element);return element;});
  let width=0,height=0,ratio=1,mobile=false,frame=0,previous=0,visible=true,progress=0,target=0,phase=-1,headerOffset=0,dirty=true;
  function bakeSky() {
    sky.width=canvas.width;sky.height=canvas.height;
    const paint=sky.getContext('2d');paint.setTransform(ratio,0,0,ratio,0,0);paint.fillStyle='#aabedb';
    for(const star of stars) {paint.globalAlpha=star.alpha;paint.fillRect(star.x*width,star.y*height,star.size,star.size);}
  }
  function geometry(value) {
    const turn=ease(.07,.75,value), convergence=ease(.43,.98,value);
    const radius=mix(Math.min(width*(mobile?.325:.222),height*(mobile?.18:.38)),width*(mobile?.43:.415),convergence);
    const tilt=mix(.16,1.554,turn);
    return {radius,convergence,flat:Math.cos(tilt),rotation:mix(-.07,-Math.PI*16/180,turn),cx:width*(mobile?.50:mix(.70,.535,turn)),cy:height*(mobile?mix(.65,.66,turn):mix(.49,.64,turn))};
  }
  function draw(value) {
    context.setTransform(ratio,0,0,ratio,0,0);context.clearRect(0,0,width,height);
    context.globalAlpha=1;context.drawImage(sky,0,0,width,height);
    const g=geometry(value), {radius:r,flat,convergence:c}=g;
    context.save();context.translate(g.cx,g.cy);context.rotate(g.rotation);
    // Fade spiral structure before the hold; only a stable tapered band remains.
    const diskAlpha=1-ease(.62,.96,value);
    if(diskAlpha>0) {context.globalAlpha=diskAlpha;context.drawImage(disk,-r*diskExtent,-r*diskExtent*flat,r*diskExtent*2,r*diskExtent*flat*2);}
    glow(context,3,0,0,r*.31,r*(mix(.055,.027,c)+.20*flat),.74);
    glow(context,3,0,0,r*.15,r*(.017+.087*flat),.9);
    glow(context,2,0,0,r*.96,r*.026,c*.76);
    glow(context,3,0,0,r*.53,r*.0075,c*.88);
    if(c>.02) {
      const band=context.createLinearGradient(-r,0,r,0);
      band.addColorStop(0,'#94d9e000');band.addColorStop(.22,'#9bcced4d');band.addColorStop(.48,'#e2ead8b8');band.addColorStop(.52,'#e2ead8b8');band.addColorStop(.8,'#b5a3ef5c');band.addColorStop(1,'#b5a3ef00');
      context.globalAlpha=c;context.strokeStyle=band;context.lineWidth=.8;context.beginPath();context.moveTo(-r,0);context.lineTo(r,0);context.stroke();
    }
    context.restore();
    coreGlint.style.transform=`translate3d(${g.cx}px,${g.cy}px,0) rotate(${g.rotation}rad) scale(${r*.15/60},${r*(.016+.075*flat)/60})`;
    coreGlint.style.opacity=String(mix(.30,.16,c));
    const labelAlpha=(1-ease(.05,.25,c))*.65+ease(.97,1,c)*.85;
    const cos=Math.cos(g.rotation),sin=Math.sin(g.rotation),project=(x,y)=>({x:g.cx+x*cos-y*sin,y:g.cy+x*sin+y*cos});
    context.font=`${mobile?8:10}px ui-monospace, SFMono-Regular, monospace`;context.textAlign='center';
    for(let index=0;index<devices.length;index++) {
      const device=devices[index],lineX=(index/(devices.length-1)*2-1)*r*.82;
      const point=project(mix(device.x*r,lineX,c),device.y*r*flat*(1-c)),anchor=project(lineX,0);
      if(c>.08&&c<.98) {
        context.globalAlpha=.15*Math.sin(c*Math.PI);context.strokeStyle=device.color;context.lineWidth=.7;
        context.beginPath();context.moveTo(point.x,point.y);context.quadraticCurveTo(mix(point.x,anchor.x,.6),anchor.y-18*(1-c),anchor.x,anchor.y);context.stroke();
      }
      glints[index].style.transform=`translate3d(${point.x}px,${point.y}px,0)`;
      glow(context,index%2?1:2,point.x,point.y,19,19,1);
      context.globalAlpha=.78;context.strokeStyle=device.color;context.lineWidth=.8;
      context.beginPath();context.moveTo(point.x-6,point.y);context.lineTo(point.x+6,point.y);context.moveTo(point.x,point.y-8);context.lineTo(point.x,point.y+8);context.stroke();
      context.globalAlpha=1;context.fillStyle='#effff8';context.beginPath();context.arc(point.x,point.y,mix(1.8,2.3,c),0,TAU);context.fill();
      if(labelAlpha>.001) {const half=context.measureText(device.name).width/2,labelX=Math.max(half+8,Math.min(width-half-8,point.x));context.globalAlpha=labelAlpha;context.fillStyle='#c1cfdf';context.fillText(device.name,labelX,point.y+23);}
    }
    context.globalAlpha=1;scene.classList.add('is-rendered');
  }
  function showPhase(value) {
    const next=value<.34?0:value<.73?1:2;if(next===phase)return;phase=next;
    panels.forEach((panel,index)=>{panel.classList.toggle('is-active',index===next);panel.classList.toggle('is-past',index<next);panel.setAttribute('aria-hidden',String(index!==next));panel.inert=index!==next;});
    markers.forEach((marker,index)=>{marker.classList.toggle('is-active',index===next);if(index===next)marker.setAttribute('aria-current','step');else marker.removeAttribute('aria-current');});
  }
  function schedule() {
    scene.classList.toggle('ambient-active',visible&&!document.hidden&&!reducedMotion.matches);
    if(frame||document.hidden||!visible)return;
    if(reducedMotion.matches) {if(dirty){draw(0);dirty=false;}return;}
    if(dirty||progress!==target) {previous=performance.now();frame=requestAnimationFrame(animate);}
  }
  function updateScroll() {
    if(reducedMotion.matches)return;
    const bounds=story.getBoundingClientRect(),travel=story.offsetHeight-stage.offsetHeight,hold=stage.offsetHeight*(mobile?.4:.65);
    target=clamp((headerOffset-bounds.top)/Math.max(1,travel-hold));
    if(!('IntersectionObserver' in window)) {visible=bounds.bottom>headerOffset&&bounds.top<innerHeight;if(!visible){cancelAnimationFrame(frame);frame=0;}}
    schedule();
  }
  function animate(now) {
    frame=0;if(document.hidden||!visible||reducedMotion.matches)return;
    const elapsed=Math.min(Math.max((now-previous)/1000,0),.05);previous=now;
    progress=mix(progress,target,1-Math.exp(-elapsed/.075));if(Math.abs(progress-target)<.0002)progress=target;
    draw(progress);showPhase(progress);dirty=false;
    if(progress!==target)frame=requestAnimationFrame(animate);
  }
  function synchronize() {cancelAnimationFrame(frame);frame=0;schedule();}
  function resize() {
    const bounds=scene.getBoundingClientRect(),nextWidth=Math.max(1,bounds.width),nextHeight=Math.max(1,bounds.height),nextRatio=Math.min(devicePixelRatio||1,1.6);
    if(width!==nextWidth||height!==nextHeight||ratio!==nextRatio) {
      width=nextWidth;height=nextHeight;ratio=nextRatio;mobile=width<=660;
      canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);bakeSky();dirty=true;
    }
    headerOffset=parseFloat(getComputedStyle(stage).top)||0;updateScroll();schedule();
  }
  function motionMode() {
    cancelAnimationFrame(frame);frame=0;document.documentElement.classList.toggle('story-ready',!reducedMotion.matches);phase=-1;dirty=true;
    if(reducedMotion.matches) {progress=target=0;panels.forEach(panel=>{panel.removeAttribute('aria-hidden');panel.inert=false;});markers.forEach(marker=>marker.removeAttribute('aria-current'));}
    resize();synchronize();
  }
  window.addEventListener('scroll',updateScroll,{passive:true});window.addEventListener('resize',resize,{passive:true});
  if('ResizeObserver' in window)new ResizeObserver(resize).observe(stage);
  if('IntersectionObserver' in window)new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;synchronize();},{threshold:0}).observe(story);
  document.addEventListener('visibilitychange',synchronize);reducedMotion.addEventListener('change',motionMode);
  motionMode();
}
mountGalaxy();

// The document remains fully readable when scripts or motion are disabled.
let revealObserver;
function synchronizeReveals() {
  revealObserver?.disconnect();document.documentElement.classList.toggle('js-motion',!reducedMotion.matches&&'IntersectionObserver' in window);
  if(reducedMotion.matches||!('IntersectionObserver' in window))return;
  revealObserver=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){entry.target.classList.add('visible');revealObserver.unobserve(entry.target);}},{threshold:.12});
  document.querySelectorAll('.reveal').forEach(element=>revealObserver.observe(element));
}
synchronizeReveals();reducedMotion.addEventListener('change',synchronizeReveals);
document.getElementById('copy-start').onclick=async event=>{
  const button=event.currentTarget;
  try{await navigator.clipboard.writeText(document.getElementById('start-command').textContent);button.textContent='已复制';}
  catch{button.textContent='请选中复制';}
  setTimeout(()=>button.textContent='复制',2500);
};
