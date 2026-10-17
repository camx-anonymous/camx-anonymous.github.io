'use strict';
// Public mirrors can serve one stitched file and crop camera views in the player.
(() => {
  const embedded = new URLSearchParams(location.search).has('embed');
  if (embedded) document.documentElement.classList.add('gallery-embedded');
  const original = setView;
  let crop = null;
  function size() {
    const player = document.getElementById('player');
    if (!crop) { player.removeAttribute('style'); return; }
    const dialog = document.getElementById('player-dialog');
    const padding = parseFloat(getComputedStyle(dialog).paddingLeft) * 2;
    const width = Math.min(dialog.clientWidth - padding, innerHeight * .57 * crop.aspect);
    player.style.width = width + 'px'; player.style.height = width / crop.aspect + 'px';
    player.style.objectFit = 'cover';
    player.style.objectPosition = `${crop.width < 1 ? 100 * crop.left / (1 - crop.width) : 0}% 50%`;
    player.style.marginInline = 'auto';
  }
  setView = function(index) {
    original(index); crop = current.views[index].crop || null; size();
    if (crop) document.getElementById('download-video').textContent = 'Download camera strip ↓';
    else document.getElementById('download-video').textContent = 'Download video ↓';
  };
  addEventListener('resize', size);
  new ResizeObserver(size).observe(document.getElementById('player-dialog'));
})();
