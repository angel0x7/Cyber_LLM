/* Local presentation controls only: no requests, storage, keys, or model execution. */
(() => {
  'use strict';
  const status = document.createElement('p');
  status.className = 'visually-hidden';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  document.body.append(status);
  async function copy(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(text); return true; } catch (_) { /* local fallback */ }
    }
    const field = document.createElement('textarea');
    field.value = text;
    field.style.cssText = 'position:fixed;left:0;top:0;opacity:0';
    document.body.append(field); field.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
    field.remove(); return ok;
  }
  document.querySelectorAll('.copy-command').forEach(button => {
    button.addEventListener('click', async () => {
      const code = button.closest('.run-step').querySelector('pre');
      const ok = await copy(code.textContent);
      button.textContent = ok ? 'Copied' : 'Select command';
      status.textContent = ok ? 'Command copied. Review it before running in your terminal.' : 'Copy unavailable. Select and copy the command manually.';
      if (!ok) { const range = document.createRange(); range.selectNodeContents(code); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); }
      button.focus();
      window.setTimeout(() => { button.textContent = 'Copy command'; }, 2200);
    });
  });
  // Old section links remain useful, including links into closed disclosures.
  function revealHash() {
    let target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (_) { return; }
    if (!target) return;
    for (let parent = target.parentElement; parent; parent = parent.parentElement) {
      if (parent.tagName === 'DETAILS') parent.open = true;
    }
    if (location.hash) requestAnimationFrame(() => target.scrollIntoView({block:'start'}));
  }
  window.addEventListener('hashchange', revealHash); revealHash();
  document.querySelectorAll('[data-diagram]').forEach(link => {
    link.addEventListener('click', event => {
      if (typeof HTMLDialogElement === 'undefined' || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      const dialog = document.createElement('dialog');
      dialog.className = 'diagram-dialog';
      dialog.setAttribute('aria-label', 'Architecture reference, enlarged');
      const bar = document.createElement('div'); bar.className = 'dialog-bar';
      const title = document.createElement('strong'); title.textContent = 'Architecture reference';
      const close = document.createElement('button'); close.type = 'button'; close.textContent = 'Close';
      bar.append(title, close); dialog.append(bar);
      const img = link.closest('figure').querySelector('img').cloneNode();
      img.removeAttribute('loading'); dialog.append(img); document.body.append(dialog);
      close.addEventListener('click', () => dialog.close());
      dialog.addEventListener('close', () => { dialog.remove(); link.focus(); }, {once:true});
      dialog.showModal(); close.focus();
    });
  });
})();
