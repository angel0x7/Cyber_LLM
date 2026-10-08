/* Reading controls only. No execution, grading, storage or network calls. */
(() => {
  'use strict';
  document.querySelectorAll('[data-workbench]').forEach(bench => {
    const panels = [...bench.querySelectorAll('.work-panel')];
    const tabs = [...bench.querySelectorAll('[data-work-index]')];
    const previous = bench.querySelector('[data-work-prev]');
    const next = bench.querySelector('[data-work-next]');
    const toggle = bench.querySelector('.show-all');
    const status = bench.querySelector('.step-status');
    let active = 0, all = false;
    function show(index, focus = false) {
      active = Math.max(0, Math.min(index, panels.length - 1));
      panels.forEach((panel, i) => { panel.hidden = !all && i !== active; });
      tabs.forEach((tab, i) => {
        if (i === active) tab.setAttribute('aria-current', 'step');
        else tab.removeAttribute('aria-current');
      });
      previous.disabled = active === 0;
      next.disabled = active === panels.length - 1;
      status.textContent = all ? `All ${panels.length} steps` : `Step ${active + 1} / ${panels.length}`;
      toggle.textContent = all ? 'Show one step' : 'Show all steps';
      toggle.setAttribute('aria-expanded', String(all));
      if (focus) { panels[active].focus({preventScroll:true}); panels[active].scrollIntoView({block:'start'}); }
    }
    tabs.forEach((tab, i) => tab.addEventListener('click', () => show(i, true)));
    previous.addEventListener('click', () => show(active - 1, true));
    next.addEventListener('click', () => show(active + 1, true));
    toggle.addEventListener('click', () => { all = !all; show(active); });
    function fromHash() {
      let target;
      try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (_) { return; }
      const index = panels.findIndex(panel => target && (panel === target || panel.contains(target)));
      if (index >= 0) { show(index); requestAnimationFrame(() => target.scrollIntoView({block:'start'})); }
    }
    show(0); fromHash(); window.addEventListener('hashchange', fromHash);
    window.addEventListener('beforeprint', () => panels.forEach(panel => { panel.hidden = false; }));
    window.addEventListener('afterprint', () => show(active));
    bench.classList.add('enhanced');
  });
})();
