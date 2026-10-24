// Run with Node.js: node --test tools/tests/viewer.test.cjs
// Execute the actual inline viewer helpers, without a browser or npm dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const scripts = Object.fromEntries(['camx-dataset', 'overlays'].map(page => {
  const html = fs.readFileSync(path.join(root, page, 'index.html'), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  new vm.Script(script, {filename: `${page}/index.html`});
  return [page, script];
}));
function section(source, start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a, `Missing source section: ${start}`);
  return source.slice(a, b);
}
function load(page, data = {}, rows = []) {
  const nodes = Object.fromEntries(['content', 'clipSummary', 'pending', 'pendingBody'].map(id => [id, {style: {}}]));
  const context = vm.createContext({D: data, L: rows, input: null,
    document: {getElementById: id => nodes[id], querySelectorAll: () => []},
    CamxCatalog: {load: () => new Promise(() => {})},
    fetch: () => new Promise(() => {})});
  if (page === 'overlays') {
    vm.runInContext(scripts[page], context);
    context.data = data;
    vm.runInContext('D = data', context);
  } else {
    vm.runInContext(section(scripts[page], 'const RAW=', 'const clipJaws='), context);
    vm.runInContext(section(scripts[page], 'function tilesOf(', '// the short name'), context);
  }
  return {context, nodes, run(code, input) {
    context.input = input;
    return JSON.parse(vm.runInContext(`JSON.stringify((${code}))`, context));
  }};
}
const clip = {key: 'robot', slug: 'episode', dataset: 'example', episode: 0, views: ['left', 'right']};
const fingerprint = {render_fingerprint: '1234567890abcdef'};
for (const page of Object.keys(scripts)) {
  test(`${page}: explicit URLs override bases and preserve queries/fragments`, () => {
    const viewer = load(page, {raw_base: '/raw/', overlay_base: '/overlay/', poster_base: '/posters/'});
    const urls = viewer.run('clipUrls(input)', {...clip, ...fingerprint,
      raw_url: 'https://clips.example/raw.mp4?token=a%2Fb&download=1#t=2',
      overlay_url: 'https://clips.example/overlay.mp4?download=1'});
    assert.deepEqual(urls, {
      raw: 'https://clips.example/raw.mp4?token=a%2Fb&download=1&v=1234567890ab#t=2',
      overlay: 'https://clips.example/overlay.mp4?download=1&v=1234567890ab',
      poster: '/posters/robot__episode.jpg?v=1234567890ab'});
    assert.equal(viewer.run('clipVersion(input, {})', 'clip.mp4?token=abc#t=1'), 'clip.mp4?token=abc#t=1');
    for (const url of ['clip.mp4?', 'clip.mp4?download=1&', 'clip.mp4#t=2']) {
      const result = viewer.run('clipVersion(input, {render_fingerprint:"a&b"})', url);
      const parsed = new URL(result, 'https://clips.example/');
      assert.equal(parsed.searchParams.get('v'), 'a&b');
      assert.ok(!result.includes('?&') && !result.includes('&&'));
      if (url.endsWith('#t=2')) assert.equal(parsed.hash, '#t=2');
    }
  });
  test(`${page}: independent configured bases and legacy fallback paths`, () => {
    assert.deepEqual(load(page, {raw_base: '/new/raw/', overlay_base: '/new/overlay/', poster_base: '/new/posters/'})
      .run('clipUrls(input)', clip), {
      raw: '/new/raw/robot__episode.mp4', overlay: '/new/overlay/robot__episode.mp4', poster: '/new/posters/robot__episode.jpg'});
    const urls = load(page).run('clipUrls(input)', clip);
    assert.deepEqual(urls, page === 'overlays' ? {
      raw: 'raw/robot__episode.mp4', overlay: 'videos/robot__episode.mp4', poster: 'posters/robot__episode.jpg'} : {
      raw: '../overlays/raw/robot__episode.mp4', overlay: '../overlays/videos/robot__episode.mp4',
      poster: '../overlays/raw/robot__episode.jpg'});
  });
}
test('example-clips rendering selects raw-only/release clips and escapes URL attributes', () => {
  const viewer = load('overlays', {poster_base: '/posters/"<&/', projects: [{
    key: 'robot', embodiments: {arm: 1}, datasets: 1, hours: 1,
    overlays: [{...clip, ...fingerprint, overlay_url: 'https://clips.example/overlay.mp4?x="<&'},
      {...clip, mode: 'raw', raw_url: 'https://clips.example/raw.mp4?download=1&x=2'}]}]});
  vm.runInContext('render()', viewer.context);
  assert.equal(viewer.nodes.clipSummary.textContent, '2 clips across 1 projects · 1 projections · 1 raw-only clips');
  const html = viewer.nodes.content.innerHTML;
  assert.ok(html.includes('data-src="https://clips.example/overlay.mp4?x=&quot;&lt;&amp;v=1234567890ab"'));
  assert.ok(html.includes('data-src="https://clips.example/raw.mp4?download=1&amp;x=2"'));
  assert.ok(html.includes('src="/posters/&quot;&lt;&amp;/robot__episode.jpg?v=1234567890ab"'));
});
const rows = [{id: clip.dataset, cams: [{name: 'left', w: 640, h: 480}, {name: 'right', w: 640, h: 480}]}];
test('dataset layout uses encoded uneven tile widths instead of source camera ratios', () => {
  const viewer = load('camx-dataset', {}, rows);
  assert.deepEqual(viewer.run('tilesOf(input)', {...clip, tile_w: [640, 320], tile_h: 480}), {A: 2, X: [0, 2 / 3]});
});
test('dataset layout falls back for legacy or invalid tile geometry', () => {
  const viewer = load('camx-dataset', {}, rows);
  const fallback = {A: 8 / 3, X: [0, 0.5]};
  assert.deepEqual(viewer.run('tilesOf(input)', clip), fallback);
  for (const geometry of [{tile_w: [640], tile_h: 480}, {tile_w: [640, 0], tile_h: 480},
    {tile_w: [640, -1], tile_h: 480}, {tile_w: [640, Infinity], tile_h: 480},
    {tile_w: ['640', 320], tile_h: 480}, {tile_w: [640, 320], tile_h: 0},
    {tile_w: [640, 320], tile_h: NaN}, {tile_w: [640, 320], tile_h: '480'}]) {
    assert.deepEqual(viewer.run('tilesOf(input)', {...clip, ...geometry}), fallback);
  }
  for (const invalidRows of [[], [{id: clip.dataset}], [{id: clip.dataset, cams: [{name: 'left', w: 640, h: 0}]}]]) {
    assert.deepEqual(load('camx-dataset', {}, invalidRows).run('tilesOf(input)', clip), fallback);
  }
});
test('dataset comparison and card consume selected URLs with safe HTML attributes', () => {
  const viewer = load('camx-dataset', {poster_base: '/posters/"/'}, rows);
  const source = scripts['camx-dataset'];
  const video = {readyState: 0, addEventListener() {}};
  const node = {style: {}, classList: {toggle() {}}};
  const element = {querySelectorAll: selector => selector === 'video' ? [video, video] : [],
    querySelector: selector => selector === '.cap' ? null : node};
  Object.assign(viewer.context, {clipOf: () => ({...clip, ...fingerprint, tile_w: [640, 320], tile_h: 480,
    raw_url: 'https://clips.example/raw.mp4?download=1&x="', overlay_url: 'https://clips.example/overlay.mp4?download=1'}),
    closeCmp() {}, placeCmp() {}, clipNote: () => '', viewTag: x => x, sel: new Set(),
    ck: () => '', human: x => x, fmtH: x => String(x), ML: {}, CAPALT: ''});
  viewer.context.document.createElement = () => element;
  vm.runInContext(section(source, 'const esc=', '\nconst human='), viewer.context);
  vm.runInContext(section(source, 'function openCmp(', '/* a caption and'), viewer.context);
  viewer.run('openCmp(input), null', {});
  assert.ok(element.innerHTML.includes('src="https://clips.example/raw.mp4?download=1&amp;x=&quot;&amp;v=1234567890ab"'));
  assert.ok(element.innerHTML.includes('src="https://clips.example/overlay.mp4?download=1&amp;v=1234567890ab"'));
  assert.ok(element.innerHTML.includes('left:66.667%'));
  vm.runInContext(section(source, 'function thumb(', '\n\n// the heading'), viewer.context);
  vm.runInContext(section(source, 'const title=', '\nfunction render('), viewer.context);
  assert.ok(viewer.run('card(input)', {id: 'example', name: 'example'}).includes('src="/posters/&quot;/robot__episode.jpg?v=1234567890ab"'));
});
