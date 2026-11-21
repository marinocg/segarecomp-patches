// Consent-gated Google Tag Manager (container GTM-WDL2MTLC) for the whole site: a small first-party mechanism, no consent-management dependency.
//
// Opt-in only. Nothing from Google is requested unless the visitor has accepted analytics: no choice yet = no request, Reject = no request, on this page or any later one.
// The container script is not in any HTML and is injected here, once per page, only while the stored choice is "accepted". Consent Mode v2 signals are declared
// denied by default; acceptance grants analytics storage only (ad_storage, ad_user_data and ad_personalization are never granted: no advertising is configured).
// The choice is kept in localStorage (first-party, no cookie) and expires after a year. It can be changed or withdrawn at any time from the "Cookie settings" button
// in the footer. Withdrawing after the container ran sends `analytics_storage: denied`, removes the analytics cookies this origin can see and reloads without
// the container; a request that was already sent cannot be undone. The `patch_download` event is pushed only while analytics consent is granted.
// Docs: docs/analytics-and-privacy.md.
export const GTM_ID = 'GTM-WDL2MTLC';
export const STORAGE_KEY = 'segarecomp-patches-consent-v1';
const MAX_AGE_MS = 365 * 24 * 60 * 60 * 1000;

export function readChoice(storage, now = Date.now()) {
  try {
    const v = JSON.parse(storage.getItem(STORAGE_KEY) ?? 'null');
    if (v && typeof v.analytics === 'boolean' && typeof v.ts === 'number' && now - v.ts < MAX_AGE_MS) return v;
  } catch { /* unreadable or blocked storage means "no choice yet" */ }
  return null;
}

export function writeChoice(storage, analytics, now = Date.now()) {
  try { storage.setItem(STORAGE_KEY, JSON.stringify({ v: 1, analytics, ts: now })); } catch { /* the choice then only lasts for this page */ }
}

/** Best effort removal of the first-party cookies Google Analytics may have set while consent was granted. */
export function clearAnalyticsCookies(doc, host) {
  const parts = host.split('.'); const domains = ['', host, ...parts.slice(1, -1).map((_, i) => '.' + parts.slice(i + 1).join('.'))];
  for (const c of doc.cookie.split(';')) {
    const name = c.split('=')[0].trim();
    if (!/^(_ga|_gid|_gat|_gcl)/.test(name)) continue;
    for (const d of domains) doc.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/${d ? `; domain=${d}` : ''}`;
  }
}

export function initConsent(win = window) {
  if (win.__consentInit) return;   // one set of listeners and one container per page, however often this is called
  win.__consentInit = true;
  const doc = win.document;
  const dl = (win.dataLayer = win.dataLayer || []);
  function gtag() { dl.push(arguments); }   // GTM reads gtag commands as `arguments` objects
  gtag('consent', 'default', { ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied', analytics_storage: 'denied',
    functionality_storage: 'denied', personalization_storage: 'denied', security_storage: 'granted' });

  const banner = doc.getElementById('consent-banner');
  const settings = doc.getElementById('consent-settings');
  const status = doc.getElementById('consent-status');
  let loaded = false;

  /** Start the container once per page, with analytics granted. Never called for a rejection or before a choice. */
  function loadContainer() {
    if (loaded || win.__gtmLoaded) return;   // never two containers on one page
    loaded = win.__gtmLoaded = true;
    win.__gtmConsent = 'granted';
    gtag('consent', 'update', { analytics_storage: 'granted' });
    dl.push({ 'gtm.start': Date.now(), event: 'gtm.js' });
    const s = doc.createElement('script');
    s.async = true; s.src = `https://www.googletagmanager.com/gtm.js?id=${GTM_ID}`;
    doc.head.appendChild(s);
  }

  function show(focus) {
    if (!banner) return;
    banner.hidden = false;
    const c = readChoice(win.localStorage);
    if (status) status.textContent = c ? `Current choice: analytics ${c.analytics ? 'accepted' : 'rejected'}.` : 'No choice made yet.';
    if (focus) banner.querySelector('button')?.focus();
  }

  function decide(analytics) {
    const had = readChoice(win.localStorage);
    writeChoice(win.localStorage, analytics);
    if (banner) banner.hidden = true;
    if (analytics) { loadContainer(); return; }
    if (loaded || had?.analytics) {   // withdrawal: no further events, tell Google, remove its cookies, reload without a container
      win.__gtmConsent = 'denied';
      gtag('consent', 'update', { analytics_storage: 'denied' });
      clearAnalyticsCookies(doc, win.location.hostname);
      win.location.reload();
    }   // a rejection with nothing loaded changes nothing: no container, no request
  }

  banner?.querySelector('[data-consent="accept"]')?.addEventListener('click', () => decide(true));
  banner?.querySelector('[data-consent="reject"]')?.addEventListener('click', () => decide(false));
  settings?.addEventListener('click', () => show(true));

  const choice = readChoice(win.localStorage);
  if (!choice) show(false); else if (choice.analytics) loadContainer();
  trackDownloads(win);
}

/** The custom GTM event for a patch download: facts of the package that was clicked, nothing about the visitor. */
export function downloadEvent(el) {
  const d = el.dataset ?? {};
  return { event: 'patch_download', patch_id: d.patchId, patch_version: d.patchVersion, patch_name: d.patchName, patch_release: d.patchRelease,
    patch_schema: d.patchSchema, patch_platform: d.patchPlatform, patch_game: d.patchGame, patch_file: d.patchFile, download_location: d.downloadLocation };
}

/** Push `patch_download` when a download link is clicked, only while analytics consent is granted. Nothing is queued: a click before acceptance or after rejection is never recorded or replayed. */
export function trackDownload(win, el) {
  if (!win.__gtmLoaded || win.__gtmConsent !== 'granted') return false;
  (win.dataLayer = win.dataLayer || []).push(downloadEvent(el));
  return true;
}

function trackDownloads(win) {
  win.document.addEventListener('click', (ev) => {
    const a = ev.target instanceof win.Element ? ev.target.closest('a[data-patch-download]') : null;
    if (a) trackDownload(win, a);
  });
}
