#!/usr/bin/env python3
"""Import product documentation into the site at a pinned product revision (docs/product-docs.md).

  import_product_docs.py --write  [--product-checkout DIR]   regenerate site/src/content/docs/product/*.md from the pin
  import_product_docs.py --check  [--product-checkout DIR]   fail unless the committed pages equal a fresh import
  import_product_docs.py --drift  [--product-checkout DIR]   fail when pinned_commit is behind minimum_commit

Sources are read from the product repository at `pinned_commit` (a local checkout via `git show`, else raw.githubusercontent.com).
The product documents stay authoritative: pages are mechanical copies with links rewritten, plus a provenance notice.
"""
import argparse, json, os, pathlib, posixpath, re, subprocess, sys, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PIN = ROOT / "docs/product-docs.pin.json"
OUT = ROOT / "site/src/content/docs"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")


def load_pin(path=PIN):
    pin = json.loads(pathlib.Path(path).read_text())
    for k in ("pinned_commit", "minimum_commit"):
        if not HEX40.match(pin.get(k, "")): raise SystemExit(f"{k} must be a full 40-hex commit id")
    if pin.get("pin_format") != 1 or not pin.get("files"): raise SystemExit("unsupported pin file")
    return pin


def fetch(pin, path, checkout=None):
    commit = pin["pinned_commit"]
    if checkout:
        r = subprocess.run(["git", "-C", checkout, "show", f"{commit}:{path}"], capture_output=True)
        if r.returncode: raise SystemExit(f"{path} not found at {commit[:12]} in {checkout}")
        return r.stdout.decode()
    url = f"https://raw.githubusercontent.com/{pin['repository']}/{commit}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r: return r.read().decode()
    except urllib.error.URLError as e: raise SystemExit(f"cannot fetch {url}: {e}")


def rewrite_links(text, source, pin):
    """Relative links to imported documents become site routes; other relative links point at the pinned product revision."""
    pages = {f["source"]: f["page"] for f in pin["files"]}
    base = f"https://github.com/{pin['repository']}"
    def sub(m):
        bang, label, target = m.groups()
        if re.match(r"^([a-z][a-z0-9+.-]*:|#)", target, re.I): return m.group(0)
        path, _, frag = target.partition("#")
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
        if resolved.startswith(".."): return label
        if resolved in pages and not bang: return f"[{label}](/{pages[resolved]}/{'#' + frag if frag else ''})"
        if bang: return f"{bang}[{label}](https://raw.githubusercontent.com/{pin['repository']}/{pin['pinned_commit']}/{resolved})"
        return f"[{label}]({base}/blob/{pin['pinned_commit']}/{resolved}{'#' + frag if frag else ''})"
    return LINK.sub(sub, text)


def render(pin, entry, text):
    lines = text.splitlines()
    if not lines or not lines[0].startswith("# "): raise SystemExit(f"{entry['source']}: expected a leading '# Title'")
    title = lines[0][2:].strip(); body = "\n".join(lines[1:]).lstrip("\n")
    body = rewrite_links(body, entry["source"], pin)
    short = pin["pinned_commit"][:12]; src_url = f"https://github.com/{pin['repository']}/blob/{pin['pinned_commit']}/{entry['source']}"
    desc = f"Imported copy of the product document {entry['source']} at revision {short}."
    notice = (f":::note[Imported product documentation]\nThis page is an unmodified copy of [`{entry['source']}`]({src_url}) at segarecomp revision `{short}`, "
              f"with links rewritten. The product repository is authoritative: where they differ, the product document wins. "
              f"What is supported is recorded only in the [compatibility ledger](/support/).\n:::\n\n")
    safe_title = json.dumps(title)
    return f"---\ntitle: {safe_title}\ndescription: {json.dumps(desc)}\neditUrl: false\n---\n\n{notice}{body.rstrip()}\n"


def build(pin, checkout):
    return {OUT / (f["page"] + ".md"): render(pin, f, fetch(pin, f["source"], checkout)) for f in pin["files"]}


def drift(pin, checkout=None, compare=None):
    """OK when pinned_commit equals or descends from minimum_commit. `compare` is injectable for tests."""
    lo, hi = pin["minimum_commit"], pin["pinned_commit"]
    if lo == hi: return None
    if compare: status = compare(lo, hi)
    elif checkout:
        r = subprocess.run(["git", "-C", checkout, "merge-base", "--is-ancestor", lo, hi])
        status = "ahead" if r.returncode == 0 else "behind" if r.returncode == 1 else "error"
    else:
        req = urllib.request.Request(f"https://api.github.com/repos/{pin['repository']}/compare/{lo}...{hi}", headers={"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r: status = json.load(r)["status"]
        except (urllib.error.URLError, KeyError, ValueError) as e: return f"cannot compare product revisions: {e}"
    if status in ("ahead", "identical"): return None
    return f"pinned product docs revision {hi[:12]} is not at or after the declared minimum {lo[:12]} (status: {status}); move the pin forward and re-import"


def main(argv=None):
    ap = argparse.ArgumentParser(); g = ap.add_mutually_exclusive_group(required=True)
    for f in ("write", "check", "drift"): g.add_argument("--" + f, action="store_true")
    ap.add_argument("--product-checkout"); ap.add_argument("--pin", default=str(PIN)); a = ap.parse_args(argv); pin = load_pin(a.pin)
    if a.drift:
        e = drift(pin, a.product_checkout)
        if e: print("FAIL:", e, file=sys.stderr); return 1
        print("ok: pin is at or after the minimum"); return 0
    pages = build(pin, a.product_checkout)
    if a.write:
        for p, t in pages.items(): p.parent.mkdir(parents=True, exist_ok=True); p.write_text(t)
        print(f"wrote {len(pages)} page(s) from {pin['pinned_commit'][:12]}"); return 0
    bad = [p for p, t in pages.items() if not p.is_file() or p.read_text() != t]
    for p in bad: print(f"FAIL: {p.relative_to(ROOT)} differs from a fresh import at the pinned revision", file=sys.stderr)
    print("ok" if not bad else f"{len(bad)} stale page(s); run --write"); return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
