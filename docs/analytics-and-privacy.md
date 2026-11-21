# Analytics, consent and privacy

The site loads **Google Tag Manager** (container `GTM-WDL2MTLC`) on every page, but only after the visitor has chosen. **Accept** enables analytics cookies; **Reject** keeps every storage signal denied, so Google Analytics runs in its **cookieless mode** (Google Consent Mode v2, "advanced" implementation). There is no consent-management dependency: the mechanism is `site/src/lib/consent.mjs` plus the Starlight `Footer` override `site/src/components/Footer.astro`, the only places GTM is mentioned in code. No page template repeats it.

## Behaviour

| Situation | What happens |
|---|---|
| First visit | A banner offers **Reject** and **Accept analytics** as equal buttons. Nothing is requested from Google before a choice, no analytics cookie is set, and the `<noscript>` iframe that Google's snippet includes is **deliberately not used** (it would request Google without consent when scripts are off). Consent Mode v2 defaults are declared denied (`ad_storage`, `ad_user_data`, `ad_personalization`, `analytics_storage`, ...). |
| Accept | Stored in `localStorage` (`segarecomp-patches-consent-v1`, first-party, one year). The container is requested once per page. Only `analytics_storage` is granted; the advertising signals stay denied. |
| Reject | Stored. The container is still requested once per page, but **no consent update is ever sent**: `analytics_storage`, `ad_storage`, `ad_user_data` and `ad_personalization` stay `denied`. Google Analytics then sets and reads no analytics cookie and stores no client identifier; Google receives only cookieless pings (page address, referrer, user agent and the IP address a request always carries) for aggregate measurement. The site never claims this is "no data to Google": it is no cookies and no persistent identifier. |
| Later | **Cookie settings** in the footer reopens the banner showing the current choice. Rejecting after accepting sends `analytics_storage: denied`, removes the analytics cookies (`_ga*`, `_gid`, `_gat*`, `_gcl*`) visible to this origin and reloads, so the container restarts cookieless from its first request. Accepting after rejecting upgrades the running container (one `analytics_storage: granted` update) without loading it twice. |
| Storage blocked | The choice only lasts for the page; the banner returns on the next page. |

The site is a multi-page static site, so "once" means once per page load: the script, the `gtm.js` start event and the request each occur exactly once; navigating to another page starts that page's single container. Search (Pagefind) and every page work with analytics rejected or blocked.

## What the website cannot guarantee

The integration controls **whether the container loads and what consent state it sees**. For cookieless measurement to work the GA4 tag in the container must be allowed to fire while `analytics_storage` is denied (Google Tag Manager: the tag's built-in consent check requires `analytics_storage` only for tags that set cookies; a Google tag using Consent Mode sends cookieless pings by itself). Verify in Tag Assistant that a rejected visit shows no `_ga` cookie and `gcs=G100`-style denied pings. What the tags inside the container do is configured in Google Tag Manager and is the maintainer's responsibility. Configure every tag in the container to require consent (for example *Built-in consent checks* on analytics tags requiring `analytics_storage`), keep advertising and remarketing tags out of the container, and re-check this after any container change. The privacy page (`site/src/content/docs/privacy.md`) states exactly the behaviour above and says plainly that a legal entity name and a privacy contact are **not yet published**; the maintainer must supply them before any claim about a controller or a contact address is added.

## Tests

* `site/scripts/consent-test.mjs` (`npm run test:consent`, in the `site / visual` CI job because it needs a downloaded browser): drives the built site in Chromium with Google's hosts intercepted. It checks that nothing is requested before consent, that Accept and Reject are both offered, the denied defaults, the container ID, one container per page, analytics-only grant, persistence of both choices, changing and withdrawing, no duplicate on navigation, and that navigation, the catalog and search work without analytics.
* `scripts/check_site_seo.py` (required `site / build` job) checks the built HTML statically: no GTM `<script src>`, no `<noscript>` iframe, the container ID appears only inside the one consent script.

## The `patch_download` event

Every download button (the large one on a package page and the compact one in the catalog list) is a link to the release asset with `data-patch-*` attributes taken from the validated catalog entry. A click pushes one event to the `dataLayer`:

```js
{ event: 'patch_download', patch_id, patch_version, patch_name, patch_release, patch_schema, patch_platform, patch_game, patch_file,
  download_location /* 'package_page_top' | 'package_page_download' | 'catalog_list' */, consent_analytics /* 'granted' | 'denied' */ }
```

It carries package facts only: no digest, no URL, nothing about the visitor. It is pushed **only while the container is running**, that is after a choice: a click before any choice is neither recorded nor replayed later. A rejected visitor's click is sent to the cookieless container with `consent_analytics: 'denied'`. In Google Tag Manager create a *Custom Event* trigger named `patch_download` and a GA4 event tag that maps the `patch_*` and `download_location` variables (data layer variables). The link itself is a plain `<a href>`: the download works with scripts off, with analytics rejected and when Google is blocked.
