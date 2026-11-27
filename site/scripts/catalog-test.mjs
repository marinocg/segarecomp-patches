// Catalog page tests against the synthetic example catalog (no commercial data, no network):
//  1. the strict reader accepts the example and rejects malformed entries;
//  2. two independent builds of the example produce byte-identical catalog pages (deterministic);
//  3. every generated page shows the package SHA-256 and the exact source revision;
//  4. a malformed catalog fails `astro build` (non-zero exit), so it can never be deployed;
//  5. the current-package view (scenarios A-F) on the published catalog and on SYNTHETIC successors added to a copy of it (nothing here is a real publication).
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { currentPackages, parseCatalog, ref } from '../src/lib/catalog.mjs';

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
    check(doc.packages.every((p) => idx.includes(`/catalog/${p.id}/${p.version}/`)), 'index links every package (current in the list, superseded in the collapsed history)');
    check((idx.match(/<a [^>]*data-patch-download/g) ?? []).length === currentPackages(parseCatalog(JSON.stringify(doc))).length, 'the catalog list has one download button per current package');
    execFileSync('python3', [path.resolve(site, '../scripts/check_site_a11y.py'), a, '--only', 'catalog/']);
    check(true, 'catalog pages pass the accessibility checks');
    try { execFileSync('python3', [path.resolve(site, '../scripts/check_site_seo.py'), a], { stdio: 'pipe' }); check(true, 'fixture site passes the SEO, JSON-LD, sitemap, robots and public-catalog checks'); }
    catch (e) { check(false, `fixture site SEO checks: ${e.stderr}`); }
  }
  // ---- current-package view -------------------------------------------------------------------------------------------------------------
  const live = JSON.parse(readFileSync(path.resolve(site, '../catalog/index.json'), 'utf8'));
  const S1 = 'sonic1-native-widescreen@2.0.1', S2 = 'sonic2-native-widescreen@3.0.1', S2R = 'sonic2-native-widescreen-rev01@3.0.1', S3 = 'sonic3k-native-widescreen@1.0.1';
  const CASTLE = ['16x9', '21x9', '32x9'].map((r) => `castle-of-illusion-activation-${r}@0.1.0`);
  const ABI1 = [S1, S2, S2R, S3];
  const of = (d, r) => d.packages.find((p) => ref(p) === r);
  const current = (d) => currentPackages(parseCatalog(JSON.stringify(d))).map(ref).sort();
  let digestSeed = 0;
  /** A SYNTHETIC schema 3 successor of `oldRef` (same platform, game directory and image) added to `d`; `point` records the pointer on the old entry. */
  const succeed = (d, oldRef, id, version, point = true) => {
    const old = of(d, oldRef), fake = () => createHash('sha256').update(`synthetic-${++digestSeed}`).digest('hex');
    const e = { ...structuredClone(of(d, CASTLE[0])), id, version, name: `SYNTHETIC successor ${id} ${version}`, game: old.game, game_path: old.game_path, source_path: `${old.game_path}/synthetic`,
      supported_scope: `SYNTHETIC test entry ${id} ${version}.`, package_sha256: fake(), package_identity: fake(),
      images: old.schema_version === 3 ? structuredClone(old.images) : [{ label: 'synthetic', sha256: old.source_image_sha256 }],
      asset: { name: `${id}.segapatch`, url: `https://github.com/marinocg/segarecomp-patches/releases/download/v0.3.0/${id}.segapatch` } };
    delete e.superseded_by;
    d.packages.push(e);
    if (point) old.superseded_by = ref(e);
    return ref(e);
  };
  const buildFixture = (name, d) => {
    const file = path.join(tmp, `${name}.json`), out = path.join(tmp, name); writeFileSync(file, JSON.stringify(d, null, 2) + '\n');
    const r = build(out, file);
    check(r.status === 0, `${name}: the site builds`);
    if (r.status !== 0) { console.log(r.stdout + r.stderr); return null; }
    for (const [script, what] of [['check_site_links.py', 'link'], ['check_site_a11y.py', 'accessibility'], ['check_site_seo.py', 'SEO']]) {
      const c = spawnSync('python3', [path.resolve(site, '../scripts', script), out], { encoding: 'utf8' });
      check(c.status === 0, `${name}: ${what} checks pass${c.status ? ': ' + c.stderr : ''}`);
    }
    const index = readFileSync(path.join(out, 'catalog', 'index.html'), 'utf8');
    const [main, history = ''] = index.split(/<summary[^>]*>\s*Superseded packages/);
    const refs = (html) => [...html.matchAll(/<h3[^>]*>\s*<a href="[^"]*\/catalog\/([^/"]+)\/([^/"]+)\/"/g)].map((m) => `${m[1]}@${m[2]}`).sort();
    const buttons = [...index.matchAll(/<a [^>]*data-patch-download[^>]*>/g)].map((m) => `${m[0].match(/data-patch-id="([^"]+)"/)[1]}@${m[0].match(/data-patch-version="([^"]+)"/)[1]}`).sort();
    const page = (r) => readFileSync(path.join(out, 'catalog', ...r.split('@'), 'index.html'), 'utf8');
    check(JSON.stringify(refs(main)) === JSON.stringify(current(d)) && JSON.stringify(buttons) === JSON.stringify(current(d)), `${name}: the browse list and its download buttons are exactly the current packages`);
    check(d.packages.every((p) => page(ref(p)).includes(`href="${p.asset.url}"`)), `${name}: every published version keeps its detail page and download`);
    check(readFileSync(path.join(out, 'catalog', 'index.json'), 'utf8') === readFileSync(file, 'utf8'), `${name}: the public JSON catalog holds every published version`);
    return { main, history, page };
  };
  const NOTICE = 'Deprecated ABI 1 — supported; replacement not yet published.';
  const count = (html, text) => html.split(text).length - 1;
  const link = (r) => `/catalog/${r.split('@').join('/')}/`;

  // A. the published state
  check(live.packages.length >= 8 && ABI1.every((r) => of(live, r)?.abi_status === 'deprecated'), 'A: the published catalog holds the four ABI 1 entries, marked deprecated');
  if (live.packages.every((p) => !p.superseded_by)) {
    const A = buildFixture('A-published', live);
    if (A) {
      check(current(live).length === live.packages.length && count(A.main, NOTICE) === 4 && A.history === '', 'A: every package is listed, the four ABI 1 ones say the replacement is not published, and there is no history list');
      check(ABI1.every((r) => A.page(r).includes(NOTICE) && !A.page(r).includes('aria-label="Superseded"')), 'A: ABI 1 pages show the deprecation and no successor');
      check(live.packages.filter((p) => !p.abi_status).every((p) => !A.page(ref(p)).includes('Deprecated ABI 1')), 'A: no other page claims a deprecation');
    }
  }
  const base = structuredClone(live); for (const p of base.packages) delete p.superseded_by;   // the scenarios start from a state with no replacement

  // B. Sonic 1 migrates
  const b1 = structuredClone(base); const n1 = succeed(b1, S1, 'synthetic-sonic1-abi2', '1.0.0');
  const B = buildFixture('B-sonic1', b1);
  if (B) {
    check(current(b1).includes(n1) && !current(b1).includes(S1) && current(b1).length === base.packages.length, 'B: exactly one current Sonic 1 package, the ABI 2 successor');
    check(count(B.main, NOTICE) === 3, 'B: the three unreplaced ABI 1 packages keep their notice');
    check(B.history.includes(link(S1)) && !B.main.includes(link(S1)), 'B: the old package is linked from the history list only');
    const old = B.page(S1);
    check(old.includes('aria-label="Superseded"') && old.includes(link(n1)) && old.includes('Deprecated ABI 1 — supported.') && old.includes('retention policy') && !old.includes(NOTICE), 'B: the old page shows the deprecation, the successor link and the retention policy');
  }
  const unpointed = structuredClone(base); const loose = succeed(unpointed, S1, 'synthetic-sonic1-abi2', '9.0.0', false);
  check(current(unpointed).includes(S1) && current(unpointed).includes(loose), 'B: a newer published package of another id hides nothing without a pointer');

  // C, D, E: both Sonic 2 revisions independently, a two-step chain, and the aspect-ratio variants
  const m = structuredClone(base);
  const r0 = succeed(m, S2, 'synthetic-sonic2-abi2-rev00', '1.0.0'), r1 = succeed(m, S2R, 'synthetic-sonic2-abi2-rev01', '1.0.0');
  const v1 = succeed(m, S1, 'synthetic-sonic1-abi2', '1.0.0'), v2 = succeed(m, v1, 'synthetic-sonic1-abi2', '2.0.0');
  const M = buildFixture('CDE-migrated', m);
  if (M) {
    const sonic2 = current(m).filter((r) => of(m, r).game_path.endsWith('/sonic-2'));
    check(JSON.stringify(sonic2) === JSON.stringify([r0, r1].sort()) && of(m, r0).images[0].sha256 !== of(m, r1).images[0].sha256, 'C: exactly one current Sonic 2 package per ROM revision, no ABI 1 duplicate');
    check(M.page(S2).includes(link(r0)) && !M.page(S2).includes(link(r1)) && M.page(S2R).includes(link(r1)) && !M.page(S2R).includes(link(r0)), 'C: each revision points only at its own successor');
    check(CASTLE.every((r) => current(m).includes(r) && M.main.includes(link(r))), 'D: all three Castle of Illusion aspect-ratio packages stay listed');
    check(current(m).includes('sor2-widescreen@1.0.0') && current(m).includes(S3) && count(M.main, NOTICE) === 1, 'D: independent packages stay; only the unreplaced ABI 1 package keeps the notice');
    const sonic1 = current(m).filter((r) => of(m, r).game_path.endsWith('/sonic-1'));
    check(JSON.stringify(sonic1) === JSON.stringify([v2]), 'E: a chain ABI 1 -> v1 -> v2 lists only v2');
    check(M.page(S1).includes(link(v1)) && M.page(S1).includes(link(v2)) && M.page(v1).includes(link(v2)) && M.history.includes(link(v1)) && M.history.includes(link(S1)), 'E: the intermediate and original pages stay linked, and the original also names the current package');
    check(!M.page(v1).includes('retention policy'), 'E: the ABI 1 retention statement is not applied to a superseded ABI 2 package');
  }

  // F. invalid supersession metadata is refused by the reader (and therefore fails the build)
  const invalid = (name, mutate, expected) => {
    const d = structuredClone(m); mutate(d);
    let msg = ''; try { parseCatalog(JSON.stringify(d)); } catch (e) { msg = String(e); }
    check(msg.includes(expected), `F: ${name} is rejected`);
    const py = path.join(tmp, 'invalid.json'); writeFileSync(py, JSON.stringify(d));
    const r = spawnSync('python3', [path.resolve(site, '../scripts/validate_catalog.py'), '--catalog', py], { encoding: 'utf8' });
    check(r.status === 1 && r.stderr.includes(expected), `F: ${name} is also rejected by validate_catalog.py`);
    return d;
  };
  const missing = invalid('a missing successor', (d) => { of(d, S3).superseded_by = 'nothing@9.9.9'; }, 'is not in this catalog');
  invalid('a self reference', (d) => { of(d, S3).superseded_by = S3; }, 'supersedes itself');
  invalid('a cycle', (d) => { of(d, v2).superseded_by = S1; }, 'supersession cycle');
  invalid('a lower version of the same id', (d) => { of(d, v2).superseded_by = v1; }, 'must name a higher version');
  invalid('a REV00 package replaced by the REV01 successor', (d) => { of(d, S2).superseded_by = r1; }, 'does not target every image');
  invalid('a successor of another game', (d) => { of(d, S3).superseded_by = CASTLE[0]; }, 'another platform or game directory');
  let threw = false; try { currentPackages(missing.packages); } catch { threw = true; }
  check(threw, 'F: the selection helper itself never recommends from invalid metadata');
  const missingPath = path.join(tmp, 'missing.json'); writeFileSync(missingPath, JSON.stringify(missing));
  const rm = build(path.join(tmp, 'f'), missingPath);
  check(rm.status !== 0 && /malformed catalog/.test(rm.stdout + rm.stderr), 'F: invalid supersession metadata fails the site build');

  const bad = clone(); delete bad.packages[1].package_identity; const badPath = path.join(tmp, 'bad.json'); writeFileSync(badPath, JSON.stringify(bad));
  const rbad = build(path.join(tmp, 'c'), badPath);
  check(rbad.status !== 0 && /malformed catalog/.test(rbad.stdout + rbad.stderr), 'a malformed catalog entry fails the build');
} finally { rmSync(tmp, { recursive: true, force: true }); }
process.exit(failed ? 1 : 0);
