#!/usr/bin/env python3
"""Claim and consistency checks for authored site pages (docs/product-docs.md, "Support claims").

  check_site_content.py [--root DIR]

Authored pages (everything under site/src/content/docs except product/ imports and the generated landing metadata) must not:
  * make blanket support claims ("all games", "universal", "guaranteed", "100% compatible", ...);
  * mention unimplemented formats (schema 3, ABI 2, Luau, WebAssembly, JIT) unless the same line negates it
    ("not", "no ", "reserved", "none", "future", "never", "unavailable", "not applicable").
The support page must link the product compatibility ledger at the pinned revision. Imported pages must carry the provenance notice.
"""
import argparse, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLANKET = re.compile(r"\b(all|every|any|most) (genesis |sega |mega drive )?(games?|titles?)\b|\buniversal(ly)?\b|\bguarantee[sd]?\b|100\s*%|\bfully (compatible|supported)\b|\bworks? with (all|any)\b", re.I)
FUTURE = re.compile(r"schema[ -]?3|\bABI[ -]?2\b|\bluau\b|\bwebassembly\b|\bwasm\b|\bJIT\b", re.I)
NEGATION = re.compile(r"\b(not|no|none|never|reserved|future|unavailable|n/a|without|isn't|aren't|nothing)\b|not applicable", re.I)


def check(root):
    root = pathlib.Path(root); docs = root / "site/src/content/docs"; errs = []
    pin = json.loads((root / "docs/product-docs.pin.json").read_text())
    for p in sorted(list(docs.rglob("*.md")) + list(docs.rglob("*.mdx"))):
        rel = p.relative_to(root).as_posix(); text = p.read_text()
        if p.relative_to(docs).parts[0] == "product":
            if "Imported product documentation" not in text: errs.append(f"{rel}: imported page lacks the provenance notice")
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if BLANKET.search(line) and not NEGATION.search(line): errs.append(f"{rel}:{n}: blanket support claim: {line.strip()[:90]!r}")
            if FUTURE.search(line) and not NEGATION.search(line): errs.append(f"{rel}:{n}: unimplemented capability not clearly negated: {line.strip()[:90]!r}")
    sp = docs / "support.md"
    if not sp.is_file(): errs.append("site/src/content/docs/support.md is missing")
    else:
        t = sp.read_text()
        for name in ("compatibility-ledger.json", "compatibility-ledger.md"):
            if f"/blob/{pin['pinned_commit']}/docs/product/{name}" not in t: errs.append(f"support.md must link {name} at the pinned revision {pin['pinned_commit'][:12]}")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(ROOT)); errs = check(ap.parse_args(argv).root)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)"); return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
