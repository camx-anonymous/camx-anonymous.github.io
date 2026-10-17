'use strict';
// The dataset browser uses the published copy of the local projection gallery.
// Historical multi-episode raw/overlay comparisons remain at /overlays/.
(() => {
  let gallery = null;
  const originalLoad = load, originalThumb = thumb, originalOpen = openCmp;
  const choose = r => gallery?.clips.find(c => c.id === r.id)
    || gallery?.clips.find(c => c.project === r.project);
  load = async function() {
    try { const r = await fetch('../gallery/gallery.json', {cache: 'no-store'});
      if (r.ok) gallery = await r.json(); } catch (_) {}
    return originalLoad();
  };
  thumb = function(r) {
    const c = choose(r);
    return c?.poster ? {poster: '../gallery/' + c.poster} : originalThumb(r);
  };
  openCmp = function(r) {
    const c = choose(r); if (!c) return originalOpen(r);
    closeCmp();
    const el = CMP = document.createElement('div'); el.className = 'cmp';
    const header = document.createElement('div'); header.className = 'hd';
    const title = document.createElement('b'); title.textContent = 'Current projection preview';
    const a = document.createElement('a'); a.href = '../gallery/#' + encodeURIComponent(c.id);
    a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'Open full gallery ↗';
    header.append(title, a); el.append(header);
    if (c.id !== r.id) { const p = document.createElement('p'); p.style.padding = '0 16px';
      p.textContent = 'Representative of this project: ' + c.id; el.append(p); }
    const frame = document.createElement('iframe');
    frame.src = '../gallery/?embed=1#' + encodeURIComponent(c.id);
    frame.title = c.id + ' projection preview'; frame.allow = 'fullscreen';
    frame.style.cssText = 'width:100%;height:70vh;min-height:420px;border:0;display:block;background:#f8f9f6';
    el.append(frame); placeCmp();
  };
  const originalDrawer = drawer;
  drawer = function(id) {
    originalDrawer(id);
    const r = L.find(x => x.id === id), c = r && choose(r);
    if (!c) return;
    for (const a of document.querySelectorAll('#drawerBody a[href^="../overlays/#"]')) {
      a.href = '../gallery/#' + encodeURIComponent(c.id); a.textContent = 'Current projection gallery';
    }
  };
})();
