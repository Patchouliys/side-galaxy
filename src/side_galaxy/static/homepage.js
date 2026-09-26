const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
if (!reducedMotion.matches && 'IntersectionObserver' in window) {
  document.documentElement.classList.add('js-motion');
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) { entry.target.classList.add('visible'); observer.unobserve(entry.target); }
  }, {threshold:0.08});
  document.querySelectorAll('.reveal').forEach(element => observer.observe(element));
  const hero = document.querySelector('.hero'), scene = document.querySelector('.galaxy-scene');
  hero.addEventListener('pointermove', event => {
    if (event.pointerType !== 'mouse' || reducedMotion.matches) return;
    const bounds = hero.getBoundingClientRect();
    scene.style.setProperty('--scene-x', ((event.clientX - bounds.left) / bounds.width - 0.5) * 12 + 'px');
    scene.style.setProperty('--scene-y', ((event.clientY - bounds.top) / bounds.height - 0.5) * 8 + 'px');
  });
  hero.addEventListener('pointerleave', () => { scene.style.setProperty('--scene-x','0px'); scene.style.setProperty('--scene-y','0px'); });
}
document.getElementById('copy-start').onclick = async event => {
  const button = event.currentTarget;
  try { await navigator.clipboard.writeText(document.getElementById('start-command').textContent); button.textContent = '已复制'; }
  catch { button.textContent = '请选中复制'; }
  setTimeout(() => button.textContent = '复制', 2500);
};
