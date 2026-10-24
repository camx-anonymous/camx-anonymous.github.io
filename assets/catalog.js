/* Load the published catalog, preserving the legacy object shape for both pages. */
(function (root) {
  'use strict';
  const SCHEMA = 'camx-catalog-v1', MAX_BYTES = 5 * 1024 * 1024;
  const encoder = new TextEncoder();
  const fail = message => { throw new Error('Catalog: ' + message); };
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const hash = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
  const count = value => Number.isSafeInteger(value) && value >= 0;
  async function verify(bytes, expected) {
    // Fetch integrity verifies shard responses even on non-secure HTTP origins.
    // WebCrypto also verifies the reassembled catalog where it is available.
    if (root.crypto && root.crypto.subtle) {
      const actual = Array.from(new Uint8Array(await root.crypto.subtle.digest('SHA-256', bytes)),
        value => value.toString(16).padStart(2, '0')).join('');
      if (actual !== expected) fail('checksum mismatch');
    }
  }
  function integrity(hex) {
    return 'sha256-' + btoa(String.fromCharCode(...hex.match(/../g).map(value => parseInt(value, 16))));
  }
  function counts(data) {
    if (!object(data) || !Array.isArray(data.projects) || !Array.isArray(data.datasets) ||
        (data.pending !== undefined && !Array.isArray(data.pending))) fail('invalid catalog shape');
    const projects = new Set(), datasets = new Set();
    let overlays = 0;
    for (const project of data.projects) {
      if (!object(project) || typeof project.key !== 'string' || !project.key ||
          projects.has(project.key) || !Array.isArray(project.overlays)) fail('invalid project');
      projects.add(project.key);
      overlays += project.overlays.length;
      for (const clip of project.overlays) {
        if (!object(clip) || ['key', 'slug', 'dataset'].some(key => typeof clip[key] !== 'string' || !clip[key]))
          fail('invalid clip');
        for (const field of ['export_id', 'render_fingerprint']) {
          if (clip[field] != null && (typeof clip[field] !== 'string' || !clip[field])) fail('invalid clip provenance');
        }
      }
    }
    for (const row of data.datasets) {
      if (!object(row) || typeof row.id !== 'string' || !row.id || datasets.has(row.id) || !projects.has(row.project))
        fail('invalid dataset');
      datasets.add(row.id);
    }
    if (object(data.totals) && data.totals.overlays !== undefined && data.totals.overlays !== overlays)
      fail('clip total mismatch');
    return {projects: projects.size, datasets: datasets.size, overlays, pending: (data.pending || []).length};
  }
  async function load(options = {}) {
    const indexUrl = options.indexUrl || '../data/catalog/index.json';
    const legacyUrl = options.legacyUrl || '../data/datasets.json';
    const fetcher = options.fetchImpl || root.fetch.bind(root);
    const response = await fetcher(indexUrl, {cache: 'no-cache'});
    if (response.status === 404) {
      const legacy = await fetcher(legacyUrl);
      if (!legacy.ok) fail('legacy request failed: ' + legacy.status);
      const data = await legacy.json();
      counts(data);
      return data;
    }
    if (!response.ok) fail('index request failed: ' + response.status);
    const indexText = await response.text();
    if (encoder.encode(indexText).length > MAX_BYTES) fail('index exceeds size limit');
    const index = JSON.parse(indexText);
    if (!object(index) || index.schema !== SCHEMA || !count(index.max_bytes) || index.max_bytes > MAX_BYTES ||
        index.max_bytes < 1024 || !hash(index.source_sha256) || !hash(index.catalog_sha256) ||
        !count(index.catalog_bytes) || !object(index.counts) || !Array.isArray(index.shards) || !index.shards.length ||
        ['projects', 'datasets', 'overlays', 'pending'].some(key => !count(index.counts[key]))) fail('invalid index');
    if (encoder.encode(indexText).length > index.max_bytes) fail('index exceeds declared size limit');
    const base = new URL(indexUrl, root.document && root.document.baseURI || root.location && root.location.href || 'http://localhost/');
    const paths = new Set();
    for (let part = 0; part < index.shards.length; part++) {
      const shard = index.shards[part];
      if (!object(shard) || !hash(shard.sha256) || !count(shard.bytes) || shard.bytes > index.max_bytes ||
          shard.path !== 'part-' + String(part).padStart(5, '0') + '-' + shard.sha256 + '.json' || paths.has(shard.path))
        fail('invalid shard descriptor');
      paths.add(shard.path);
    }
    const pieces = await Promise.all(index.shards.map(async (shard, part) => {
      const result = await fetcher(new URL(shard.path, base).href, {integrity: integrity(shard.sha256)});
      if (!result.ok) fail('shard request failed: ' + result.status);
      const text = await result.text(), bytes = encoder.encode(text);
      if (bytes.length !== shard.bytes || bytes.length > index.max_bytes) fail('shard size mismatch');
      await verify(bytes, shard.sha256);
      const payload = JSON.parse(text);
      if (!object(payload) || payload.schema !== SCHEMA || payload.part !== part || typeof payload.text !== 'string')
        fail('invalid shard payload');
      return payload.text;
    }));
    const document = pieces.join(''), bytes = encoder.encode(document);
    if (bytes.length !== index.catalog_bytes) fail('catalog size mismatch');
    await verify(bytes, index.catalog_sha256);
    const data = JSON.parse(document), actual = counts(data);
    if (Object.keys(actual).some(key => actual[key] !== index.counts[key])) fail('catalog count mismatch');
    return data;
  }
  root.CamxCatalog = {load};
  if (typeof module === 'object' && module.exports) module.exports = root.CamxCatalog;
})(globalThis);
