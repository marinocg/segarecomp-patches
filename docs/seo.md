# SEO, structured data, sitemap and robots

Everything is generated at build time from real page metadata and the validated catalog; nothing is a hand-maintained duplicate, and nothing is invented.

| Concern | Where it comes from | Checked by |
|---|---|---|
| Title and meta description | Starlight frontmatter / `site/astro.config.mjs` site description; catalog pages from `site/src/lib/seo.mjs` (`packageDescription`, built from the package's own name, game, platform, trust class and first sentence of `supported_scope`) | `scripts/check_site_seo.py`: one non-empty title, one description 40-320 characters, titles and descriptions unique across pages |
| Canonical URL, Open Graph, Twitter card | Starlight emits them from `site` and the base path (`https://marinocg.github.io/segarecomp-patches/`); the site config sets the card to `summary` because no sharing image exists | exactly one canonical per page, absolute HTTPS, equal to the page's own trailing-slash URL, no localhost or GitHub source URLs, unique; `og:url` equals it, `og:description` equals the description, `og:type` is `website` or `article` |
| Sitemap | Starlight's built-in `@astrojs/sitemap` (`sitemap-index.xml`, `sitemap-0.xml`); not added a second time | the sitemap lists exactly the canonical URLs of the built pages, no 404, no artificial `lastmod`/`changefreq`/`priority` |
| `robots.txt` | `site/src/pages/robots.txt.ts`: `Allow: /` and the real sitemap URL | announces the production sitemap, does not block the site |
| JSON-LD | `site/src/lib/seo.mjs`; docs pages through the Starlight route middleware `site/src/routeData.ts`, catalog pages in `site/src/pages/catalog/` | valid JSON, `@context` `https://schema.org`, known types, required fields, no duplicate identity, internal URLs exist, names/versions/download links visible on the page, no ratings, reviews, offers, authors, publishers, dates or operating systems |
| Public JSON | `catalog/index.json` and `schema/*.schema.json` ([catalog format](catalog-format.md)) | published, valid, schemas' `$id` equals their URL, every catalog entry has a page linked from the catalog index (no orphans) |

## Structured data used

* **Homepage:** `WebSite` (name, URL, description). No `Organization`: the publishing entity is not established.
* **Documentation pages:** `TechArticle` (`WebPage` for the privacy page) from the page's real title and description.
* **Catalog index:** `CollectionPage` with an `ItemList` of the published packages, and `BreadcrumbList`.
* **Package pages:** `SoftwareApplication` with name, version, page URL, `downloadUrl`, file size, the licence URL when the package declares one, the package and source-image SHA-256 as `PropertyValue`, plus `BreadcrumbList`. It is a patch package, not the game and not the recompiler; the page text says so. No `operatingSystem`, `applicationCategory`, rating, review, price, popularity, date or author is claimed.

## Known limits

* `robots.txt` and the sitemap are emitted under the project path. Search engines read `robots.txt` only at the host root, and on `marinocg.github.io` that belongs to the user-site repository, so this file only takes effect on a custom domain served from the root (`SITE_URL`/`SITE_BASE`). Submit `https://marinocg.github.io/segarecomp-patches/sitemap-index.xml` in the search engines' webmaster tools to make discovery explicit.
* There is no `og:image`: no real, useful image asset exists, and one will not be fabricated. The Twitter card is therefore `summary`.
* Rich-result eligibility is not a goal. JSON-LD is present only where the page accurately represents the entity.
