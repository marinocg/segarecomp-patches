// Consent and Google Tag Manager behaviour in a real browser, against the built site (no network: googletagmanager.com is intercepted and stubbed).
// Usage: node scripts/consent-test.mjs [dist-dir]
//  - before consent nothing is requested from Google; the banner offers Accept and Reject equally; search and navigation work without analytics
//  - Reject: ZERO requests to Google, on that page, after a reload and on later pages; no analytics cookie; choice persisted (no banner)
//  - Accept: the container with the right ID is requested exactly once per page, with Consent Mode v2 defaults denied then analytics granted only
//  - persistence: an accepted choice loads the container on later pages (still exactly one); the choice can be changed or withdrawn from "Cookie settings"
//  - the `patch_download` event: exactly one per click, only while analytics is accepted (never before a choice, never after a rejection, never replayed); downloads work regardless
import { chromium } from 'playwright';
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const dist = path.resolve(process.argv[2] ?? 'dist');
const BASE = (process.env.SITE_BASE ?? '/segarecomp-patches').replace(/\/+$/, '');
const ID = 'GTM-WDL2MTLC';
const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.wasm': 'application/wasm', '.pf_meta': 'application/octet-stream' };
const server = http.createServer(async (req, res) => {
  let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  if (BASE && p !== BASE && !p.startsWith(BASE + '/')) { res.statusCode = 404; res.end('outside base'); return; }
  p = p.slice(BASE.length) || '/'; if (p.endsWith('/')) p += 'index.html';
  try { res.setHeader('content-type', types[path.extname(p)] ?? 'application/octet-stream'); res.end(await readFile(path.join(dist, p))); }
  catch { res.statusCode = 404; res.end('not found'); }
}).listen(0);
const origin = `http://127.0.0.1:${server.address().port}`;
const base = origin + BASE;

