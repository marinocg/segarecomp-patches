#!/usr/bin/env python3
"""Static accessibility checks on a built site (standard library only; no browser, no network).

  check_site_a11y.py site/dist [--only PREFIX]

Per HTML page: `<html lang>`, a non-empty `<title>`, exactly one `<h1>`, no skipped heading level, every `<img>` has `alt`, every `<table>` of the generated catalog pages
has a `<caption>` and header cells with `scope`, every link has an accessible name, ids are unique, scrollable regions are labelled.
This is a floor, not a substitute for the informational browser/visual job; it is deterministic and runs in the required site build job.
"""
import argparse, html.parser, pathlib, sys


class Page(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.lang = None; self.title = ""; self.h = []; self.errs = []; self.ids = set(); self.stack = []; self._in_title = False
        self.tables = []; self.link_text = None; self.link_attrs = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html": self.lang = a.get("lang")
        if tag == "title": self._in_title = True
        if len(tag) == 2 and tag[0] == "h" and tag[1] in "123456": self.h.append(int(tag[1]))
        if a.get("id"):
            if a["id"] in self.ids: self.errs.append(f"duplicate id {a['id']!r}")
            self.ids.add(a["id"])
        if tag == "img" and "alt" not in a: self.errs.append("img without alt")
        if tag == "table": self.tables.append({"caption": False, "th_scope_missing": 0})
        if tag == "caption" and self.tables: self.tables[-1]["caption"] = True
        if tag == "th" and self.tables and not a.get("scope"): self.tables[-1]["th_scope_missing"] += 1
        if a.get("tabindex") == "0" and not (a.get("aria-label") or a.get("aria-labelledby")) and tag in ("div", "section"): self.errs.append("focusable region without an accessible name")
        if tag == "a" and a.get("href") is not None: self.link_text = ""; self.link_attrs = a
        if tag == "img" and self.link_text is not None and a.get("alt"): self.link_text += a["alt"]

    def handle_endtag(self, tag):
        if tag == "title": self._in_title = False
        if tag == "a" and self.link_text is not None:
            if not (self.link_text.strip() or (self.link_attrs or {}).get("aria-label")): self.errs.append(f"link without accessible name: {(self.link_attrs or {}).get('href')}")
            self.link_text = None

    def handle_data(self, d):
        if self._in_title: self.title += d
        if self.link_text is not None: self.link_text += d


def check_page(text, tables=True):
    p = Page(); p.feed(text); errs = list(p.errs)
    if not p.lang: errs.append("html lang missing")
    if not p.title.strip(): errs.append("empty <title>")
    if p.h.count(1) != 1: errs.append(f"expected exactly one h1, found {p.h.count(1)}")
    prev = 0
    for lvl in p.h:
        if prev and lvl > prev + 1: errs.append(f"heading level jumps h{prev} -> h{lvl}")
        prev = lvl
    for t in (p.tables if tables else []):
        if not t["caption"]: errs.append("table without caption")
        if t["th_scope_missing"]: errs.append("table header cell without scope")
    return errs


def check(dist, only="", table_prefix="catalog/"):
    dist = pathlib.Path(dist); errs = []
    pages = sorted(dist.rglob("*.html"))
    if not pages: return ["no HTML pages found"]
    for f in pages:
        rel = f.relative_to(dist).as_posix()
        if only and not rel.startswith(only): continue
        if rel == "404.html": continue
        for e in check_page(f.read_text(), rel.startswith(table_prefix)): errs.append(f"{rel}: {e}")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("dist"); ap.add_argument("--only", default=""); ap.add_argument("--table-prefix", default="catalog/", help="table caption/scope rules apply to generated pages under this prefix (imported Markdown tables are out of scope)"); a = ap.parse_args(argv)
    errs = check(a.dist, a.only, a.table_prefix)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)"); return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
