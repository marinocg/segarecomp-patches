#!/usr/bin/env python3
"""Static SEO, structured-data, sitemap/robots, public-JSON and GTM-wiring checks on a BUILT site (standard library only; no network).

  check_site_seo.py site/dist

Production origin and base path come from SITE_URL / SITE_BASE (defaults https://marinocg.github.io and /segarecomp-patches), the same variables the build uses.
Per page: one title, a meta description (distinct across pages), exactly one absolute HTTPS canonical equal to the page's own URL, Open Graph consistency,
a summary Twitter card, no noindex, and valid, grounded JSON-LD. Site-wide: the sitemap lists exactly the canonical URLs (no 404, no invented lastmod),
robots.txt announces it, the public catalog/schemas parse, no catalog page is orphaned, and Google Tag Manager is only inside the consent script.
"""
import argparse, html.parser, json, os, pathlib, re, sys
import xml.etree.ElementTree as ET

ORIGIN = os.environ.get("SITE_URL", "https://marinocg.github.io").rstrip("/")
BASE = os.environ.get("SITE_BASE", "/segarecomp-patches").rstrip("/")
GTM_ID = "GTM-WDL2MTLC"
LD_TYPES = {"WebSite", "TechArticle", "WebPage", "CollectionPage", "ItemList", "BreadcrumbList", "ListItem", "SoftwareApplication", "PropertyValue"}
LD_FORBIDDEN = {"aggregateRating", "review", "offers", "interactionStatistic", "datePublished", "dateModified", "author", "publisher", "operatingSystem", "applicationCategory", "ratingValue"}
EXTERNAL_OK = ("https://github.com/", "https://marinocg.github.io/", "https://www.mozilla.org/", "https://opensource.org/", "https://schema.org")
REQUIRED = {"WebSite": ("name", "url"), "TechArticle": ("headline", "url", "description"), "WebPage": ("name", "url", "description"), "CollectionPage": ("name", "url", "mainEntity"),
            "SoftwareApplication": ("name", "url", "softwareVersion", "downloadUrl", "description"), "BreadcrumbList": ("itemListElement",), "ItemList": ("itemListElement",)}


