// Run: node --test tools/tests/*.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {webcrypto, createHash} = require('node:crypto');
const test = require('node:test');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const script = fs.readFileSync(path.join(root, 'assets/catalog.js'), 'utf8');
const context = vm.createContext({TextEncoder, URL, btoa, crypto: webcrypto});
vm.runInContext(script, context);
const {load} = context.CamxCatalog;
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'camx-catalog-test-'));
process.on('exit', () => fs.rmSync(temp, {recursive: true, force: true}));
const catalog = {
  projects: [{key: 'robot/project', overlays: [{key: 'robot_project', slug: 'task__ep2',
    dataset: 'robot/project/task', episode: 2, export_id: null, render_fingerprint: 'abc123',
    rendered_from: {export_id: 'future-42', extra: ['雪', 7]}, tile_w: [640, 320], tile_h: 480,
    captions: [[0, 'take ☕']]}]}],
  datasets: [{id: 'robot/project/task', project: 'robot/project', new_field: {x: true}}],
  pending: [], totals: {overlays: 1}, future_metadata: '☕"\\\n'.repeat(6000)
};
fs.writeFileSync(path.join(temp, 'input.json'), JSON.stringify(catalog));
const writer = spawnSync('python3', [path.join(root, 'tools/write_site_catalog.py'), '--input',
  path.join(temp, 'input.json'), '--out', path.join(temp, 'catalog'), '--max-bytes', '32768'], {encoding: 'utf8'});
assert.equal(writer.status, 0, writer.stderr);
const published = JSON.parse(fs.readFileSync(path.join(temp, 'catalog/index.json'), 'utf8'));
assert.ok(published.shards.length > 1);
const indexUrl = 'https://example.test/site/data/catalog/index.json';
const legacyUrl = 'https://example.test/site/data/datasets.json';
function harness({index = published, indexStatus = 200, shardStatus = 200, change, reject, legacy = catalog} = {}) {
  const calls = [];
  async function fetchImpl(url, options) {
    calls.push({url, options});
    if (url === legacyUrl) return new Response(JSON.stringify(legacy));
    if (url === indexUrl) return new Response(typeof index === 'string' ? index : JSON.stringify(index), {status: indexStatus});
    if (reject) throw new Error('integrity rejected by fetch');
    const name = new URL(url).pathname.split('/').pop();
    const payload = fs.readFileSync(path.join(temp, 'catalog', name), 'utf8');
    return new Response(change ? change(payload) : payload, {status: shardStatus});
  }
  return {calls, run: () => load({indexUrl, legacyUrl, fetchImpl})};
}
const plain = x => JSON.parse(JSON.stringify(x));
const hash = x => createHash('sha256').update(x).digest('hex');
test('Python-written shards round-trip every field, use integrity, and preserve the site prefix', async () => {
  const h = harness();
  assert.deepEqual(plain(await h.run()), catalog);
  assert.equal(h.calls.length, published.shards.length + 1);
  for (const {url, options} of h.calls.slice(1)) {
    assert.ok(url.startsWith('https://example.test/site/data/catalog/part-'));
    assert.ok(options.integrity.startsWith('sha256-'));
    const entry = published.shards.find(entry => url.endsWith(entry.path));
    assert.equal(options.integrity, 'sha256-' + Buffer.from(entry.sha256, 'hex').toString('base64'));
  }
});
test('legacy fallback occurs only when the catalog index returns 404', async () => {
  const h = harness({indexStatus: 404});
  assert.deepEqual(plain(await h.run()), catalog);
  assert.deepEqual(h.calls.map(call => call.url), [indexUrl, legacyUrl]);
});
test('index HTTP failure, corruption, and invalid schema never fall back', async () => {
  for (const options of [{indexStatus: 403}, {indexStatus: 500}, {index: '<html>failure</html>'},
    {index: {...published, schema: 'unknown'}}, {index: {...published, counts: {}}}]) {
    const h = harness(options);
    await assert.rejects(h.run());
    assert.equal(h.calls.length, 1);
  }
});
test('missing, truncated, checksum-corrupted, and fetch-rejected shards fail without fallback', async () => {
  for (const options of [{shardStatus: 404}, {shardStatus: 500}, {change: text => text.slice(1)},
    {change: text => text.replace('camx-catalog-v1', 'camx-catalog-v2')}, {reject: true}]) {
    const h = harness(options);
    await assert.rejects(h.run());
    assert.ok(h.calls.every(call => call.url !== legacyUrl));
  }
});
test('path traversal and oversized descriptors are rejected before any shard request', async () => {
  for (const entry of [{...published.shards[0], path: '../private.json'},
    {...published.shards[0], bytes: 5 * 1024 * 1024 + 1}]) {
    const h = harness({index: {...published, shards: [entry, ...published.shards.slice(1)]}});
    await assert.rejects(h.run(), /invalid shard descriptor/);
    assert.equal(h.calls.length, 1);
  }
});
test('catalog counts, final size, and checksum are independently checked', async () => {
  for (const override of [{counts: {...published.counts, overlays: 9}},
    {catalog_bytes: published.catalog_bytes + 1}, {catalog_sha256: hash('different catalog')}]) {
    const h = harness({index: {...published, ...override}});
    await assert.rejects(h.run(), /mismatch/);
    assert.ok(h.calls.every(call => call.url !== legacyUrl));
  }
});
test('self-consistent wrong shard ordinal is rejected as an invalid payload', async () => {
  const payload = JSON.parse(fs.readFileSync(path.join(temp, 'catalog', published.shards[0].path), 'utf8'));
  payload.part = 2;
  const text = JSON.stringify(payload), sha256 = hash(text);
  const entry = {path: 'part-00000-' + sha256 + '.json', bytes: Buffer.byteLength(text), sha256};
  fs.writeFileSync(path.join(temp, 'catalog', entry.path), text);
  const h = harness({index: {...published, shards: [entry, ...published.shards.slice(1)]}});
  await assert.rejects(h.run(), /invalid shard payload/);
});
test('index network errors do not trigger fallback', async () => {
  let calls = 0;
  await assert.rejects(load({indexUrl, legacyUrl, fetchImpl: async () => { calls++; throw new Error('offline'); }}), /offline/);
  assert.equal(calls, 1);
});
