const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');

// A cached star-cloud texture supplies detail; only foreground stars and currents move.
// ponytail: Canvas 2D is enough for this decorative scene; no WebGL or animation library.
function mountGalaxy() {
  const canvas = document.getElementById('galaxy-canvas');
  const context = canvas?.getContext('2d', {alpha:true});
  if (!context) return;
  const scene = canvas.parentElement, hero = document.querySelector('.hero');
  const texture = document.createElement('canvas'), paint = texture.getContext('2d');
  if (!paint) return;
  const TAU = Math.PI * 2, palette = ['#7dedca','#8dccff','#deefff','#c2a4ff','#fff0ce'];
  let seed = 7919;
  const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  const normal = () => Math.sqrt(-2 * Math.log(Math.max(0.00001, random()))) * Math.cos(TAU * random());
  let width = 0, height = 0, ratio = 1, radius = 1, frame = 0, previous = 0, elapsed = 0;
  let visible = true, pointerX = 0, pointerY = 0, targetX = 0, targetY = 0;
  const stars = Array.from({length:175}, () => ({x:random(),y:random(),size:0.35+random()*0.9,alpha:0.15+random()*0.48,phase:random()*TAU,speed:0.3+random()*0.8}));
  const dust = Array.from({length:580}, () => {
    const r = 0.12 + Math.pow(random(),0.7)*0.88;
    return {r,angle:random()*TAU,thickness:normal()*0.012,phase:random()*TAU,speed:0.025+(1-r)*0.045,size:0.65+random()*0.95,color:Math.floor(random()*palette.length)};
  });
  const currents = Array.from({length:24}, (_, index) => ({r:0.43+random()*0.68,angle:random()*TAU,speed:(index%2 ? 1 : -1)*(0.1+random()*0.09),pitch:0.16+random()*0.11,alpha:0.5+random()*0.35}));

  function glow(ctx, x, y, rx, ry, stops) {
    ctx.save(); ctx.translate(x,y); ctx.scale(rx,ry);
    const gradient = ctx.createRadialGradient(0,0,0,0,0,1);
    for (const [offset,color] of stops) gradient.addColorStop(offset,color);
    ctx.fillStyle=gradient; ctx.beginPath(); ctx.arc(0,0,1,0,TAU); ctx.fill(); ctx.restore();
  }
  function drawTexture() {
    texture.width=canvas.width; texture.height=canvas.height;
    paint.setTransform(ratio,0,0,ratio,0,0);
    paint.translate(width*0.51,height*0.49); paint.rotate(-0.27);
    glow(paint,-radius*0.3,0,radius*1.14,radius*0.54,[[0,'#6a65d846'],[0.35,'#577cc325'],[0.7,'#527db010'],[1,'#527db000']]);
    glow(paint,radius*0.18,0,radius*1.12,radius*0.47,[[0,'#57dcb646'],[0.35,'#47a69e24'],[0.7,'#429eab0c'],[1,'#429eab00']]);
    glow(paint,0,0,radius*1.05,radius*0.24,[[0,'#e6dfbb68'],[0.18,'#bce6d350'],[0.47,'#7dd6df37'],[0.75,'#7689c317'],[1,'#7689c300']]);
    glow(paint,0,0,radius*0.68,radius*0.095,[[0,'#fff0cfba'],[0.2,'#e0ecc875'],[0.65,'#85d8e62c'],[1,'#85d8e600']]);
    // Tapered spiral arms, seen close to their equatorial plane.
    seed=14087;
    for (let index=0;index<11200;index++) {
      const r=Math.pow(random(),0.63), arm=index%3;
      const angle=arm*TAU/3 + Math.log(r+0.12)*2.7 + normal()*(0.2+r*0.18);
      const x=Math.cos(angle)*r*radius, depth=Math.sin(angle)*r;
      const spread=normal()*(0.004+0.022*(1-r));
      const y=(depth*0.17+spread)*radius;
      const core=1-r, brightness=0.23+random()*0.45+core*0.12;
      paint.globalAlpha=brightness*(0.75+Math.max(0,depth)*0.25);
      paint.fillStyle=palette[r<0.18 ? 4 : x < -radius*0.35 ? (index%3 === 0 ? 3 : 1) : index%palette.length];
      const dot=(0.35+random()*0.9)*(0.75+core*0.25);
      paint.fillRect(x,y,dot,dot);
    }
    // A warm stellar bulge with resolved points rather than an overexposed disk.
    for (let index=0;index<2000;index++) {
      const x=normal()*radius*0.092, y=normal()*radius*0.031;
      paint.globalAlpha=0.12+random()*0.4; paint.fillStyle=index%3 ? '#eadfce' : '#d8eee2';
      const dot=0.3+random()*0.75; paint.fillRect(x,y,dot,dot);
    }
    paint.globalAlpha=1;
    // Dust in front of the bulge gives the edge-on disk depth.
    glow(paint,radius*0.02,radius*0.013,radius*0.7,radius*0.018,[[0,'#09101991'],[0.45,'#0b18234f'],[1,'#0b182300']]);
    glow(paint,0,-radius*0.013,radius*0.26,radius*0.064,[[0,'#ffe6bda8'],[0.25,'#efebbd77'],[0.58,'#b9e8d631'],[1,'#b9e8d600']]);
    glow(paint,0,-radius*0.014,radius*0.092,radius*0.025,[[0,'#fff8dff2'],[0.22,'#fff4d5c9'],[0.53,'#f6e6ba71'],[1,'#f6e6ba00']]);
    glow(paint,0,-radius*0.014,radius*0.31,radius*0.0028,[[0,'#fff8e49c'],[0.12,'#f8f3d473'],[0.5,'#baf2de24'],[1,'#baf2de00']]);
    // Fine irregular knots provide the dense, filament-like silhouette.
    for (let index=0;index<1800;index++) {
      const x=(random()*2-1)*radius*0.93, falloff=1-Math.abs(x/radius);
      const y=(Math.sin(x/radius*8)*0.009+normal()*0.009)*radius;
      paint.globalAlpha=falloff*(0.24+random()*0.4); paint.fillStyle=index%2 ? '#99f0d2' : '#bdd9ff';
      paint.fillRect(x,y,0.45+random()*0.8,0.45+random()*0.6);
    }
    paint.globalAlpha=1;
  }
  function draw(time) {
    context.setTransform(ratio,0,0,ratio,0,0); context.clearRect(0,0,width,height);
    const moveX=pointerX*9, moveY=pointerY*7;
    for (const star of stars) {
      const twinkle=reducedMotion.matches ? 0.8 : 0.66+Math.sin(time*star.speed+star.phase)*0.24;
      context.globalAlpha=star.alpha*twinkle; context.fillStyle='#bdd7e1';
      context.fillRect(star.x*width+moveX*0.3,star.y*height+moveY*0.3,star.size,star.size);
    }
    context.globalAlpha=1;
    context.drawImage(texture,moveX,moveY,width,height);
    context.save(); context.translate(width*0.51+moveX,height*0.49+moveY); context.rotate(-0.27);
    // Outer stellar streams are soft, incomplete ellipses, never hard neon rings.
    context.lineWidth=0.6;
    for (let index=0;index<3;index++) {
      context.strokeStyle=index===1 ? '#a7d8c20e' : '#8caec613';
      context.beginPath(); context.ellipse(0,0,radius*(0.78+index*0.11),radius*(0.21+index*0.035),0,0.15+index*0.6,Math.PI*1.78+index*0.3); context.stroke();
    }
    for (const point of dust) {
      const angle=point.angle+time*point.speed;
      const x=Math.cos(angle)*point.r*radius, y=(Math.sin(angle)*point.r*0.17+point.thickness)*radius;
      context.globalAlpha=(0.48+Math.sin(point.phase+time*0.7)*0.24)*(1-point.r*0.3);
      context.fillStyle=palette[point.color]; context.fillRect(x,y,point.size,point.size);
    }
    for (const stream of currents) {
      const angle=stream.angle+time*stream.speed;
      const x=Math.cos(angle)*stream.r*radius, y=Math.sin(angle)*stream.r*radius*stream.pitch;
      for (let tail=0;tail<10;tail++) {
        const a=angle-tail*Math.sign(stream.speed)*0.009;
        context.globalAlpha=stream.alpha*(1-tail/10)*0.88;
        context.fillStyle=stream.speed>0 ? '#b9ffe0' : '#c5cdff';
        context.beginPath(); context.arc(Math.cos(a)*stream.r*radius,Math.sin(a)*stream.r*radius*stream.pitch,tail===0 ? 1.65 : 1-tail*0.055,0,TAU); context.fill();
      }
      context.globalAlpha=stream.alpha*0.63;
      glow(context,x,y,9,9,[[0,'#d5fff5c4'],[0.2,'#aff3e35d'],[1,'#aff3e300']]);
    }
    context.globalAlpha=1;
    const shimmer=reducedMotion.matches ? 0.8 : 0.8+Math.sin(time*0.6)*0.16;
    context.globalAlpha=shimmer;
    glow(context,0,-radius*0.014,radius*0.16,radius*0.038,[[0,'#fff7ddb8'],[0.16,'#fff0ce69'],[0.45,'#d7f0d821'],[1,'#d7f0d800']]);
    // Small resolved star flares add a few bright accents without washing out the disk.
    for (let index=0;index<7;index++) {
      const angle=index*2.399+time*0.026, r=0.3+index*0.075;
      const x=Math.cos(angle)*r*radius, y=Math.sin(angle)*r*radius*0.18;
      const pulse=reducedMotion.matches ? 0.65 : 0.55+Math.sin(time*0.85+index*1.7)*0.3;
      context.globalAlpha=pulse;
      glow(context,x,y,13,13,[[0,'#e1fffbb5'],[0.13,'#bdeedf7c'],[0.42,'#7dcae624'],[1,'#7dcae600']]);
      context.strokeStyle=index%2 ? '#d2d9ff' : '#c5ffe5'; context.lineWidth=0.6;
      context.beginPath(); context.moveTo(x-6,y); context.lineTo(x+6,y); context.moveTo(x,y-4); context.lineTo(x,y+4); context.stroke();
    }
    context.restore(); context.globalAlpha=1;
  }
  function animate(now) {
    frame=0;
    if (document.hidden || !visible || reducedMotion.matches) return;
    // Limit to 30 fps, and never advance the scene across a suspended tab.
    if (now-previous>=1000/30) {
      elapsed+=Math.min((now-previous)/1000,0.05); previous=now;
      pointerX+=(targetX-pointerX)*0.045; pointerY+=(targetY-pointerY)*0.045;
      draw(elapsed);
    }
    frame=requestAnimationFrame(animate);
  }
  function synchronize() {
    cancelAnimationFrame(frame); frame=0; previous=performance.now();
    if (reducedMotion.matches) { pointerX=pointerY=targetX=targetY=0; draw(0); }
    else if (!document.hidden && visible) frame=requestAnimationFrame(animate);
  }
  function resize() {
    const bounds=scene.getBoundingClientRect();
    if (bounds.width===width && bounds.height===height && ratio===Math.min(devicePixelRatio||1,1.75)) return;
    width=Math.max(1,bounds.width); height=Math.max(1,bounds.height); ratio=Math.min(devicePixelRatio||1,1.75);
    radius=Math.min(width*0.405,height*0.63);
    canvas.width=Math.round(width*ratio); canvas.height=Math.round(height*ratio);
    drawTexture(); draw(reducedMotion.matches ? 0 : elapsed);
  }
  hero.addEventListener('pointermove',event=>{
    if (event.pointerType!=='mouse' || reducedMotion.matches) return;
    const bounds=hero.getBoundingClientRect();
    targetX=(event.clientX-bounds.left)/bounds.width-0.5; targetY=(event.clientY-bounds.top)/bounds.height-0.5;
  },{passive:true});
  hero.addEventListener('pointerleave',()=>{targetX=targetY=0;});
  if ('ResizeObserver' in window) new ResizeObserver(resize).observe(scene);
  window.addEventListener('resize',resize,{passive:true});
  if ('IntersectionObserver' in window) new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;synchronize();},{threshold:0}).observe(hero);
  document.addEventListener('visibilitychange',synchronize);
  reducedMotion.addEventListener('change',synchronize);
  resize(); scene.classList.add('is-rendered'); synchronize();
}
mountGalaxy();

if (!reducedMotion.matches && 'IntersectionObserver' in window) {
  document.documentElement.classList.add('js-motion');
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) { entry.target.classList.add('visible'); observer.unobserve(entry.target); }
  }, {threshold:0.08});
  document.querySelectorAll('.reveal').forEach(element => observer.observe(element));
}
document.getElementById('copy-start').onclick = async event => {
  const button = event.currentTarget;
  try { await navigator.clipboard.writeText(document.getElementById('start-command').textContent); button.textContent = '已复制'; }
  catch { button.textContent = '请选中复制'; }
  setTimeout(() => button.textContent = '复制', 2500);
};
