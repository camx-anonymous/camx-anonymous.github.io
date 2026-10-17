'use strict';
const $ = id => document.getElementById(id);
let data, family = '', mode = 'all', page = 0, current = null;
const perPage = 24;
const modeNames = {urdf: 'URDF', cad: 'CAD', primitive: 'STAND-IN', axes: 'AXES', raw: 'RAW ONLY', unknown: 'UNKNOWN'};
const displayMode = clip => clip.review ? 'axes' : clip.mode;
const duration = seconds => { const total = Math.round(seconds); return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`; };
const make = (tag, cls, text) => { const el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el; };
function updateFamilies() {
  const counts = new Map();
  for (const c of data.clips) counts.set(c.family, (counts.get(c.family) || 0) + 1);
  $('families').replaceChildren();
  for (const [name, count] of [['', data.total], ...[...counts].sort()]) {
    const b = make('button', family === name ? 'active' : '', name || 'All embodiments');
    b.setAttribute('aria-pressed', String(family === name)); b.append(make('span', '', String(count)));
    b.onclick = () => { family = name; page = 0; $('project').value = ''; updateFamilies(); render(); };
    $('families').append(b);
  }
}
function render() {
  if (!data) return;
  const query = $('search').value.trim().toLowerCase(), project = $('project').value;
  const clips = data.clips.filter(c => (!family || c.family === family) && (!project || c.project === project)
    && (!$('readiness') || !$('readiness').value || c.readiness === $('readiness').value)
    && (mode === 'all' || (mode === 'cad' ? ['cad', 'urdf'].includes(displayMode(c)) : mode === displayMode(c)))
    && (!query || `${c.id} ${c.title} ${c.embodiment} ${c.variant || ''} ${c.readiness || ''} ${(c.caveats || []).join(' ')}`.toLowerCase().includes(query)));
  const pages = Math.max(1, Math.ceil(clips.length / perPage)); page = Math.min(page, pages - 1);
  $('result-heading').textContent = family ? `${family} samples` : 'All samples';
  $('result-count').textContent = `${clips.length} ${clips.length === 1 ? 'sample' : 'samples'}`;
  $('grid').replaceChildren();
  for (const c of clips.slice(page * perPage, (page + 1) * perPage)) {
    const card = make('article', 'card'), b = make('button', 'thumbnail');
    b.setAttribute('aria-label', `Play ${c.id}`);
    if (c.views.length) {
      if (c.poster) { const im = make('img'); im.src = c.poster; im.alt = `${c.title} — ${modeNames[c.mode]} projection preview`; im.loading = 'lazy'; im.decoding = 'async'; b.append(im); }
      b.append(make('span', 'play', '▶'), make('span', 'duration', duration(c.duration || 0)));
      b.onclick = () => openClip(c.id);
    } else { b.disabled = true; b.append(make('span', 'pending-label', c.status === 'failed' ? 'RENDER FAILED' : 'AWAITING RENDER')); }
    const tags = make('div', 'card-meta'); tags.append(make('span', 'family-tag', c.family), make('span', `mode-tag mode-${displayMode(c)}`, c.review ? 'CAMERA-FRAME REVIEW' : (modeNames[c.mode] || c.mode)));
    if (c.readiness) tags.append(make('span', 'family-tag', c.readiness.toUpperCase()));
    const cameraCount = Math.max(0, c.views.length - 1);
    card.append(b, tags, make('h3', '', c.title), make('p', 'card-sub', `${c.project.split('/')[1]} · Episode ${c.episode ?? 0}${cameraCount ? ` · ${cameraCount} camera${cameraCount === 1 ? '' : 's'}` : ''}`));
    if (c.geometry_status) card.append(make('p', 'card-warning', c.geometry_status.replaceAll('_', ' ').toUpperCase()));
    if (c.caveats.some(x => x.startsWith('Known calibration'))) card.append(make('p', 'card-warning', 'CALIBRATION LIMITATION'));
    if (c.status === 'failed') card.append(make('p', 'card-warning', c.error || 'See render metadata'));
    $('grid').append(card);
  }
  if (!clips.length) $('grid').append(make('p', 'empty', 'No samples match these filters. Try another project or search term.'));
  $('previous').disabled = page === 0; $('next').disabled = page >= pages - 1;
  $('page-label').textContent = `${page + 1} / ${pages}`;
}
function setView(index) {
  const view = current.views[index];
  $('player').src = view.url; $('player').poster = view.reviewed ? '' : (current.poster || '');
  $('download-video').href = view.url;
  $('meta-link').href = view.meta_url || current.meta_url;
  $('player-stats').textContent = `${view.reviewed ? current.review.label : modeNames[current.mode]} · EP ${current.episode ?? 0} · ${duration(view.duration ?? current.duration)} · ${Number(view.fps ?? current.fps).toFixed(1)} FPS${current.readiness ? ' · ' + current.readiness.toUpperCase() : ''}`;
  $('player-caveats').replaceChildren();
  const notes = view.reviewed ? [current.review.note, view.note] : [current.reason, ...current.caveats];
  for (const text of notes.filter(Boolean)) $('player-caveats').append(make('p', '', text));
  if (current.review) {
    const a = make('a', 'text-link', 'Compare previous and latest camera frames ↗');
    a.href = '#compare/' + current.review.case_id;
    const destination = a.href;
    a.onclick = event => {
      event.preventDefault();
      $('player-dialog').addEventListener('close', () => { location.href = destination; }, {once: true});
      closePlayer();
    };
    const p = make('p'); p.append(a); $('player-caveats').append(p);
  }
  for (const link of current.evidence_links || []) { const a = make('a', 'text-link', link.label + ' ↗'); a.href = link.url; const p = make('p'); p.append(a); $('player-caveats').append(p); }
  $('recipe-note').textContent = view.reviewed ? 'Latest reviewed camera display. ' + current.review.note :
    (current.recipe_note || 'Recipe recorded in render metadata.')
    + (current.renderer ? ` Renderer: ${current.renderer}.` : '')
    + (current.lens_backends ? ' Camera projection: ' + Object.entries(current.lens_backends).map(([k, v]) => `${k}: ${v}`).join('; ') + '.' : '')
    + (current.accept ? ` Geometry acceptance: ${current.accept}.` : '');
}
function openClip(id) {
  const c = data.clips.find(c => c.id === id); if (!c || !c.views.length) return;
  current = c.review ? {...c, views: [...c.review.views, ...c.views.map(v => ({...v, label: (c.mode === 'raw' ? 'Original raw · ' : 'Original · ') + v.label}))]} : c;
  $('player-title').textContent = c.title; $('player-project').textContent = c.id;
  $('view-select').replaceChildren(); current.views.forEach((v, i) => { const o = make('option', '', v.label); o.value = i; $('view-select').append(o); });
  $('input-hash').textContent = c.input_manifest_sha256 ? `Input manifest SHA-256: ${c.input_manifest_sha256}` : '';
  $('sample-link').href = c.sample_url; $('meta-link').href = c.meta_url;
  setView(0); if (!$('player-dialog').open) $('player-dialog').showModal();
  history.replaceState(null, '', '#' + encodeURIComponent(c.id));
}
function closePlayer() { $('player-dialog').close(); }
window.addEventListener('hashchange', () => {
  if (!data) return;
  if (location.hash) { try { openClip(decodeURIComponent(location.hash.slice(1))); } catch (_) {} }
  else if ($('player-dialog').open) closePlayer();
});
$('player-dialog').addEventListener('close', () => { if ($('player-dialog').open) return; $('player').pause(); $('player').removeAttribute('src'); $('player').load(); current = null; history.replaceState(null, '', location.pathname + location.search); });
$('player-dialog').addEventListener('click', e => { if (e.target === $('player-dialog')) { const r = e.target.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) closePlayer(); } });
$('close-player').onclick = closePlayer;
$('view-select').onchange = () => setView(Number($('view-select').value));
$('search').oninput = () => { page = 0; render(); };
$('project').onchange = () => { page = 0; render(); };
if ($('readiness')) $('readiness').onchange = () => { page = 0; render(); };
for (const b of document.querySelectorAll('[data-mode]')) b.onclick = () => { mode = b.dataset.mode; page = 0; for (const other of document.querySelectorAll('[data-mode]')) { other.classList.toggle('active', other === b); other.setAttribute('aria-pressed', String(other === b)); } render(); };
for (const [id, direction] of [['previous', -1], ['next', 1]]) $(id).onclick = () => { page += direction; render(); document.querySelector('.toolbar').scrollIntoView({behavior: 'smooth', block: 'start'}); };
async function load() {
  try {
    const [response, reviews] = await Promise.all([
      fetch('gallery.json', {cache: 'no-store'}),
      fetch('comparisons.json', {cache: 'no-store'}).then(r => r.ok ? r.json() : null).catch(() => null),
    ]);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const first = !data; data = await response.json();
    for (const review of reviews?.cases || []) {
      const config = review.gallery_review;
      const clip = data.clips.find(c => c.id === review.dataset_id && c.episode === review.episode_index);
      if (!config || review.status !== 'diagnostic' || !review.after?.overlay || !clip || !clip.input_manifest_sha256
          || clip.input_manifest_sha256 !== review.alignment?.input_manifest_sha256_after) continue;
      const views = review.views.filter(v => v.after).map(v => ({...v.after,
        label: 'Latest review · ' + v.label, reviewed: true, view_id: v.view_id,
        note: v.gallery_note || v.playback_note || review.playback_note, meta_url: review.after.meta.url}));
      const preferred = views.findIndex(v => v.view_id === config.default_view_id);
      if (preferred < 0) continue;
      views.unshift(...views.splice(preferred, 1));
      clip.review = {...config, case_id: review.id, views};
    }
    $('total').textContent = data.total.toLocaleString(); $('projects').textContent = data.project_count;
    $('cad').textContent = (data.mode_counts.cad || 0) + (data.mode_counts.urdf || 0);
    const ready = (data.counts.ok || 0) + (data.counts.raw || 0); $('complete').textContent = ready;
    $('build-status').textContent = data.counts.pending ? `RENDERING · ${ready} / ${data.total} ready · ${data.counts.pending} pending${data.counts.failed ? ` · ${data.counts.failed} failed` : ''} · This gallery refreshes automatically.` : `RENDER COMPLETE · ${ready} playable videos${data.counts.failed ? ` · ${data.counts.failed} failed` : ' · No render failures'}`;
    $('build-time').textContent = 'BUILT ' + new Date(data.built_at).toISOString().slice(0, 10);
    if (first) { for (const name of [...new Set(data.clips.map(c => c.project))].sort()) { const o = make('option', '', name); o.value = name; $('project').append(o); } updateFamilies(); }
    render();
    if (first && location.hash) { try { openClip(decodeURIComponent(location.hash.slice(1))); } catch (_) {} }
    if (data.counts.pending) setTimeout(load, 15000);
  } catch (error) { $('build-status').textContent = `Gallery could not load: ${error.message}. Retrying…`; setTimeout(load, 15000); }
}
load();
