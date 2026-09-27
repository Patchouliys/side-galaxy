const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const clamp = value => Math.max(0,Math.min(1,value));
const mix = (start,end,amount) => start+(end-start)*amount;
const ease = (start,end,value) => { const t=clamp((value-start)/(end-start)); return t*t*(3-2*t); };

// ponytail: bake nebula detail once; animate only cached textures and six DOM stars.
function mountGalaxy() {
  const canvas=document.getElementById('galaxy-canvas'), story=document.getElementById('galaxy-story');
  const context=canvas?.getContext('2d',{alpha:true}); if (!context || !story) return;
  const stage=story.querySelector('.story-stage'), plane=canvas.parentElement, scene=plane.parentElement;
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
  // A softened flat-speed curve gives inner material a faster angular rate.
  const angularRate=radius=>1/Math.hypot(radius,.32);
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
  const diskProjection=document.createElement('div');diskProjection.className='galaxy-disk';
  diskProjection.appendChild(disk);plane.insertBefore(diskProjection,canvas);
  // Keep the broad spiral pattern slow; cached dust layers shear at different rates.
  const dust=[.36,.69,1.02].map((radius,index)=>{
    const layer=document.createElement('canvas');layer.width=layer.height=1024;
    const paint=layer.getContext('2d');paint.translate(512,512);
    for(let knot=0;knot<9;knot++) {
      const angle=knot*TAU/3+Math.log(radius+.12)*2.85+normal()*.2;
      const distance=(radius+normal()*.09)*diskRadius;
      glow(paint,index,Math.cos(angle)*distance,Math.sin(angle)*distance,46,35,.13);
    }
    for(let point=0;point<280;point++) {
      const distance=Math.max(.08,Math.min(1.24,radius+normal()*.13));
      const angle=point%3*TAU/3+Math.log(distance+.12)*2.85+normal()*.38;
      paint.globalAlpha=.18+random()*.35;paint.fillStyle=palette[index];
      const size=.5+random()*1.2;
      paint.fillRect(Math.cos(angle)*distance*diskRadius,Math.sin(angle)*distance*diskRadius,size,size);
    }
    diskProjection.appendChild(layer);return {layer,rate:angularRate(radius)};
  });
  const edge=document.createElement('canvas');edge.width=1024;edge.height=128;
  const edgePaint=edge.getContext('2d');
  for(let index=0;index<650;index++) {
    const x=random()*2-1,y=normal()*Math.pow(1-Math.abs(x),.7)*12;
    edgePaint.globalAlpha=(.2+random()*.5)*(1-Math.abs(x));edgePaint.fillStyle=palette[index%palette.length];
    const size=.4+random();edgePaint.fillRect(512+x*500,64+y,size,size);
  }
  const stars=Array.from({length:135},()=>({x:random(),y:random(),size:.4+random()*.8,alpha:.12+random()*.28}));
  const sky=document.createElement('canvas');
  const devices=[['Pi 4',-2.62,.62],['Pi 5',-1.34,.91],['QEMU',-.22,1.16],['Linux',.70,.76],['KVM guest',1.83,1.28],['Custom',2.48,.98]].map(([name,angle,r])=>({name,x:Math.cos(angle)*r,y:Math.sin(angle)*r,labelWidth:0,rate:angularRate(r)}));
  const ambient=document.createElement('div');ambient.className='galaxy-glints';ambient.setAttribute('aria-hidden','true');plane.appendChild(ambient);
  const coreGlint=document.createElement('span');coreGlint.className='core-glint';ambient.appendChild(coreGlint);
  const glints=devices.map(device=>{
    const element=document.createElement('span');element.className='star-glint';
    const label=document.createElement('span');label.className='star-label';label.textContent=device.name;
    element.appendChild(label);ambient.appendChild(element);return element;
  });
  let width=0,height=0,ratio=1,mobile=false,frame=0,previous=0,visible=true,progress=0,target=0,phase=-1,headerOffset=0,dirty=true,orbit=0;
  function bakeSky() {
    sky.width=canvas.width;sky.height=canvas.height;
    const paint=sky.getContext('2d');paint.setTransform(ratio,0,0,ratio,0,0);paint.fillStyle='#aabedb';
    for(const star of stars) {paint.globalAlpha=star.alpha;paint.fillRect(star.x*width,star.y*height,star.size,star.size);}
  }
  function geometry(value) {
    const turn=ease(.07,.75,value), convergence=ease(.43,.98,value);
    const radius=mix(Math.min(width*(mobile?.325:.222),height*(mobile?.18:.38)),width*(mobile?.43:.25),convergence);
    const tilt=mix(.78,1.554,turn);
    return {radius,convergence,flat:Math.cos(tilt),rotation:mix(-.28,-.08,turn),cx:width*(mobile?.50:mix(.70,.73,turn)),cy:height*(mobile?mix(.65,.66,turn):mix(.49,.50,turn))};
  }
  function draw(value) {
    context.setTransform(ratio,0,0,ratio,0,0);context.clearRect(0,0,width,height);
    context.globalAlpha=1;context.drawImage(sky,0,0,width,height);
    const g=geometry(value), {radius:r,flat,convergence:c}=g;
    context.save();context.translate(g.cx,g.cy);context.rotate(g.rotation);
    // Fade spiral structure before the hold; only a stable tapered band remains.
    const diskAlpha=1-ease(.62,.96,value);
    // Rotate the cached texture before projection; no idle canvas redraw is needed.
    const diameter=r*diskExtent*2;
    diskProjection.style.width=diskProjection.style.height=`${diameter}px`;
    diskProjection.style.transform=`translate(${g.cx-diameter/2}px,${g.cy-diameter/2}px) rotate(${g.rotation}rad) scaleY(${flat})`;
    diskProjection.style.opacity=String(diskAlpha);
    diskProjection.style.visibility=diskAlpha>0?'visible':'hidden';
    glow(context,3,0,0,r*.31,r*(mix(.055,.027,c)+.20*flat),.74);
    glow(context,3,0,0,r*.15,r*(.017+.087*flat),.9);
    glow(context,2,-r*.12,0,r*.98,r*.070,c*.85);
    glow(context,1,r*.18,0,r*.79,r*.050,c*.65);
    glow(context,3,0,0,r*.27,r*.065,c*.95);
    if(c>.02) {
      context.globalAlpha=c*.85;context.drawImage(edge,-r,-r*.12,r*2,r*.24);
    }
    context.restore();
    coreGlint.style.transform=`translate3d(${g.cx}px,${g.cy}px,0) rotate(${g.rotation}rad) scale(${r*.15/60},${r*(.042+.075*flat)/60})`;
    coreGlint.style.opacity=String(mix(.30,.36,c));
    context.globalAlpha=1;scene.classList.add('is-rendered');
  }
  function moveStars(value) {
    const g=geometry(value),{radius:r,flat,convergence:c}=g;
    disk.style.transform=`rotate(${orbit*.61}rad)`;
    for(const {layer,rate} of dust)layer.style.transform=`rotate(${orbit*rate}rad)`;
    const labelAlpha=(1-ease(.05,.25,c))*.65+ease(.97,1,c)*.85;
    const cos=Math.cos(g.rotation),sin=Math.sin(g.rotation);
    for(let index=0;index<devices.length;index++) {
      const device=devices[index],lineX=(index/(devices.length-1)*2-1)*r*.82;
      const spinCos=Math.cos(orbit*device.rate),spinSin=Math.sin(orbit*device.rate);
      const x=mix((device.x*spinCos-device.y*spinSin)*r,lineX,c);
      const y=(device.x*spinSin+device.y*spinCos)*r*flat*(1-c);
      const px=g.cx+x*cos-y*sin,py=g.cy+x*sin+y*cos,element=glints[index];
      element.style.transform=`translate3d(${px}px,${py}px,0)`;
      const label=element.firstChild,half=device.labelWidth/2;
      label.style.opacity=String(labelAlpha);
      label.style.left=`${Math.max(half+8,Math.min(width-half-8,px))-px}px`;
    }
  }
  const orbitSpeed=value=>1-ease(.43,.90,value);
  function showPhase(value) {
    const next=value<.34?0:value<.73?1:2;if(next===phase)return;phase=next;
    panels.forEach((panel,index)=>{panel.classList.toggle('is-active',index===next);panel.classList.toggle('is-past',index<next);panel.setAttribute('aria-hidden',String(index!==next));panel.inert=index!==next;});
    markers.forEach((marker,index)=>{marker.classList.toggle('is-active',index===next);if(index===next)marker.setAttribute('aria-current','step');else marker.removeAttribute('aria-current');});
  }
  function schedule() {
    scene.classList.toggle('ambient-active',visible&&!document.hidden&&!reducedMotion.matches);
    if(frame||document.hidden||!visible)return;
    if(reducedMotion.matches) {if(dirty){draw(0);moveStars(0);dirty=false;}return;}
    if(dirty||progress!==target||orbitSpeed(progress)>0) {previous=performance.now();frame=requestAnimationFrame(animate);}
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
    const lastProgress=progress;
    progress=mix(progress,target,1-Math.exp(-elapsed/.075));if(Math.abs(progress-target)<.0002)progress=target;
    orbit+=elapsed*TAU/44*orbitSpeed(progress);
    if(dirty||progress!==lastProgress) {draw(progress);showPhase(progress);dirty=false;}
    moveStars(progress);
    if(progress!==target||orbitSpeed(progress)>0)frame=requestAnimationFrame(animate);
  }
  function synchronize() {cancelAnimationFrame(frame);frame=0;schedule();}
  function resize() {
    const bounds=scene.getBoundingClientRect(),nextWidth=Math.max(1,bounds.width),nextHeight=Math.max(1,bounds.height),nextRatio=Math.min(devicePixelRatio||1,1.6);
    if(width!==nextWidth||height!==nextHeight||ratio!==nextRatio) {
      width=nextWidth;height=nextHeight;ratio=nextRatio;mobile=width<=660;
      canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);bakeSky();dirty=true;
      context.font=`${mobile?8:10}px ui-monospace, SFMono-Regular, monospace`;
      devices.forEach(device=>{device.labelWidth=context.measureText(device.name).width;});
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
