#!/usr/bin/env python3
"""Per-file publication review record for every source file of an ELIGIBLE patch (docs/source-review.md).

  check_source_review.py            fail unless docs/source-review.json has an exact, current record for every source file of every patch that
                                    publication.json marks `eligible` (legacy: source/*; schema 3: mod.toml and the files under src/, scripts/, edits/)
  check_source_review.py --write    regenerate the mechanical fields (path, SHA-256, size, class, measurements); keeps the reviewed rationale

The record is a technical content classification (what the file is, how large it is, that it carries no reconstructable image data). It is
not a legal clearance: legal and redistribution decisions are the maintainer's and are deliberately not recorded here.
"""
import argparse, hashlib, json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_meta

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLASSES = {
    ".bps": ("bps-delta", "BPS delta of at most 4 KiB: opcodes and a few literal bytes, no copy of the original image; useless without the exact source image."),
    ".json": ("package-manifest", "The exact manifest shipped inside the package: identifiers, digests and declared presentation defaults; no image content."),
    ".c": ("native-provider-source", "Original provider code written for the public SDK ABI (C11 text); it contains no embedded image, table dump or asset data."),
    ".h": ("native-provider-source", "Original provider code written for the public SDK ABI (C11 text); it contains no embedded image, table dump or asset data."),
    ".asm": ("guest-asm-source", "Original assembly text assembled by the product tool; it contains no embedded image, table dump or asset data."),
    ".edits": ("rom-edit-set", "A typed edit set (offsets and a few asserted values) applied by the product tool to an image the user owns; it carries no image content."),
    ".luau": ("luau-source", "Original Luau script text; it contains no embedded image, table dump or asset data."),
    ".toml": ("mod-manifest-source", "The schema 3 project manifest: identifiers, capabilities, declared memory ranges and image digests; no image content."),
}
MAX_BPS = 4096
RUN = re.compile(r"(?:0x[0-9A-Fa-f]{2}\s*,\s*){16,}")   # 16+ consecutive byte literals would look like an embedded data table


def classify(path):
    s = path.suffix
    if path.name.endswith(".manifest.json"): s = ".json"
    return CLASSES.get(s)


def measure(path):
    data = path.read_bytes()
    longest = max((len(re.findall(r"0x[0-9A-Fa-f]{2}", m.group(0))) for m in RUN.finditer(data.decode("latin-1"))), default=0)
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "longest_byte_literal_run": longest}


def current(root):
    """The files that need a review record: every source file of every eligible patch (publication.json), nothing else."""
    out = {}
    for pt in release_meta.patches(root):
        if release_meta.state_of(root, pt.rel) != "eligible": continue
        files = [pt.dir / "mod.toml", *sorted(f for top in ("src", "scripts", "edits") for f in (pt.dir / top).rglob("*") if f.is_file())] if pt.is_mod \
            else sorted(f for f in (pt.dir / "source").glob("*") if f.is_file())
        for f in files: out[f.relative_to(root).as_posix()] = (f, classify(f))
    return out


def check(root, errs):
    rec_file = root / "docs" / "source-review.json"
    if not rec_file.is_file(): errs.append("docs/source-review.json is missing"); return
    rec = json.loads(rec_file.read_text())
    if rec.get("record_format") != 1: errs.append("source-review: unsupported record_format")
    recs = {r.get("path"): r for r in rec.get("files", [])}
    files = current(root)
    for rel, (f, cls) in files.items():
        r = recs.get(rel)
        if cls is None: errs.append(f"source-review: {rel}: no publication class exists for this file type"); continue
        if r is None: errs.append(f"source-review: {rel}: no review record (every migrated file needs one)"); continue
        m = measure(f)
        for k, v in m.items():
            if r.get(k) != v: errs.append(f"source-review: {rel}: {k} differs from the record ({r.get(k)!r} vs {v!r}); re-review the changed file")
        if r.get("class") != cls[0] or r.get("decision") != "published" or not r.get("rationale"): errs.append(f"source-review: {rel}: class/decision/rationale is not the reviewed one")
        if cls[0] == "bps-delta" and m["size"] > MAX_BPS: errs.append(f"source-review: {rel}: BPS larger than {MAX_BPS} bytes")
        if m["longest_byte_literal_run"] >= 16: errs.append(f"source-review: {rel}: {m['longest_byte_literal_run']} consecutive byte literals look like embedded data")
    for rel in sorted(set(recs) - set(files)):
        errs.append(f"source-review: record for {rel} which is not a source file of an eligible patch (renamed, removed or no longer eligible)")
    ex = rec.get("excluded", [])
    if not ex or any(not (e.get("item") and e.get("reason")) for e in ex): errs.append("source-review: excluded items must be listed, each with a reason")


def write(root):
    rec_file = root / "docs" / "source-review.json"
    old = json.loads(rec_file.read_text()) if rec_file.is_file() else {}
    files = [{"path": rel, **measure(f), "class": cls[0], "decision": "published", "rationale": cls[1]} for rel, (f, cls) in current(root).items() if cls]
    doc = {"record_format": 1, "scope": "source files of every patch that publication.json marks eligible (v0.1.0: patches/genesis/<game>/source/, moved to patches/<platform>/<game>/<patch>/source/ with identical bytes)", "files": files, "excluded": old.get("excluded", [])}
    rec_file.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--write", action="store_true"); a = ap.parse_args(argv)
    root = pathlib.Path(a.root)
    if a.write: write(root); return 0
    errs = []; check(root, errs)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
