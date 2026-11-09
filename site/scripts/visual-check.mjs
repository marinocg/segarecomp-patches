// Visual + layout check of the built site in a real browser, at phone, tablet and desktop widths, in dark and light themes.
// Writes full-page screenshots to ./screenshots/ (uploaded as a CI artifact) and FAILS on layout defects:
//   horizontal overflow, text below WCAG AA contrast on key elements, tap targets under 40px on phones, console errors, missing font.
// Usage: node scripts/visual-check.mjs [dist-dir]   (needs `npx playwright install --with-deps chromium`)
import { chromium } from 'playwright';
import http from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import path from 'node:path';

const dist = path.resolve(process.argv[2] ?? 'dist');
const SITE_BASE = (process.env.SITE_BASE ?? '/segarecomp-patches').replace(/\/+$/, '');
const out = path.resolve('screenshots');
const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.png': 'image/png', '.wasm': 'application/wasm' };

const server = http.createServer(async (req, res) => {
  let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  if (SITE_BASE && p !== SITE_BASE && !p.startsWith(SITE_BASE + '/')) { res.statusCode = 404; res.end('outside the site base path'); return; }
  p = p.slice(SITE_BASE.length) || '/';
  if (p.endsWith('/')) p += 'index.html';
  try { res.setHeader('content-type', types[path.extname(p)] ?? 'application/octet-stream'); res.end(await readFile(path.join(dist, p))); }
  catch { res.statusCode = 404; res.end(await readFile(path.join(dist, '404.html')).catch(() => 'not found')); }
}).listen(0);
const base = `http://127.0.0.1:${server.address().port}${SITE_BASE}`;

const viewports = [['phone', 360, 740], ['phone-large', 414, 896], ['tablet', 768, 1024], ['desktop', 1280, 800], ['wide', 1920, 1080]];
const pages = ['/', '/getting-started/', '/security/', '/product/patch-packages/', '/product/native-patch-sdk/', '/support/', '/repository/', '/nope-404/'];
const themes = ['dark', 'light'];

const lum = ([r, g, b]) => { const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };

const problems = [];
const browser = await chromium.launch();
await mkdir(out, { recursive: true });
for (const theme of themes) {
  for (const [vname, w, h] of viewports) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1, isMobile: w < 500, hasTouch: w < 500, colorScheme: theme });
    await ctx.addInitScript((t) => localStorage.setItem('starlight-theme', t), theme);
    for (const pg of pages) {
      const page = await ctx.newPage();
      const errs = [];
      page.on('console', (m) => { if (m.type() === 'error' && !/404/.test(m.text())) errs.push(m.text()); });
      page.on('pageerror', (e) => errs.push(String(e)));
      const resp = await page.goto(base + pg, { waitUntil: 'networkidle' });
      const tag = `${theme}/${vname}${pg}`;
      if (pg !== '/nope-404/' && resp.status() !== 200) problems.push(`${tag}: HTTP ${resp.status()}`);
      await page.evaluate(() => document.fonts.ready);
      const m = await page.evaluate(() => {
        const doc = document.documentElement, vw = doc.clientWidth;
        const wide = [...document.querySelectorAll('body *')].filter((e) => {
          const r = e.getBoundingClientRect();
          if (r.width === 0 || r.right <= vw + 1) return false;
          // elements that scroll internally (code blocks, tables) are allowed to be wider than their own box, not the page
          for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
            const o = getComputedStyle(p).overflowX; if ((o === 'auto' || o === 'scroll' || o === 'hidden') && p.getBoundingClientRect().right <= vw + 1) return false;
          }
          return true;
        }).slice(0, 4).map((e) => e.tagName.toLowerCase() + '.' + String(e.className).slice(0, 40));
        const h1 = document.querySelector('h1');
        const color = (el, prop) => getComputedStyle(el)[prop].match(/[\d.]+/g).slice(0, 3).map(Number);
        const bg = (el) => { for (let n = el; n; n = n.parentElement) { const c = getComputedStyle(n).backgroundColor; const v = c.match(/[\d.]+/g).map(Number); if (v.length === 3 || v[3] > 0.95) return v.slice(0, 3); } return [255, 255, 255]; };
        const small = [...document.querySelectorAll('a, button')].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.top < innerHeight && (r.height < 40 && r.width < 40) && getComputedStyle(e).display !== 'inline' && !e.classList.contains('sl-anchor-link'); }).slice(0, 3).map((e) => e.outerHTML.slice(0, 60));
        return { scrollW: doc.scrollWidth, vw, wide, fontOk: document.fonts.check('16px Silkscreen'), h1: h1 ? { font: getComputedStyle(h1).fontFamily, fg: color(h1, 'color'), bg: bg(h1) } : null,
                 bodyFg: color(document.body, 'color'), bodyBg: bg(document.body), small, hasSkip: !!document.querySelector('a[href="#_top"]') };
      });
      if (m.scrollW > m.vw + 1) problems.push(`${tag}: horizontal overflow (scrollWidth ${m.scrollW} > ${m.vw}); offenders: ${m.wide.join(', ')}`);
      if (!m.fontOk && pg === '/') problems.push(`${tag}: Silkscreen font did not load`);
      if (ratio(m.bodyFg, m.bodyBg) < 4.5) problems.push(`${tag}: body contrast ${ratio(m.bodyFg, m.bodyBg).toFixed(2)} < 4.5`);
      if (m.h1 && m.h1.bg.length === 3 && ratio(m.h1.fg, m.h1.bg) < 3) problems.push(`${tag}: heading contrast ${ratio(m.h1.fg, m.h1.bg).toFixed(2)} < 3`);
      if (w < 500 && m.small.length) problems.push(`${tag}: tap targets under 40x40: ${m.small.join(' | ')}`);
      for (const e of errs) problems.push(`${tag}: console error ${e}`);
      const file = `${theme}-${vname}-${w}x${h}${pg === '/' ? '-home' : pg.replace(/\//g, '-')}.png`;
      await page.screenshot({ path: path.join(out, file), fullPage: true });
      await page.close();
    }
    // interactive checks on phone: mobile menu opens and search dialog finds a known page
    if (vname === 'phone' && theme === 'dark') {
      const page = await ctx.newPage(); await page.goto(base + '/getting-started/', { waitUntil: 'networkidle' });
      try {
        await page.click('button.sl-menu-button', { timeout: 5000 });
        await page.waitForSelector('#starlight__sidebar a[href$="/security/"]', { state: 'visible', timeout: 5000 });
        await page.screenshot({ path: path.join(out, 'dark-phone-menu-open.png') });
        await page.click('button.sl-menu-button', { timeout: 5000 });
      } catch (e) { problems.push('dark/phone: mobile menu did not open: ' + String(e).split('\n')[0]); }
      try {
        await page.click('site-search button[data-open-modal]:not([disabled])', { timeout: 5000 });
        await page.fill('dialog input', 'sandboxed', { timeout: 5000 });
        await page.waitForSelector('dialog a[href*="security"]', { timeout: 8000 });
        await page.screenshot({ path: path.join(out, 'dark-phone-search.png') });
      } catch (e) { problems.push('dark/phone: search did not return the security page for "sandboxed": ' + String(e).split('\n')[0]); await page.screenshot({ path: path.join(out, 'dark-phone-search-failed.png') }); }
      await page.close();
    }
    await ctx.close();
  }
}
await browser.close(); server.close();
for (const p of problems) console.error('FAIL:', p);
console.log(problems.length ? `${problems.length} problem(s)` : `ok (${themes.length * viewports.length * pages.length} page renders)`);
process.exit(problems.length ? 1 : 0);
