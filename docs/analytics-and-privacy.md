# Analytics, consent and privacy

The site loads **Google Tag Manager** (container `GTM-WDL2MTLC`) on every page, but only after the visitor accepts. There is no consent-management dependency: the mechanism is `site/src/lib/consent.mjs` plus the Starlight `Footer` override `site/src/components/Footer.astro`, the only places GTM is mentioned in code. No page template repeats it.

## Behaviour

| Situation | What happens |
|---|---|
| First visit | A banner offers **Reject** and **Accept analytics** as equal buttons. Nothing is requested from Google, no analytics cookie is set, and the `<noscript>` iframe that Google's snippet includes is **deliberately not used** (it would request Google without consent when scripts are off). Consent Mode v2 defaults are declared denied (`ad_storage`, `ad_user_data`, `ad_personalization`, `analytics_storage`, ...). |
| Accept | Stored in `localStorage` (`segarecomp-patches-consent-v1`, first-party, one year). The container is requested once per page. Only `analytics_storage` is granted; the advertising signals stay denied. |
| Reject | Stored. Nothing is ever requested from Google. |
| Later | **Cookie settings** in the footer reopens the banner showing the current choice. Rejecting after accepting sends `analytics_storage: denied`, removes the analytics cookies (`_ga*`, `_gid`, `_gat*`, `_gcl*`) visible to this origin and reloads, so no container keeps running. |
| Storage blocked | The choice only lasts for the page; the banner returns on the next page. |

The site is a multi-page static site, so "once" means once per page load: the script, the `gtm.js` start event and the request each occur exactly once; navigating to another page starts that page's single container. Search (Pagefind) and every page work with analytics rejected or blocked.

## What the website cannot guarantee

The integration controls **whether the container loads and what consent state it sees**. What the tags inside the container do is configured in Google Tag Manager and is the maintainer's responsibility. Configure every tag in the container to require consent (for example *Built-in consent checks* on analytics tags requiring `analytics_storage`), keep advertising and remarketing tags out of the container, and re-check this after any container change. The privacy page (`site/src/content/docs/privacy.md`) states exactly the behaviour above and says plainly that a legal entity name and a privacy contact are **not yet published**; the maintainer must supply them before any claim about a controller or a contact address is added.

## Tests

* `site/scripts/consent-test.mjs` (`npm run test:consent`, in the `site / visual` CI job because it needs a downloaded browser): drives the built site in Chromium with Google's hosts intercepted. It checks that nothing is requested before consent, that Accept and Reject are both offered, the denied defaults, the container ID, one container per page, analytics-only grant, persistence of both choices, changing and withdrawing, no duplicate on navigation, and that navigation, the catalog and search work without analytics.
* `scripts/check_site_seo.py` (required `site / build` job) checks the built HTML statically: no GTM `<script src>`, no `<noscript>` iframe, the container ID appears only inside the one consent script.
