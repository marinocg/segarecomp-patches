#!/usr/bin/env python3
"""Link checker for the built static site (no network, standard library only).

  check_site_links.py site/dist

Every internal href/src/srcset target must exist in the build output, and every `#fragment` must name an id in the target page.
External links (https:) are not fetched: CI must not depend on third-party availability. The scripts/check_repo.py link rules still
require HTTPS for external links in repository Markdown.
"""
import html.parser, pathlib, re, sys, urllib.parse


class Page(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self.ids = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"): self.ids.add(a["id"])
        if tag == "a" and a.get("name"): self.ids.add(a["name"])
        for k in ("href", "src"):
            if tag in {"a", "link", "script", "img", "source", "iframe"} and a.get(k): self.links.append(a[k])
        if a.get("srcset"):
            self.links += [s.split()[0] for s in a["srcset"].split(",") if s.strip()]


def target(dist, page, link):
    u = urllib.parse.urlsplit(link)
    if u.scheme or u.netloc:
        return None if u.scheme in {"https", "http", "mailto", "data"} else "unsupported scheme"
    path = urllib.parse.unquote(u.path)
    base = dist if path.startswith("/") else page.parent
    t = (base / path.lstrip("/")) if path else page
    try: t = t.resolve(); t.relative_to(dist.resolve())
    except ValueError: return "escapes the site root"
    if t.is_dir(): t = t / "index.html"
    return t if t.is_file() else "target not found"


def check(dist):
    dist = pathlib.Path(dist); errs = []; pages = {}
    if not (dist / "index.html").is_file(): return [f"{dist}: no index.html (build the site first)"]
    for f in sorted(dist.rglob("*.html")):
        p = Page(); p.feed(f.read_text(errors="replace")); pages[f.resolve()] = p
    if not (dist / "404.html").is_file(): errs.append("404.html is missing")
    for f, p in pages.items():
        rel = f.relative_to(dist.resolve()).as_posix()
        for link in p.links:
            t = target(dist, f, link)
            if t is None: continue
            if isinstance(t, str): errs.append(f"{rel}: {link}: {t}"); continue
            frag = urllib.parse.urlsplit(link).fragment
            if frag and t.suffix == ".html":
                tp = pages.get(t.resolve())
                if tp is not None and urllib.parse.unquote(frag) not in tp.ids: errs.append(f"{rel}: {link}: no such anchor")
    # CSS url(...) references (fonts, images): every site-local one must exist in the build output
    for css in sorted(dist.rglob("*.css")):
        for u in re.findall(r"url\(\s*['\"]?([^'\")]+?)['\"]?\s*\)", css.read_text(errors="replace")):
            if u.startswith(("data:", "#")): continue
            t = target(dist, css, u)
            if isinstance(t, str): errs.append(f"{css.relative_to(dist).as_posix()}: url({u}): {t}")
    return errs


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1: print(__doc__, file=sys.stderr); return 2
    errs = check(argv[0])
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} broken link(s)"); return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