let failed = 0;
const check = (ok, msg) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${msg}`); if (!ok) failed++; };

const browser = await chromium.launch();
async function session() {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const google = [];     // every request that would have gone to Google
  await ctx.route(/googletagmanager\.com|google-analytics\.com|doubleclick\.net/, (route) => { google.push(route.request().url()); route.fulfill({ status: 200, contentType: 'text/javascript', body: 'window.__gtmStubRuns=(window.__gtmStubRuns||0)+1;' }); });
  const page = await ctx.newPage();
  const errors = []; page.on('pageerror', (e) => errors.push(String(e))); page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  return { ctx, page, google, errors };
}
const info = (page) => page.evaluate(() => ({
  scripts: document.querySelectorAll('script[src*="googletagmanager.com"]').length,
  iframes: document.querySelectorAll('iframe[src*="googletagmanager.com"]').length,
  starts: (window.dataLayer || []).filter((e) => e && !e.length && e.event === 'gtm.js').length,
  consent: (window.dataLayer || []).filter((e) => e && e.length && e[0] === 'consent').map((e) => [e[1], { ...e[2] }]),
  bannerVisible: !document.getElementById('consent-banner').hidden,
  stored: localStorage.getItem('segarecomp-patches-consent-v1'),
}));

// 1. First visit: no Google request, banner visible with both choices, defaults denied, site works.
{
  const { ctx, page, google, errors } = await session();
  await page.goto(base + '/', { waitUntil: 'networkidle' });
  const i = await info(page);
  check(google.length === 0, 'first visit: nothing requested from Google before consent');
  check(i.bannerVisible, 'first visit: consent banner is shown');
  check(await page.locator('#consent-banner button').count() === 2 && await page.getByRole('button', { name: 'Reject' }).isVisible() && await page.getByRole('button', { name: 'Accept analytics' }).isVisible(), 'banner offers Accept and Reject as equal buttons');
  const def = i.consent.find(([k, v]) => k === 'default')?.[1];
  check(def && ['ad_storage', 'ad_user_data', 'ad_personalization', 'analytics_storage'].every((k) => def[k] === 'denied'), 'Consent Mode v2 defaults are denied');
  check(i.scripts === 0 && i.iframes === 0 && i.starts === 0, 'no container script, no noscript iframe and no gtm.js event before consent');
  const html = await (await ctx.request.get(base + '/')).text();
  check(!/<noscript[^>]*>\s*<iframe/i.test(html) && !/<script[^>]+src="[^"]*googletagmanager/.test(html), 'served HTML has no GTM script tag and no noscript iframe');
  check((html.match(new RegExp(ID, 'g')) ?? []).length === 1, 'the container ID appears exactly once in the page');
  // site functionality without analytics: navigation and search
  await page.getByRole('link', { name: 'Getting started' }).first().click(); await page.waitForLoadState('networkidle');
  check(page.url().includes('/getting-started/') && google.length === 0, 'navigation works without analytics');
  await page.goto(base + '/catalog/', { waitUntil: 'networkidle' });
  check(await page.locator('.catalog-list li').count() >= 1 && google.length === 0, 'catalog pages work without analytics');
  await page.keyboard.press('Control+K').catch(() => {});
  await page.locator('site-search button, button[data-open-modal]').first().click().catch(() => {});
  const dialogOpen = await page.locator('dialog[open]').count();
  check(dialogOpen === 1 && google.length === 0, 'search opens without analytics');
  check(errors.length === 0, `no console errors (${errors.slice(0, 2).join(' | ')})`);
  await ctx.close();
}

// 2. Reject: opt-in means NO analytics traffic at all. Zero Google requests, no container, no cookie, persisted; accepting later loads it normally, once.
{
  const { ctx, page, google } = await session();
  await page.goto(base + '/', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Reject' }).click(); await page.waitForTimeout(400);
  let i = await info(page);
  check(!i.bannerVisible && JSON.parse(i.stored).analytics === false, 'reject: banner closes and the choice is stored');
  check(google.length === 0 && i.scripts === 0 && i.starts === 0 && i.iframes === 0, 'reject: no request to Google, no container script, no gtm.js start event');
  const def = i.consent.find(([k]) => k === 'default')?.[1];
  check(def && ['ad_storage', 'ad_user_data', 'ad_personalization', 'analytics_storage'].every((k) => def[k] === 'denied') && !i.consent.some(([k]) => k === 'update'), 'reject: Consent Mode defaults stay denied and nothing is ever granted');
  check(!(await page.evaluate(() => document.cookie)).match(/_ga|_gid|_gcl/), 'reject: no analytics cookie exists');
  await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(400); i = await info(page);
  check(!i.bannerVisible && google.length === 0 && i.scripts === 0 && i.starts === 0, 'reject persists: after a reload still no request and no container');
  for (const u of ['/security/', '/catalog/', '/getting-started/']) { await page.goto(base + u, { waitUntil: 'networkidle' }); await page.waitForTimeout(300); }
  i = await info(page);
  check(google.length === 0 && i.scripts === 0 && i.starts === 0 && !i.bannerVisible, 'reject persists across navigation: still zero requests to Google');
  // change the choice later: accept loads the container normally, exactly once
  await page.getByRole('button', { name: 'Cookie settings' }).click();
  check((await info(page)).bannerVisible && /rejected/.test(await page.locator('#consent-status').textContent()), 'Cookie settings reopens the banner and shows the current choice');
  await page.getByRole('button', { name: 'Accept analytics' }).click(); await page.waitForTimeout(400); i = await info(page);
  const upd = i.consent.filter(([k]) => k === 'update');
  check(google.length === 1 && new URL(google[0]).searchParams.get('id') === ID && i.scripts === 1 && i.starts === 1 && upd.length === 1 && upd[0][1].analytics_storage === 'granted', 'reject -> accept loads the container exactly once with analytics granted');
  await page.getByRole('button', { name: 'Cookie settings' }).click(); await page.getByRole('button', { name: 'Accept analytics' }).click(); await page.waitForTimeout(300);
  check(google.length === 1 && (await info(page)).scripts === 1, 'accepting again does not load a second container');
  await ctx.close();
}

// 3. Accept: exactly one initialisation, right ID, analytics granted only, persists, never duplicated by navigation, withdrawable.
{
  const { ctx, page, google } = await session();
  await page.goto(base + '/', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Accept analytics' }).click(); await page.waitForTimeout(300);
  let i = await info(page);
  check(google.length === 1 && new URL(google[0]).searchParams.get('id') === ID && google[0].startsWith('https://www.googletagmanager.com/gtm.js'), `accept: container ${ID} requested once from googletagmanager.com`);
  check(i.scripts === 1 && i.starts === 1 && i.iframes === 0, 'accept: one container script, one gtm.js start event, no noscript iframe');
  const upd = i.consent.find(([k]) => k === 'update')?.[1];
  check(upd && upd.analytics_storage === 'granted' && !('ad_storage' in upd) && !('ad_user_data' in upd), 'accept grants analytics storage only (advertising signals stay denied)');
  check(JSON.parse(i.stored).analytics === true && !i.bannerVisible, 'accept is stored and the banner closes');
  await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(200); i = await info(page);
  check(google.length === 2 && i.scripts === 1 && i.starts === 1 && !i.bannerVisible, 'persisted accept: reload initialises exactly one container, no banner');
  await page.getByRole('link', { name: 'Security' }).first().click(); await page.waitForLoadState('networkidle'); await page.waitForTimeout(200); i = await info(page);
  check(i.scripts === 1 && i.starts === 1, 'navigation to another page initialises exactly one container on that page');
  // withdraw
  await page.getByRole('button', { name: 'Cookie settings' }).click();
  check(/accepted/.test(await page.locator('#consent-status').textContent()), 'Cookie settings shows the accepted state');
  const before = google.length;
  await Promise.all([page.waitForLoadState('load'), page.getByRole('button', { name: 'Reject' }).click()]); await page.waitForLoadState('networkidle'); await page.waitForTimeout(300);
  i = await info(page);
  check(JSON.parse(i.stored).analytics === false && !i.bannerVisible, 'withdrawal: the rejection is stored');
  check(google.length === before && i.scripts === 0 && i.starts === 0 && !i.consent.some(([k]) => k === 'update'), 'withdrawal: the page reloads without a container and sends no further request to Google');
  check(!(await page.evaluate(() => document.cookie)).match(/_ga|_gid|_gcl/), 'withdrawal: the analytics cookies are gone');
  await page.goto(base + '/catalog/', { waitUntil: 'networkidle' }); await page.waitForTimeout(300);
  check(google.length === before && (await info(page)).scripts === 0, 'withdrawal persists across navigation: still no Google request');
  await ctx.close();
}

// 4. The patch_download event: exactly one per click and only while analytics is accepted. Downloads work in every state and never depend on analytics.
{
  const downloads = (page) => page.evaluate(() => (window.dataLayer || []).filter((e) => e && !e.length && e.event === 'patch_download'));
  const prep = async (choice) => {
    const s = await session(); let served = 0;
    await s.ctx.route(/github\.com\/marinocg\/segarecomp-patches\/releases\/download/, (route) => { served++; route.fulfill({ status: 200, headers: { 'content-type': 'application/octet-stream', 'content-disposition': 'attachment; filename=x.segapatch' }, body: 'x' }); });
    await s.page.goto(base + '/catalog/', { waitUntil: 'networkidle' });
    if (choice) { await s.page.getByRole('button', { name: choice }).click(); await s.page.waitForTimeout(400); }
    s.served = () => served;
    s.click = async () => { await s.page.locator('a[data-patch-download]').first().click(); await s.page.waitForTimeout(300); };
    return s;
  };
  {   // before any choice
    const s = await prep(null); await s.click();
    check(s.served() === 1 && (await downloads(s.page)).length === 0 && s.google.length === 0, 'download before any choice: the file is served, no event, no request to Google');
    await s.page.getByRole('button', { name: 'Accept analytics' }).click(); await s.page.waitForTimeout(300);
    check((await downloads(s.page)).length === 0, 'a click made before acceptance is not replayed afterwards');
    await s.ctx.close();
  }
  {   // rejected
    const s = await prep('Reject'); await s.click(); await s.click();
    check(s.served() === 2 && (await downloads(s.page)).length === 0 && s.google.length === 0, 'download after rejection: files are served, no patch_download event, zero requests to Google');
    await s.ctx.close();
  }
  {   // accepted: exactly one event per click (no duplicated listener), correct facts
    const s = await prep('Accept analytics'); await s.click();
    let ev = await downloads(s.page); const link = await s.page.locator('a[data-patch-download]').first().evaluate((a) => ({ ...a.dataset }));
    check(s.served() === 1 && ev.length === 1 && ev[0].patch_id === link.patchId && ev[0].patch_version === link.patchVersion && ev[0].patch_file === link.patchFile && ev[0].download_location === 'catalog_list', `accepted: the file is served and exactly one patch_download event is emitted (${ev[0]?.patch_id})`);
    check(!JSON.stringify(ev[0]).match(/sha256|identity|http|consent/i), 'the event carries package facts only: no digest, no URL, nothing about the visitor');
    await s.click(); ev = await downloads(s.page); check(ev.length === 2, 'a second click emits exactly one more event');
    check(await s.page.evaluate(() => document.querySelectorAll('script[src*="googletagmanager.com"]').length) === 1 && s.google.length === 1, 'one container, one Google request');
    // withdrawal: no more events, even for a click right after
    await s.page.getByRole('button', { name: 'Cookie settings' }).click();
    await Promise.all([s.page.waitForLoadState('load'), s.page.getByRole('button', { name: 'Reject' }).click()]); await s.page.waitForLoadState('networkidle'); await s.page.waitForTimeout(300);
    await s.click(); check((await downloads(s.page)).length === 0 && s.google.length === 1 && s.served() === 3, 'after withdrawal the download still works but emits no event and no request');
    await s.ctx.close();
  }
  {   // the package page button
    const s = await prep('Accept analytics');
    await s.page.locator('.catalog-list h3 a').first().click(); await s.page.waitForLoadState('networkidle'); await s.page.waitForTimeout(400);
    const big = s.page.locator('a.download-button:not(.download-button--compact)').first();
    check(await big.isVisible() && (await big.boundingBox()).height >= 44, 'the package page shows a large, visible download button');
    await big.click(); await s.page.waitForTimeout(300); const ev = await downloads(s.page);
    check(ev.length === 1 && ev[0].download_location === 'package_page_top' && s.served() === 1, 'the package-page button downloads and reports its location');
    await s.ctx.close();
  }
}

await browser.close(); server.close();
process.exit(failed ? 1 : 0);
