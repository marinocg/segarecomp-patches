// Catalog page tests against the synthetic example catalog (no commercial data, no network):
//  1. the strict reader accepts the example and rejects malformed entries;
//  2. two independent builds of the example produce byte-identical catalog pages (deterministic);
//  3. every generated page shows the package SHA-256 and the exact source revision;
//  4. a malformed catalog fails `astro build` (non-zero exit), so it can never be deployed.
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCatalog } from '../src/lib/catalog.mjs';

const site = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const example = path.resolve(site, '../catalog/examples/valid-catalog.json');
const doc = JSON.parse(readFileSync(example, 'utf8'));
let failed = 0;
const check = (ok, msg) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${msg}`); if (!ok) failed++; };
const clone = () => structuredClone(doc);
const rejects = (mutate) => { const d = clone(); mutate(d); try { parseCatalog(JSON.stringify(d)); return false; } catch { return true; } };

check(parseCatalog(JSON.stringify(doc)).length === 3, 'reader accepts the example catalog (two BPS packages and one schema 3 mod)');
check(parseCatalog(readFileSync(path.resolve(site, '../catalog/examples/valid-catalog-1.json'), 'utf8')).length === 2, 'reader still accepts a catalog_format 1 document');
check(rejects((d) => delete d.packages[0].package_sha256), 'reader rejects a missing SHA-256');
check(rejects((d) => { d.packages[0].source_revision.commit = 'abc'; }), 'reader rejects an unpinned source revision');
check(rejects((d) => { d.packages[0].asset.url = 'http://example.com/x'; }), 'reader rejects a non-HTTPS asset URL');
check(rejects((d) => { d.packages[1] = d.packages[0]; }), 'reader rejects a duplicate (id, version)');
check(rejects((d) => { d.catalog_format = 3; }), 'reader rejects an unknown catalog_format');
const MODI = 2;
check(rejects((d) => { d.packages[MODI].bps_sha256 = 'a'.repeat(64); }), 'reader rejects a fabricated BPS digest on a schema 3 mod');
check(rejects((d) => { d.packages[MODI].patched_image_sha256 = 'a'.repeat(64); }), 'reader rejects a fabricated patched-image digest on a schema 3 mod');
check(rejects((d) => { d.packages[MODI].native_abi = 1; }), 'reader rejects a schema 3 mod with the wrong ABI');
check(rejects((d) => { d.packages[MODI].capabilities = []; }), 'reader rejects a schema 3 mod without capabilities');
check(rejects((d) => { delete d.packages[MODI].images; }), 'reader rejects a schema 3 mod without its target images');

const tmp = mkdtempSync(path.join(tmpdir(), 'catalog-test-'));
const tree = (dir) => readdirSync(dir, { recursive: true }).filter((f) => statSync(path.join(dir, f)).isFile()).sort();
const digest = (dir) => createHash('sha256').update(tree(dir).map((f) => f + '\0' + createHash('sha256').update(readFileSync(path.join(dir, f))).digest('hex')).join('\n')).digest('hex');
const build = (out, catalog) => spawnSync('npx', ['astro', 'build', '--outDir', out], { cwd: site, env: { ...process.env, CATALOG_PATH: catalog }, encoding: 'utf8' });
try {
  const a = path.join(tmp, 'a'), b = path.join(tmp, 'b');
  const ra = build(a, example), rb = build(b, example);
  check(ra.status === 0 && rb.status === 0, 'example catalog builds');
  if (ra.status === 0 && rb.status === 0) {
    check(digest(path.join(a, 'catalog')) === digest(path.join(b, 'catalog')), 'catalog pages are byte-identical across two builds');
    for (const p of doc.packages) {
      const html = readFileSync(path.join(a, 'catalog', p.id, p.version, 'index.html'), 'utf8');
      check(html.includes(p.package_sha256) && html.includes(p.source_revision.commit), `${p.id}@${p.version} page shows SHA-256 and exact source commit`);
      const buttons = [...html.matchAll(/<a [^>]*class="[^"]*download-button[^"]*"[^>]*>/g)].map((m) => m[0]);
      check(buttons.length >= 2 && buttons.every((b) => b.includes(`href="${p.asset.url}"`) && b.includes('data-patch-download') && b.includes(`data-patch-id="${p.id}"`) && b.includes(`data-patch-version="${p.version}"`)), `${p.id}@${p.version} page has prominent download buttons that link to the release asset and carry the event data`);
      if (p.schema_version === 3) {
        check(p.images.every((i) => html.includes(i.sha256)) && p.capabilities.every((c) => html.includes(c)), `${p.id}@${p.version} page lists the target images and capabilities`);
        check(!/BPS SHA-256|Patched image SHA-256|Source image SHA-256|Native source SHA-256/.test(html), `${p.id}@${p.version} page shows no fictitious BPS or patched-image fields`);
        check(html.includes(`${p.source_path}`) , `${p.id}@${p.version} page links its source directory`);
      } else check(html.includes('BPS SHA-256') && html.includes(p.patched_image_sha256), `${p.id}@${p.version} legacy page still shows the BPS and patched-image digests`);
    }
    // The public machine-readable catalog is the validated input, byte for byte, and the schemas are served at their `$id` URLs.
    check(readFileSync(path.join(a, 'catalog', 'index.json'), 'utf8') === readFileSync(example, 'utf8'), 'public /catalog/index.json equals the validated catalog');
    for (const n of ['catalog-1', 'catalog-2', 'release-1', 'release-2', 'package-1']) {
      const s = JSON.parse(readFileSync(path.join(a, 'schema', `${n}.schema.json`), 'utf8'));
      check(s.$id.endsWith(`/schema/${n}.schema.json`), `schema ${n} is served at its $id`);
    }
    const idx = readFileSync(path.join(a, 'catalog', 'index.html'), 'utf8');
    check(doc.packages.every((p) => idx.includes(p.id)), 'index lists every package');
    check((idx.match(/<a [^>]*data-patch-download/g) ?? []).length === doc.packages.length, 'the catalog list has one download button per package');
    execFileSync('python3', [path.resolve(site, '../scripts/check_site_a11y.py'), a, '--only', 'catalog/']);
    check(true, 'catalog pages pass the accessibility checks');
    try { execFileSync('python3', [path.resolve(site, '../scripts/check_site_seo.py'), a], { stdio: 'pipe' }); check(true, 'fixture site passes the SEO, JSON-LD, sitemap, robots and public-catalog checks'); }
    catch (e) { check(false, `fixture site SEO checks: ${e.stderr}`); }
  }
  const bad = clone(); delete bad.packages[1].package_identity; const badPath = path.join(tmp, 'bad.json'); writeFileSync(badPath, JSON.stringify(bad));
  const rbad = build(path.join(tmp, 'c'), badPath);
  check(rbad.status !== 0 && /malformed catalog/.test(rbad.stdout + rbad.stderr), 'a malformed catalog entry fails the build');
} finally { rmSync(tmp, { recursive: true, force: true }); }
process.exit(failed ? 1 : 0);
