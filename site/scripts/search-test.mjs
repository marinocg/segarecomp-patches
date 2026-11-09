// Built-site search test: load the real Pagefind client that Starlight ships in dist/ and search for a known page.
// Runs entirely against local files (no network). Usage: node scripts/search-test.mjs [dist-dir]
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const dist = path.resolve(process.argv[2] ?? 'dist');
const base = pathToFileURL(dist + path.sep);

// The Pagefind client fetches its index files relative to its own URL; serve them from disk.
const realFetch = globalThis.fetch;
globalThis.fetch = async (input, init) => {
  const url = new URL(typeof input === 'string' ? input : input.url ?? String(input), base);
  if (url.protocol === 'file:') {
    try { return new Response(await readFile(url)); } catch { return new Response('not found', { status: 404 }); }
  }
  return realFetch(input, init);
};

const checks = [
  // [query, substring that must appear in a hit's URL]
  ['sandboxed', '/security/'],
  ['provider', '/getting-started/'],
  ['BPS', '/product/patch-packages/'],
];

const pagefind = await import(pathToFileURL(path.join(dist, 'pagefind', 'pagefind.js')).href);
await pagefind.options({ basePath: new URL('pagefind/', base).href });
let failed = 0;
for (const [query, expect] of checks) {
  const res = await pagefind.search(query);
  const urls = (await Promise.all(res.results.slice(0, 20).map((r) => r.data()))).map((d) => d.url);
  const ok = urls.some((u) => u.includes(expect));
  console.log(`${ok ? 'ok  ' : 'FAIL'} search ${JSON.stringify(query)} -> ${urls.length} hit(s), expects ${expect}`);
  if (!ok) failed++;
}
const none = await pagefind.search('zzqxjwv-no-such-term');
if (none.results.length !== 0) { console.log('FAIL nonsense query returned hits'); failed++; }
process.exit(failed ? 1 : 0);
