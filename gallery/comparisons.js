'use strict';
(() => {
  const el = id => document.getElementById('comparison-' + id);
  const section = document.getElementById('comparisons');
  const before = el('before'), after = el('after');
  const statuses = {corrected: 'Convention corrected', partial: 'Partial correction', candidate: 'Candidate · needs validation', diagnostic: 'Camera-frame diagnostic', no_validated_change: 'No validated after'};
  let manifest, selected, view, active = [], ready = new Set(), generation = 0;
  let wanted = false, animation = 0, starting = false;
  const node = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
  const time = seconds => { const tenths = Math.round(Math.max(0, seconds) * 10); return `${Math.floor(tenths / 600)}:${String(Math.floor(tenths / 10) % 60).padStart(2, '0')}.${tenths % 10}`; };
  const link = (label, url) => { const a = node('a', label); a.href = url; return a; };
  const pauseMedia = () => active.forEach(v => v.pause());
  function updateTime() {
    if (!view) return;
    const t = Math.min(view.duration, before.currentTime || 0);
    el('seek').value = t;
    el('time').textContent = `${time(t)} / ${time(view.duration)}`;
    el('seek').setAttribute('aria-valuetext', `${t.toFixed(1)} of ${view.duration.toFixed(1)} seconds`);
  }
  function pause() {
    wanted = false; cancelAnimationFrame(animation); pauseMedia();
    if (active.length === 2 && ready.size === 2 && Math.abs(after.currentTime - before.currentTime) > .0001) {
      after.currentTime = Math.min(before.currentTime, view.duration);
    }
    el('play').textContent = view?.after ? 'Play both' : 'Play reference';
  }
  function fail(message) { pause(); el('error').textContent = message; }
  function tick() {
    if (!wanted) return;
    updateTime();
    if (active.some(v => v.ended) || before.currentTime >= view.duration - .015) { pause(); return; }
    if (active.every(v => v.readyState >= 3) && active.some(v => v.paused)) resume();
    if (active.every(v => v.readyState >= 3) && active.length === 2 && !after.seeking
        && Math.abs(after.currentTime - before.currentTime) > .08) after.currentTime = before.currentTime;
    animation = requestAnimationFrame(tick);
  }
  async function resume() {
    if (!wanted || starting || active.some(v => v.readyState < 3)) return;
    starting = true; const token = generation;
    try {
      await Promise.all(active.map(v => v.play()));
      if (token !== generation) return;
      if (!wanted) pauseMedia();
    } catch (error) {
      if (token === generation && wanted && error.name !== 'AbortError') fail('Playback could not start. Try Play again or download the videos.');
    } finally { if (token === generation) starting = false; }
  }
  function seek(seconds) {
    pause();
    const t = Math.max(0, Math.min(seconds, Math.max(0, view.duration - .02)));
    for (const video of active) video.currentTime = t;
    updateTime();
  }
  function loadView(index, initialTime) {
    pause(); generation++; starting = false; ready = new Set();
    view = selected.views[index]; active = view.after ? [before, after] : [before];
    el('play').textContent = view.after ? 'Play both' : 'Play reference';
    el('error').textContent = ''; el('play').disabled = true; el('seek').disabled = true;
    el('seek').max = view.duration; el('seek').value = 0;
    section.style.setProperty('--comparison-aspect', `${view.before.width}/${view.before.height}`);
    el('after').hidden = !view.after; el('unavailable').hidden = !!view.after;
    el('after-download').hidden = !view.after;
    el('after-label').textContent = view.after ? (view.after_label || selected.after.label) : 'After · pending validation';
    el('before-label').textContent = view.before_label || selected.before.label;
    el('unavailable-note').textContent = view.unavailable_note || (selected.id.startsWith('dexora')
      ? 'The camera-frame error is identified. A measured lens and mount calibration is still needed before replacing the trajectory.'
      : 'The candidate tracking fits failed validation. The released identity poses do not establish a tracked camera trajectory.');
    el('playback-note').textContent = view.playback_note || selected.playback_note || (view.after
      ? 'Linked playback and seeking · same episode and camera · no added time shift.'
      : 'Current reference only. No replacement projection or trajectory has passed validation.');
    el('provenance-links').replaceChildren();
    const token = generation;
    for (const [side, video] of [['before', before], ['after', after]]) {
      video.onloadedmetadata = null; video.oncanplay = null; video.onerror = null; video.onwaiting = null;
      video.pause(); video.removeAttribute('src'); video.load();
      el(side + '-spec').textContent = '';
      if (!view[side]) continue;
      const asset = view[side];
      el(side + '-spec').textContent = `${asset.fps.toFixed(1).replace('.0', '')} fps · ${asset.width} × ${asset.height}`;
      el(side + '-download').href = asset.url;
      const name = side === 'before' && !view.after ? 'Reference' : side[0].toUpperCase() + side.slice(1);
      el('provenance-links').append(link(name + ' render metadata ↗', selected[side].meta.url));
      video.onloadedmetadata = () => {
        if (token !== generation) return;
        video.currentTime = Math.max(0, Math.min(initialTime, view.duration - .02));
        ready.add(video);
        if (ready.size === active.length) { el('play').disabled = false; el('seek').disabled = false; updateTime(); }
      };
      video.oncanplay = () => { if (token === generation) resume(); };
      video.onwaiting = () => { if (token === generation && wanted) pauseMedia(); };
      video.onerror = () => { if (token === generation) fail('A comparison video could not load. Reload this page or use the download link.'); };
      video.playbackRate = Number(el('speed').value); video.src = asset.url; video.load();
    }
    updateTime();
  }
  function selectCase(id, writeHash = false) {
    const next = manifest.cases.find(c => c.id === id); if (!next) return;
    selected = next;
    for (const b of el('cases').children) b.setAttribute('aria-pressed', String(b.dataset.case === id));
    el('dataset').textContent = `${selected.dataset_id} · Episode ${selected.episode_index}`;
    el('case-title').textContent = selected.title;
    el('status').textContent = statuses[selected.status]; el('status').className = 'comparison-status ' + selected.status;
    el('finding').textContent = selected.finding; el('change').textContent = selected.change;
    el('remaining').replaceChildren(...selected.remaining.map(t => node('li', t)));
    el('evidence').replaceChildren();
    for (const item of selected.evidence) {
      const dd = node('dd'); dd.append(item.url ? link(item.value + ' ↗', item.url) : node('span', item.value));
      el('evidence').append(node('dt', item.label), dd);
    }
    el('related').replaceChildren();
    if (selected.related_dataset_ids.length) {
      el('related').append(node('span', 'Also applied in the gallery:'));
      for (const id of selected.related_dataset_ids) el('related').append(link(id.split('/').pop().replaceAll('_', ' ') + ' ↗', '#' + encodeURIComponent(id)));
    }
    el('gallery-link').href = '#' + encodeURIComponent(selected.dataset_id);
    el('view').replaceChildren();
    for (const [index, v] of selected.views.entries()) { const option = node('option', v.label); option.value = index; el('view').append(option); }
    const index = Math.max(0, selected.views.findIndex(v => v.view_id === selected.before.view_id));
    el('view').value = index; el('view').disabled = selected.views.length === 1;
    loadView(index, selected.inspection_seconds || 0);
    if (writeHash) history.replaceState(null, '', '#compare/' + selected.id);
  }
  function fromHash() {
    if (!manifest || !location.hash.startsWith('#compare/')) return;
    let id; try { id = decodeURIComponent(location.hash.slice(9)); } catch (_) { return; }
    if (!manifest.cases.some(c => c.id === id)) return;
    if (selected?.id !== id) selectCase(id);
    section.scrollIntoView({block: 'start'});
  }
  el('play').onclick = () => {
    if (wanted) { pause(); return; }
    if (before.currentTime >= view.duration - .05 || active.some(v => v.ended)) seek(0);
    wanted = true; el('error').textContent = ''; el('play').textContent = 'Pause'; resume(); tick();
  };
  el('seek').oninput = () => seek(Number(el('seek').value));
  el('speed').onchange = () => active.forEach(v => { v.playbackRate = Number(el('speed').value); });
  el('view').onchange = () => loadView(Number(el('view').value), before.currentTime);
  before.addEventListener('timeupdate', updateTime);
  for (const video of [before, after]) video.addEventListener('ended', pause);
  document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });
  new MutationObserver(() => { if (document.getElementById('player-dialog').open) pause(); }).observe(document.getElementById('player-dialog'), {attributes: true, attributeFilter: ['open']});
  window.addEventListener('hashchange', fromHash);
  async function loadComparisons() {
    try {
      const response = await fetch('comparisons.json', {cache: 'no-store'});
      if (response.status === 404) return; // Optional on galleries without a review bundle.
      if (!response.ok) throw new Error('HTTP ' + response.status);
      manifest = await response.json(); if (!manifest.cases?.length) return;
      el('title').textContent = manifest.title; el('description').textContent = manifest.description;
      for (const c of manifest.cases) {
        const button = node('button'); button.dataset.case = c.id;
        button.append(node('span', c.title.split(' · ')[0]), node('small', statuses[c.status]));
        button.onclick = () => selectCase(c.id, true); el('cases').append(button);
      }
      section.hidden = false; el('nav').hidden = false;
      selectCase(manifest.cases[0].id); fromHash();
      if (location.hash === '#comparisons') section.scrollIntoView({block: 'start'});
    } catch (error) {
      section.hidden = false; el('description').textContent = 'The comparison bundle could not load. Reload this page to retry.';
      section.querySelector('article').hidden = true;
    }
  }
  loadComparisons();
})();
