'use strict';
// Keep dated screening observations separate from the render's acceptance state.
(() => {
  let audit;
  const original = setView;
  function note() {
    if (!audit || !current) return;
    const row = audit.projects.find(p => p.project === current.project);
    if (!row || !['visible_mismatch', 'review', 'schematic_mismatch'].includes(row.status)) return;
    const host = document.getElementById('player-caveats');
    if (host.querySelector('.projection-audit-note')) return;
    const p = document.createElement('p'); p.className = 'projection-audit-note';
    p.append(document.createTextNode(`Public preview screen (${audit.date}; episode ${row.episode}): ${row.observation} `));
    const a = document.createElement('a');
    a.href = `evidence/public-projection-screen-20261016/#p${row.index}`;
    a.textContent = 'See the sampled public image and review limits ↗'; a.target = '_blank'; a.rel = 'noopener';
    p.append(a); host.append(p);
  }
  setView = function(index) { original(index); note(); };
  fetch('projection-audit.json', {cache: 'no-store'}).then(r => r.ok ? r.json() : null).then(x => {
    audit = x; note(); if (!audit) return;
    const nav = document.querySelector('.masthead-links');
    if (nav) { const a = document.createElement('a'); a.className = 'text-link projection-audit-link';
      a.href = 'evidence/public-projection-screen-20261016/'; a.textContent = '75-project projection screen ↗'; nav.prepend(a); }
  }).catch(() => {});
})();
