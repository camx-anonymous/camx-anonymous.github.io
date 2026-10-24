// Run with Node.js: node --test tools/tests/viewer.test.cjs
// Execute the dataset viewer's actual inline helpers without browser/npm dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'camx-dataset/index.html'), 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(source, {filename: 'camx-dataset/index.html'});
function section(start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a, `Missing source section: ${start}`);
  return source.slice(a, b);
}
function capHost() {
  const p = {}, stepper = {children: [{}, {}, {}]};
  const alt = {querySelector: () => stepper};
  return {p, alt, stepper, querySelector: s => s === 'p' ? p : alt};
}
const classes = () => ({add() {}, remove() {}, toggle() {}});
const decode = s => s.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
class Video {
  constructor(src) { Object.assign(this, {src, currentTime: 0, duration: 10, paused: true, readyState: 0, events: {}, plays: 0, loads: 0}); }
  addEventListener(type, fn, options) { (this.events[type] ||= []).push({fn, once: options?.once}); }
  emit(type) {
    const events = this.events[type] || [];
    this.events[type] = events.filter(e => !e.once);
    events.forEach(e => e.fn());
  }
  play() { this.plays++; if (this.paused) { this.paused = false; this.emit('play'); } return Promise.resolve(); }
  pause() { if (!this.paused) { this.paused = true; this.emit('pause'); } }
  removeAttribute(key) { delete this[key]; }
  load() { this.loads++; }
}
class Comparison {
  set innerHTML(value) {
    this.html = value;
    this.videos = [...value.matchAll(/<video src="([^"]*)"/g)].map(m => new Video(decode(m[1])));
    this.windows = this.videos.map(v => ({style: {}, firstChild: v, insertAdjacentHTML() {}}));
    this.button = {setAttribute(k, v) { this[k] = v; }};
    this.position = {value: 0};
    this.cap = value.includes('class="cap"') ? capHost() : null;
    this.panes = {classList: classes()};
    const selected = value.match(/<option value="([^"]*)" selected>/);
    this.picker = selected ? {value: decode(selected[1]), focus() { this.focused = true; }} : null;
  }
  get innerHTML() { return this.html; }
  querySelectorAll(s) { return s === 'video' ? this.videos : s === '.win' ? this.windows : []; }
  querySelector(s) { return ({'.ctl button': this.button, '.ctl input': this.position, '.cap': this.cap,
    '.panes': this.panes, '.clip-picker select': this.picker})[s] || null; }
  remove() { this.removed = true; }
}
function load(data = {}, rows = []) {
  const nodes = {stage: {classList: classes(), appendChild(cmp) { this.current = cmp; }},
    drawerBody: {querySelector: () => ({before(cmp) { nodes.stage.current = cmp; }})}};
  const context = vm.createContext({D: data, L: rows, P: Object.fromEntries((data.projects || []).map(p => [p.key, p])),
    input: null, $: id => nodes[id], matchMedia: () => ({matches: true, addEventListener() {}}),
    document: {createElement: () => new Comparison()}});
  vm.runInContext(section('const esc=', '\nconst human='), context);
  vm.runInContext(section('const RAW=', '\n\n// the heading'), context);
  vm.runInContext(section('let CMP=', '/* a caption and'), context);
  vm.runInContext(section('const CAPALT=', '/* data/captions.json'), context);
  return {context, nodes, run(code, input) {
    context.input = input;
    return JSON.parse(vm.runInContext(`JSON.stringify((${code}))`, context));
  }, open(row) { this.run('openCmp(input), null', row); return nodes.stage.current; }};
}
const clip = {key: 'robot', slug: 'episode', dataset: 'example', episode: 0, views: ['left', 'right']};
const fingerprint = {render_fingerprint: '1234567890abcdef'};
const rows = [{id: clip.dataset, project: 'robot', name: 'example', cams: [
  {name: 'left', w: 640, h: 480}, {name: 'right', w: 640, h: 480}]}];
const withClips = clips => ({projects: [{key: 'robot', overlays: clips}]});

