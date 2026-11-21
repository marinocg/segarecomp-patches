// Consent-gated Google Tag Manager (container GTM-WDL2MTLC) for the whole site: a small first-party mechanism, no consent-management dependency.
//
// Nothing from Google is requested until the visitor makes a choice. The container script is not in any HTML and is injected here, once per page, after
// a choice:
//   * Accept  -> Consent Mode v2 `analytics_storage: granted`: normal analytics (first-party cookies such as _ga).
//   * Reject  -> the container still loads, but every storage signal stays `denied`: Google Analytics then runs in its cookieless mode. It sets and reads no
//                analytics cookie and stores no client ID; Google receives only cookieless pings (page, referrer, user agent, IP address) for aggregate measurement.
// ad_storage, ad_user_data and ad_personalization are never granted: no advertising or marketing is configured or intended.
// The choice is kept in localStorage (first-party, no cookie) and expires after a year. It can be changed or withdrawn at any time from the
// "Cookie settings" button in the footer. The `patch_download` event (trackDownload) is pushed to the dataLayer only while the container is running, i.e. after a choice.
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
  const doc = win.document;
  const dl = (win.dataLayer = win.dataLayer || []);
  function gtag() { dl.push(arguments); }   // GTM reads gtag commands as `arguments` objects
  gtag('consent', 'default', { ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied', analytics_storage: 'denied',
    functionality_storage: 'denied', personalization_storage: 'denied', security_storage: 'granted' });

  const banner = doc.getElementById('consent-banner');
  const settings = doc.getElementById('consent-settings');
  const status = doc.getElementById('consent-status');
  let loaded = false;

  /** Start the container once per page. `granted` = the visitor accepted analytics; otherwise it runs cookieless with every storage signal denied. */
  function loadContainer(granted) {
    if (loaded || win.__gtmLoaded) {   // never two containers on one page; a cookieless one that is later accepted only has its consent upgraded
      if (granted && win.__gtmConsent === 'denied') { win.__gtmConsent = 'granted'; gtag('consent', 'update', { analytics_storage: 'granted' }); }
      return;
    }
    loaded = win.__gtmLoaded = true;
    win.__gtmConsent = granted ? 'granted' : 'denied';
    if (granted) gtag('consent', 'update', { analytics_storage: 'granted' });
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
    if (analytics) { loadContainer(true); return; }
    if (loaded || had?.analytics) {   // withdrawal: tell Google, remove its cookies and reload so the container restarts cookieless from the first request
      gtag('consent', 'update', { analytics_storage: 'denied' });
      clearAnalyticsCookies(doc, win.location.hostname);
      win.location.reload();
      return;
    }
    loadContainer(false);   // a first rejection: cookieless measurement only
  }

  banner?.querySelector('[data-consent="accept"]')?.addEventListener('click', () => decide(true));
  banner?.querySelector('[data-consent="reject"]')?.addEventListener('click', () => decide(false));
  settings?.addEventListener('click', () => show(true));

  const choice = readChoice(win.localStorage);
  if (!choice) show(false); else loadContainer(choice.analytics);
  trackDownloads(win);
}

/** The custom GTM event for a patch download: facts of the package that was clicked, nothing about the visitor. */
export function downloadEvent(el) {
  const d = el.dataset ?? {};
  return { event: 'patch_download', patch_id: d.patchId, patch_version: d.patchVersion, patch_name: d.patchName, patch_release: d.patchRelease,
    patch_schema: d.patchSchema, patch_platform: d.patchPlatform, patch_game: d.patchGame, patch_file: d.patchFile, download_location: d.downloadLocation };
}

/** Push `patch_download` when a download link is clicked. Only while the container is running (after a choice): a click before any choice is not recorded, and is not replayed later. */
export function trackDownload(win, el) {
  if (!win.__gtmLoaded) return false;
  (win.dataLayer = win.dataLayer || []).push({ ...downloadEvent(el), consent_analytics: win.__gtmConsent });
  return true;
}

function trackDownloads(win) {
  win.document.addEventListener('click', (ev) => {
    const a = ev.target instanceof win.Element ? ev.target.closest('a[data-patch-download]') : null;
    if (a) trackDownload(win, a);
  });
}