class Page(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.title = ""; self.metas = []; self.canon = []; self.ld = []; self.h1 = ""; self.text = []; self.hrefs = []
        self.scripts = []; self.noscript_iframe = False; self.script_srcs = []
        self._t = self._h1 = self._ld = self._script = self._noscript = False; self._buf = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title": self._t = True
        elif tag == "h1": self._h1 = True
        elif tag == "meta": self.metas.append(a)
        elif tag == "link" and a.get("rel") == "canonical": self.canon.append(a.get("href"))
        elif tag == "a" and a.get("href"): self.hrefs.append(a["href"])
        elif tag == "script":
            self._script = True; self._buf = ""; self._ld = a.get("type") == "application/ld+json"
            if a.get("src"): self.script_srcs.append(a["src"])
        elif tag == "noscript": self._noscript = True
        elif tag == "iframe" and self._noscript: self.noscript_iframe = True

    def handle_endtag(self, tag):
        if tag == "title": self._t = False
        elif tag == "h1": self._h1 = False
        elif tag == "noscript": self._noscript = False
        elif tag == "script":
            (self.ld if self._ld else self.scripts).append(self._buf); self._script = self._ld = False

    def handle_data(self, d):
        if self._t: self.title += d
        if self._script: self._buf += d; return
        if self._h1: self.h1 += d
        self.text.append(d)


def meta(p, key, attr="name"): return [m.get("content") for m in p.metas if m.get(attr) == key]


def expected_url(rel):   # "security/index.html" -> https://origin/base/security/
    d = rel[: -len("index.html")] if rel.endswith("index.html") else rel
    return f"{ORIGIN}{BASE}/{d}"


def check_ld(p, url, errs, where, all_urls):
    text = " ".join(p.text); seen = set()
    for raw in p.ld:
        try: obj = json.loads(raw)
        except ValueError as e: errs.append(f"{where}: JSON-LD is not valid JSON: {e}"); continue
        stack = [obj]
        while stack:
            o = stack.pop()
            if isinstance(o, list): stack += o; continue
            if not isinstance(o, dict): continue
            stack += [v for v in o.values() if isinstance(v, (dict, list))]
            bad = LD_FORBIDDEN & set(o)
            if bad: errs.append(f"{where}: JSON-LD carries ungrounded properties {sorted(bad)}")
            t = o.get("@type")
            if t is not None and t not in LD_TYPES: errs.append(f"{where}: unexpected JSON-LD type {t!r}")
            if "@context" in o and o["@context"] != "https://schema.org": errs.append(f"{where}: @context must be https://schema.org")
            for k in REQUIRED.get(t, ()):
                if k not in o: errs.append(f"{where}: JSON-LD {t} lacks {k}")
            if "@id" in o:
                if o["@id"] in seen and o.get("@type"): errs.append(f"{where}: duplicate JSON-LD identity {o['@id']}")
                if o.get("@type"): seen.add(o["@id"])
            for k in ("url", "item", "downloadUrl", "license", "mainEntityOfPage", "@id"):
                v = o.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    if not v.startswith(("https://",)): errs.append(f"{where}: JSON-LD {k} is not HTTPS: {v}")
                    elif v.startswith(ORIGIN) and v.split("#")[0] not in all_urls: errs.append(f"{where}: JSON-LD {k} points at a page that does not exist: {v}")
                    elif not v.startswith(EXTERNAL_OK) and not v.startswith(ORIGIN): errs.append(f"{where}: JSON-LD {k} points outside the site and GitHub: {v}")
            if t in ("TechArticle", "WebPage", "SoftwareApplication", "CollectionPage") and o.get("url") != url: errs.append(f"{where}: JSON-LD url {o.get('url')} differs from the canonical {url}")
            name = o.get("headline") or (o.get("name") if t in ("TechArticle", "WebPage", "SoftwareApplication", "CollectionPage", "WebSite") else None)
            if name and name.strip() not in (p.h1.strip(), p.title.strip(), text) and name.strip() not in p.title and name.strip() not in text:
                errs.append(f"{where}: JSON-LD name {name!r} is not visible on the page")
            if t == "SoftwareApplication":
                if o.get("softwareVersion") not in text: errs.append(f"{where}: softwareVersion {o.get('softwareVersion')} is not shown on the page")
                if o.get("downloadUrl") not in p.hrefs: errs.append(f"{where}: downloadUrl is not a link on the page")
                for pv in o.get("additionalProperty", []):
                    if pv.get("value") not in text: errs.append(f"{where}: property {pv.get('name')} value is not shown on the page")
            if t == "BreadcrumbList":
                pos = [i.get("position") for i in o["itemListElement"]]
                if pos != list(range(1, len(pos) + 1)): errs.append(f"{where}: breadcrumb positions are not 1..n")
            if t == "ItemList" and o.get("numberOfItems") not in (None, len(o["itemListElement"])): errs.append(f"{where}: ItemList numberOfItems differs from its items")


def check(dist):
    dist = pathlib.Path(dist); errs = []
    pages = {f.relative_to(dist).as_posix(): f for f in sorted(dist.rglob("index.html"))}
    if not pages: return ["no pages found"]
    parsed = {}
    for rel, f in pages.items():
        p = Page(); p.feed(f.read_text()); parsed[rel] = p
    all_urls = {expected_url(r) for r in pages}
    canon_seen, desc_seen, title_seen = {}, {}, {}
    for rel, p in parsed.items():
        w = rel; url = expected_url(rel)
        if not p.title.strip(): errs.append(f"{w}: empty title")
        elif p.title.strip() in title_seen: errs.append(f"{w}: title duplicates {title_seen[p.title.strip()]}")
        else: title_seen[p.title.strip()] = w
        if len(p.title.strip()) > 120: errs.append(f"{w}: title is longer than 120 characters")
        d = meta(p, "description")
        if len(d) != 1 or not (d[0] or "").strip(): errs.append(f"{w}: needs exactly one non-empty meta description")
        else:
            if not 40 <= len(d[0]) <= 320: errs.append(f"{w}: description length {len(d[0])} outside 40-320")
            if d[0] in desc_seen: errs.append(f"{w}: description duplicates {desc_seen[d[0]]}")
            desc_seen[d[0]] = w
        if len(p.canon) != 1: errs.append(f"{w}: expected exactly one canonical link, found {len(p.canon)}")
        else:
            c = p.canon[0]
            if c != url: errs.append(f"{w}: canonical {c} should be {url}")
            if not c.startswith("https://") or "localhost" in c or "127.0.0.1" in c or "github.com" in c: errs.append(f"{w}: canonical is not the production URL: {c}")
            if c in canon_seen: errs.append(f"{w}: canonical duplicates {canon_seen[c]}")
            canon_seen[c] = w
        for k, want in (("og:url", [url]), ("og:title", None), ("og:description", d)):
            v = meta(p, k, "property")
            if len(v) != 1 or (want is not None and v != want): errs.append(f"{w}: {k} must appear once and agree with the page ({v})")
        if (meta(p, "og:type", "property") or [None])[0] not in ("website", "article") or len(meta(p, "og:type", "property")) != 1: errs.append(f"{w}: og:type must be one of website/article")
        if meta(p, "twitter:card") != ["summary"]: errs.append(f"{w}: twitter:card must be exactly 'summary' (no sharing image exists)")
        if any("noindex" in (x or "").lower() for x in meta(p, "robots")): errs.append(f"{w}: public page is noindex")
        check_ld(p, url, errs, w, all_urls)
        # Google Tag Manager: only inside the consent script, once; never a script tag, link or noscript iframe in the markup
        if p.noscript_iframe: errs.append(f"{w}: a <noscript> iframe would request Google without consent")
        if any("googletagmanager" in s for s in p.script_srcs): errs.append(f"{w}: GTM is loaded by a script tag instead of after consent")
        n = sum(s.count(GTM_ID) for s in p.scripts)
        if n != 1: errs.append(f"{w}: the GTM container ID must appear exactly once in the page's scripts, found {n}")
    # sitemap
    idx = dist / "sitemap-index.xml"
    if not idx.is_file(): errs.append("sitemap-index.xml is missing")
    else:
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = set()
        for sm in ET.parse(idx).getroot().findall("s:sitemap/s:loc", ns):
            f = dist / sm.text.replace(f"{ORIGIN}{BASE}/", "")
            if not sm.text.startswith(f"{ORIGIN}{BASE}/") or not f.is_file(): errs.append(f"sitemap index points at {sm.text}")
            else:
                root = ET.parse(f).getroot()
                for u in root.findall("s:url", ns):
                    locs.add(u.find("s:loc", ns).text)
                    for bad in ("lastmod", "changefreq", "priority"):
                        if u.find(f"s:{bad}", ns) is not None: errs.append(f"sitemap entry carries an artificial {bad}")
        pages_404 = {expected_url("404.html")}
        if locs & pages_404: errs.append("sitemap lists the 404 page")
        if locs != all_urls: errs.append(f"sitemap and canonical URLs differ: only in sitemap {sorted(locs - all_urls)[:3]}, only in pages {sorted(all_urls - locs)[:3]}")
    # robots
    rb = dist / "robots.txt"
    if not rb.is_file(): errs.append("robots.txt is missing")
    else:
        t = rb.read_text()
        if f"Sitemap: {ORIGIN}{BASE}/sitemap-index.xml" not in t: errs.append("robots.txt does not announce the real sitemap URL")
        if re.search(r"(?im)^disallow:\s*/\s*$", t): errs.append("robots.txt blocks the whole site")
    # public catalog and schemas, orphans
    cj = dist / "catalog" / "index.json"
    if not cj.is_file(): errs.append("catalog/index.json is not published")
    else:
        cat = json.loads(cj.read_text())
        if cat.get("catalog_format") != 1: errs.append("published catalog has an unexpected format")
        idxp = parsed.get("catalog/index.html"); linked = set(idxp.hrefs) if idxp else set()
        for e in cat.get("packages", []):
            rel = f"catalog/{e['id']}/{e['version']}/index.html"
            if rel not in pages: errs.append(f"catalog entry {e['id']}@{e['version']} has no page")
            elif f"{BASE}/catalog/{e['id']}/{e['version']}/" not in linked: errs.append(f"catalog page {e['id']}@{e['version']} is not linked from the catalog index (orphan)")
        if len([r for r in pages if re.match(r"catalog/[^/]+/[^/]+/index.html", r)]) != len(cat.get("packages", [])): errs.append("catalog pages and catalog entries differ in number")
    for n in ("catalog-1", "release-1"):
        f = dist / "schema" / f"{n}.schema.json"
        if not f.is_file(): errs.append(f"schema/{n}.schema.json is not published")
        elif json.loads(f.read_text()).get("$id") != f"{ORIGIN}{BASE}/schema/{n}.schema.json": errs.append(f"schema {n} $id does not equal its public URL")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("dist"); errs = check(ap.parse_args(argv).dist)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)"); return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