test('explicit URLs override bases and preserve queries/fragments', () => {
  const viewer = load({raw_base: '/raw/', overlay_base: '/overlay/', poster_base: '/posters/'});
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
test('independent configured bases and legacy fallback paths', () => {
  assert.deepEqual(load({raw_base: '/new/raw/', overlay_base: '/new/overlay/', poster_base: '/new/posters/'})
    .run('clipUrls(input)', clip), {
    raw: '/new/raw/robot__episode.mp4', overlay: '/new/overlay/robot__episode.mp4', poster: '/new/posters/robot__episode.jpg'});
  assert.deepEqual(load().run('clipUrls(input)', clip), {
    raw: '../overlays/raw/robot__episode.mp4', overlay: '../overlays/videos/robot__episode.mp4',
    poster: '../overlays/raw/robot__episode.jpg'});
});
test('layout uses encoded uneven tile widths instead of source camera ratios', () => {
  assert.deepEqual(load({}, rows).run('tilesOf(input)', {...clip, tile_w: [640, 320], tile_h: 480}), {A: 2, X: [0, 2 / 3]});
});
test('layout falls back for legacy or invalid tile geometry', () => {
  const viewer = load({}, rows), fallback = {A: 8 / 3, X: [0, 0.5]};
  assert.deepEqual(viewer.run('tilesOf(input)', clip), fallback);
  for (const geometry of [{tile_w: [640], tile_h: 480}, {tile_w: [640, 0], tile_h: 480},
    {tile_w: [640, -1], tile_h: 480}, {tile_w: [640, Infinity], tile_h: 480},
    {tile_w: ['640', 320], tile_h: 480}, {tile_w: [640, 320], tile_h: 0},
    {tile_w: [640, 320], tile_h: NaN}, {tile_w: [640, 320], tile_h: '480'}]) {
    assert.deepEqual(viewer.run('tilesOf(input)', {...clip, ...geometry}), fallback);
  }
  for (const invalidRows of [[], [{id: clip.dataset}], [{id: clip.dataset, cams: [{name: 'left', w: 640, h: 0}]}]]) {
    assert.deepEqual(load({}, invalidRows).run('tilesOf(input)', clip), fallback);
  }
});
test('owned clips exclude siblings; unowned rows retain the matching rig and same-task restriction', () => {
  const owner = {...rows[0], station: 'east', variant: 'narrow'};
  const borrow = {...owner, id: 'borrow'}, absent = {...owner, id: 'absent'};
  const otherRows = [{...owner, id: 'west', station: 'west'}, {...owner, id: 'east'}];
  const own = [clip, {...clip, slug: 'older', episode: 4}];
  const siblings = [{...clip, dataset: 'west', slug: 'west', also_for: ['example', 'borrow']},
    {...clip, dataset: 'east', slug: 'east', also_for: ['example', 'borrow'], grippers: {left: {model: 'narrow'}}},
    {...clip, dataset: 'unrelated', slug: 'unrelated'}];
  const viewer = load(withClips([...siblings, ...own]), [owner, borrow, absent, ...otherRows]);
  assert.deepEqual(viewer.run('clipsOf(input).map(o => o.slug)', owner), ['episode', 'older']);
  assert.deepEqual(viewer.run('clipsOf(input).map(o => o.slug)', borrow), ['east', 'west']);
  assert.equal(viewer.run('clipOf(input).slug', borrow), 'east');
  assert.deepEqual(viewer.run('clipsOf(input)', absent), []);
  const cmp = viewer.open(borrow);
  assert.ok(cmp.innerHTML.includes('(sibling dataset, same rig)'));
  assert.ok(!cmp.innerHTML.includes('value="robot__unrelated"'));
});
test('every published clip is reachable through its own dataset row, including additional episodes', () => {
  const data = JSON.parse(fs.readFileSync(path.join(root, 'data/datasets.json'), 'utf8'));
  const viewer = load(data, data.datasets);
  const expected = data.projects.flatMap(p => p.overlays.map(o => `${o.key}__${o.slug}`));
  const reachable = viewer.run('D.datasets.flatMap(r => clipsOf(r).filter(o => o.dataset === r.id)).map(clipName)');
  assert.equal(new Set(expected).size, expected.length, 'Published clip identifiers must be unique');
  assert.deepEqual([...new Set(reachable)].sort(), expected.sort());
  assert.ok(expected.length > new Set(data.projects.flatMap(p => p.overlays.map(o => o.dataset))).size,
    'Catalog covers additional clips that the default card alone cannot reach');
});
test('comparison and card consume selected URLs with safe HTML attributes', () => {
  const own = {...clip, ...fingerprint, tile_w: [640, 320], tile_h: 480,
    raw_url: 'https://clips.example/raw.mp4?download=1&x="', overlay_url: 'https://clips.example/overlay.mp4?download=1'};
  const viewer = load({...withClips([own]), poster_base: '/posters/"/'}, rows), cmp = viewer.open(rows[0]);
  assert.ok(cmp.innerHTML.includes('src="https://clips.example/raw.mp4?download=1&amp;x=&quot;&amp;v=1234567890ab"'));
  assert.ok(cmp.innerHTML.includes('src="https://clips.example/overlay.mp4?download=1&amp;v=1234567890ab"'));
  assert.ok(cmp.innerHTML.includes('left:66.667%'));
  Object.assign(viewer.context, {sel: new Set(), ck: () => '', human: x => x, fmtH: String, ML: {}});
  vm.runInContext(section('const title=', '\nfunction render('), viewer.context);
  assert.ok(viewer.run('card(input)', rows[0]).includes('src="/posters/&quot;/robot__episode.jpg?v=1234567890ab"'));
});
test('switching clips updates paired media, geometry, captions and seek; reopening remembers each dataset', () => {
  const first = {...clip, task: 'First task||First alternate', tile_w: [640, 320], tile_h: 480};
  const second = {...clip, slug: 'second', episode: 3, tile_w: [320, 640], tile_h: 480,
    captions: [[0, ['Reach', 'Approach']], [2, 'Lift||Raise']]};
  const raw = {...clip, slug: 'raw', episode: 8, mode: 'raw', task: ['Raw task', 'Raw alternate'], views: ['left']};
  const otherRow = {...rows[0], id: 'other'}, otherClip = {...clip, dataset: 'other', slug: 'other', task: 'Other task'};
  const viewer = load(withClips([first, second, raw, otherClip]), [...rows, otherRow]);
  const old = viewer.open(rows[0]);
  assert.equal(old.cap.p.textContent, 'First task');
  assert.ok(old.innerHTML.includes('<label for="cmpClip">Clip / episode · 3 available</label>'));
  old.picker.value = 'robot__second'; old.picker.onchange();
  const selected = viewer.nodes.stage.current;
  assert.ok(old.removed && old.videos.every(v => v.paused && !v.src && v.loads === 1));
  old.videos.forEach(v => v.emit('loadeddata'));
  assert.ok(old.videos.every(v => v.plays === 0), 'Stale readiness events cannot restart a removed viewer');
  assert.ok(selected.picker.focused);
  assert.deepEqual(selected.videos.map(v => v.src), ['../overlays/raw/robot__second.mp4', '../overlays/videos/robot__second.mp4']);
  assert.ok(selected.innerHTML.includes('left:33.333%'));
  assert.ok(selected.windows.every(w => w.style.aspectRatio === 2));
  assert.equal(selected.cap.p.textContent, 'Reach');
  selected.cap.stepper.children[2].onclick();
  assert.equal(selected.cap.p.textContent, 'Approach');
  selected.position.value = 500; selected.position.oninput();
  assert.ok(selected.videos.every(v => v.currentTime === 5));
  assert.equal(selected.cap.p.textContent, 'Lift');
  selected.cap.stepper.children[2].onclick();
  assert.equal(selected.cap.p.textContent, 'Raise');
  selected.videos[0].emit('loadeddata'); selected.videos[0].emit('error');
  assert.ok(selected.videos.every(v => v.plays === 0), 'One video cannot count as both ready companions');
  selected.videos[1].emit('loadeddata');
  assert.ok(selected.videos.every(v => !v.paused && v.plays === 1));
  selected.videos[1].emit('error');
  assert.ok(selected.videos.every(v => !v.paused), 'A late error must not toggle playback again');
  viewer.run('closeCmp(), null');
  const reopened = viewer.open(rows[0]);
  assert.equal(reopened.picker.value, 'robot__second');
  assert.ok(reopened.videos.every(v => v.currentTime === 0));
  reopened.picker.value = 'robot__raw'; reopened.picker.onchange();
  const rawCmp = viewer.nodes.stage.current;
  assert.equal(rawCmp.videos.length, 1);
  assert.equal(rawCmp.videos[0].src, '../overlays/raw/robot__raw.mp4');
  assert.equal(rawCmp.cap.p.textContent, 'Raw task');
  rawCmp.videos[0].emit('loadeddata');
  assert.equal(rawCmp.videos[0].plays, 1);
  const otherCmp = viewer.open(otherRow);
  assert.equal(otherCmp.cap.p.textContent, 'Other task');
  assert.ok(rawCmp.removed && rawCmp.videos[0].paused && !rawCmp.videos[0].src);
  assert.equal(viewer.open(rows[0]).picker.value, 'robot__raw');
  assert.equal(viewer.run('openCmp(input, "robot__unrelated"), clipChoices.get(input.id)', rows[0]), 'robot__episode');
});
test('caption wordings preserve both arrays and || strings, deduplicate and reset on new captions', () => {
  for (const words of ['Pick up||Lift||Pick up', ['Pick up', 'Lift', 'Pick up']]) {
    const viewer = load(), host = capHost();
    viewer.context.host = host;
    vm.runInContext('const box = capBox(host)', viewer.context);
    viewer.run('box.set(input), null', words);
    assert.equal(host.p.textContent, 'Pick up');
    assert.equal(host.alt.hidden, false);
    assert.equal(host.stepper.children[1].textContent, '1 / 2');
    host.stepper.children[2].onclick();
    assert.equal(host.p.textContent, 'Lift');
    viewer.run('box.set(input), null', 'Place down');
    assert.equal(host.p.textContent, 'Place down');
    assert.equal(host.alt.hidden, true);
  }
});
test('dataset drawer keeps clip help inline without linking to the retired gallery', () => {
  assert.ok(!/href="\.\.\/overlays\/(?:#|\")/.test(html));
  assert.ok(html.includes('choose a clip / episode in the viewer'));
});
