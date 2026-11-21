"""Positive and negative fixtures for scripts/check_site_seo.py on a fabricated built site (no network, no commercial data)."""
import json, pathlib, shutil, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_site_seo as seo

O, B = seo.ORIGIN, seo.BASE
GTM = seo.GTM_ID


def ld(*objs): return "".join(f'<script type="application/ld+json">{json.dumps(o)}</script>' for o in objs)


def page(path, title, desc, body, extra_head="", otype="website", canon=None, scripts=None):
    url = canon or f"{O}{B}{path}"
    sc = f"<script>const id='{GTM}';</script>" if scripts is None else scripts
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title><link rel="canonical" href="{url}"/>'
            f'<meta name="description" content="{desc}"/><meta property="og:title" content="{title}"/><meta property="og:type" content="{otype}"/>'
            f'<meta property="og:url" content="{url}"/><meta property="og:description" content="{desc}"/><meta name="twitter:card" content="summary"/>{extra_head}{sc}</head>'
            f'<body><h1>{title}</h1>{body}</body></html>')


ENTRY = {"id": "demo", "version": "1.2.3", "name": "Demo Patch"}
ASSET = f"https://github.com/marinocg/segarecomp-patches/releases/download/v1.0.0/demo.segapatch"


def site(test, **over):
    d = pathlib.Path(tempfile.mkdtemp()); test.addCleanup(shutil.rmtree, d)
    home_url, cat_url, pk_url = f"{O}{B}/", f"{O}{B}/catalog/", f"{O}{B}/catalog/demo/1.2.3/"
    web = {"@context": "https://schema.org", "@type": "WebSite", "@id": home_url + "#website", "name": "Fixture site", "url": home_url}
    sw = {"@context": "https://schema.org", "@type": "SoftwareApplication", "@id": pk_url + "#software", "name": "Demo Patch 1.2.3", "url": pk_url, "softwareVersion": "1.2.3",
          "description": "A fabricated patch for the fixture.", "downloadUrl": ASSET, "additionalProperty": [{"@type": "PropertyValue", "name": "Package SHA-256", "value": "a" * 64}]}
    bc = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": home_url}, {"@type": "ListItem", "position": 2, "name": "Catalog", "item": cat_url},
        {"@type": "ListItem", "position": 3, "name": "Demo Patch 1.2.3", "item": pk_url}]}
    col = {"@context": "https://schema.org", "@type": "CollectionPage", "@id": cat_url + "#page", "name": "Fixture catalog", "url": cat_url,
           "mainEntity": {"@type": "ItemList", "numberOfItems": 1, "itemListElement": [{"@type": "ListItem", "position": 1, "url": pk_url, "name": "Demo Patch 1.2.3"}]}}
    pages = {
        "index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "<p>Home</p>", ld(web)),
        "catalog/index.html": page("/catalog/", "Fixture catalog", "A fabricated catalog page used to test the SEO checks thoroughly.", f'<a href="{B}/catalog/demo/1.2.3/">Demo</a>', ld(col, bc)),
        "catalog/demo/1.2.3/index.html": page("/catalog/demo/1.2.3/", "Demo Patch 1.2.3", "A fabricated package page used to test the SEO checks thoroughly.",
                                              f'<p>Version 1.2.3</p><a href="{ASSET}">download</a><code>{"a" * 64}</code>', ld(sw, bc)),
    }
    pages.update(over.get("pages", {}))
    for rel, t in pages.items():
        f = d / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(t)
    urls = over.get("sitemap", [home_url, cat_url, pk_url])
    (d / "sitemap-0.xml").write_text('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
    (d / "sitemap-index.xml").write_text(f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>{O}{B}/sitemap-0.xml</loc></sitemap></sitemapindex>')
    (d / "robots.txt").write_text(over.get("robots", f"User-agent: *\nAllow: /\n\nSitemap: {O}{B}/sitemap-index.xml\n"))
    (d / "catalog/index.json").write_text(json.dumps({"catalog_format": 2, "packages": [ENTRY]}))
    for n in ("catalog-1", "catalog-2", "release-1", "release-2", "package-1"):
        (d / "schema").mkdir(exist_ok=True); (d / f"schema/{n}.schema.json").write_text(json.dumps({"$id": f"{O}{B}/schema/{n}.schema.json"}))
    return d


class Seo(unittest.TestCase):
    def errs(self, **over): return seo.check(site(self, **over))
    def has(self, errs, needle): self.assertTrue(any(needle in e for e in errs), (needle, errs))
    def pk(self, **kw):
        base = page("/catalog/demo/1.2.3/", "Demo Patch 1.2.3", "A fabricated package page used to test the SEO checks thoroughly.", f'<p>Version 1.2.3</p><a href="{ASSET}">download</a><code>{"a" * 64}</code>', **kw)
        return {"pages": {"catalog/demo/1.2.3/index.html": base}}

    def test_clean_fixture_passes(self): self.assertEqual(self.errs(), [])

    def test_the_real_build_if_present(self):
        d = ROOT / "site/dist"
        if d.is_dir() and (d / "robots.txt").is_file(): self.assertEqual(seo.check(d), [])

    def test_canonical_must_be_production_and_own(self):
        e = self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "", canon="http://localhost:4321/")}); self.has(e, "canonical")
    def test_duplicate_description(self):
        d = "A fabricated home page used to test the SEO checks thoroughly."; self.has(self.errs(pages={"catalog/index.html": page("/catalog/", "Other", d, f'<a href="{B}/catalog/demo/1.2.3/">x</a>')}), "description duplicates")
    def test_missing_description(self): self.has(self.errs(pages={"index.html": page("/", "Fixture site", "", "")}), "description")
    def test_noindex(self): self.has(self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "", '<meta name="robots" content="noindex">')}), "noindex")
    def test_bad_og_type(self): self.has(self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "", otype="video")}), "og:type")
    def test_sitemap_missing_page(self): self.has(self.errs(sitemap=[f"{O}{B}/"]), "sitemap and canonical URLs differ")
    def test_sitemap_with_404(self): self.has(self.errs(sitemap=[f"{O}{B}/", f"{O}{B}/catalog/", f"{O}{B}/catalog/demo/1.2.3/", f"{O}{B}/404.html"]), "differ")
    def test_robots_without_sitemap(self): self.has(self.errs(robots="User-agent: *\nAllow: /\n"), "robots.txt does not announce")
    def test_robots_blocking_everything(self): self.has(self.errs(robots=f"User-agent: *\nDisallow: /\nSitemap: {O}{B}/sitemap-index.xml\n"), "blocks the whole site")
    def test_orphan_catalog_page(self): self.has(self.errs(pages={"catalog/index.html": page("/catalog/", "Fixture catalog", "A fabricated catalog page used to test the SEO checks thoroughly.", "<p>none</p>", ld({"@context": "https://schema.org", "@type": "CollectionPage", "@id": f"{O}{B}/catalog/#page", "name": "Fixture catalog", "url": f"{O}{B}/catalog/", "mainEntity": {"@type": "ItemList", "numberOfItems": 0, "itemListElement": []}}))}), "orphan")

    def test_jsonld_invalid_json(self): self.has(self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "", '<script type="application/ld+json">{nope</script>')}), "not valid JSON")
    def test_jsonld_invented_rating(self):
        sw = {"@context": "https://schema.org", "@type": "SoftwareApplication", "@id": f"{O}{B}/catalog/demo/1.2.3/#software", "name": "Demo Patch 1.2.3", "url": f"{O}{B}/catalog/demo/1.2.3/", "softwareVersion": "1.2.3",
              "description": "x", "downloadUrl": ASSET, "aggregateRating": {"ratingValue": 5}}
        self.has(self.errs(**self.pk(extra_head=ld(sw))), "ungrounded")
    def test_jsonld_wrong_context(self): self.has(self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "", ld({"@context": "http://schema.org", "@type": "WebSite", "name": "Fixture site", "url": f"{O}{B}/"}))}), "@context")
    def test_jsonld_unknown_internal_url(self): self.has(self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "", ld({"@context": "https://schema.org", "@type": "WebSite", "name": "Fixture site", "url": f"{O}{B}/", "@id": f"{O}{B}/nope/#x", "mainEntityOfPage": f"{O}{B}/nope/"}))}), "does not exist")
    def test_jsonld_name_not_visible(self): self.has(self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "", ld({"@context": "https://schema.org", "@type": "WebSite", "name": "Hidden Brand", "url": f"{O}{B}/"}))}), "not visible")
    def test_jsonld_version_not_shown(self):
        base = page("/catalog/demo/1.2.3/", "Demo Patch 1.2.3", "A fabricated package page used to test the SEO checks thoroughly.", f'<a href="{ASSET}">download</a>', ld({"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "Demo Patch 1.2.3", "url": f"{O}{B}/catalog/demo/1.2.3/", "softwareVersion": "9.9.9", "description": "x", "downloadUrl": ASSET}))
        self.has(self.errs(pages={"catalog/demo/1.2.3/index.html": base}), "softwareVersion")
    def test_jsonld_download_must_be_linked(self):
        base = page("/catalog/demo/1.2.3/", "Demo Patch 1.2.3", "A fabricated package page used to test the SEO checks thoroughly.", "<p>Version 1.2.3</p>", ld({"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "Demo Patch 1.2.3", "url": f"{O}{B}/catalog/demo/1.2.3/", "softwareVersion": "1.2.3", "description": "x", "downloadUrl": ASSET}))
        self.has(self.errs(pages={"catalog/demo/1.2.3/index.html": base}), "downloadUrl is not a link")
    def test_jsonld_duplicate_identity(self):
        w = {"@context": "https://schema.org", "@type": "WebSite", "@id": f"{O}{B}/#website", "name": "Fixture site", "url": f"{O}{B}/"}
        self.has(self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "", ld(w, w))}), "duplicate JSON-LD identity")

    def test_gtm_noscript_iframe(self): self.has(self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", f'<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={GTM}"></iframe></noscript>')}), "noscript")
    def test_gtm_script_tag(self): self.has(self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "", scripts=f'<script async src="https://www.googletagmanager.com/gtm.js?id={GTM}"></script>')}), "script tag")
    def test_gtm_id_twice(self): self.has(self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "", scripts=f"<script>'{GTM}';'{GTM}'</script>")}), "exactly once")
    def test_gtm_id_must_be_present(self): self.has(self.errs(pages={"index.html": page("/", "Fixture site", "A fabricated home page used to test the SEO checks thoroughly.", "", scripts="<script>x</script>")}), "exactly once")

    def test_lastmod_is_artificial(self):
        d = site(self); f = d / "sitemap-0.xml"; f.write_text(f.read_text().replace("</loc>", "</loc><lastmod>2020-01-01</lastmod>", 1)); self.has(seo.check(d), "artificial lastmod")
    def test_catalog_json_and_schema_ids(self):
        d = site(self); (d / "schema/catalog-1.schema.json").write_text(json.dumps({"$id": "https://example.com/x"})); self.has(seo.check(d), "$id")
        d = site(self); (d / "catalog/index.json").unlink(); self.has(seo.check(d), "not published")


if __name__ == "__main__": unittest.main()
