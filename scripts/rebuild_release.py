#!/usr/bin/env python3
"""Rebuild and verify the packages of selected collection releases, each with the tool revision recorded for it.

  rebuild_release.py --release v0.2.0 --work DIR     ONE release (what the release workflow does): its listed packages only
  rebuild_release.py --affected-from BASE --work DIR the prepared releases a pull request affects (what CI does): see affected_tags()
  rebuild_release.py --prepared --work DIR           every release that is not published yet
  rebuild_release.py --all --work DIR                FULL AUDIT: every recorded release, published ones from Git at their pinned commit (manual/scheduled)
  rebuild_release.py --list                          the recorded release tags (the audit workflow loops over them, building each release's own product revision)

Routine work (`--release`, `--affected-from`, `--prepared`) never touches a published release: a historical package is verified by its stored digest, its pinned source
commit (verify_provenance.py) and the immutability check against the base branch, and is rebuilt only on demand (`--release <old tag>` or `--all`).

The schema 1/2 writer (the product's `tools/segapatch.py`) is fetched at the release's `build.writer_ref`; `--writer-url` may be any URL template with
`{ref}` (tests use file://). Schema 3 packages are built by the product CLI you pass with `--segarecomp`, which must have been built at the release's
pinned product revision (`--segarecomp-ref`, from `build_packages.py --release TAG --print-product-ref`); a mismatch fails closed. Needs no game image and no secrets.
"""
import argparse, io, contextlib, json, pathlib, subprocess, sys, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_packages, check_repo, release_meta

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_URL = "https://raw.githubusercontent.com/marinocg/segarecomp/{ref}/tools/segapatch.py"


# Paths whose change can alter how ANY package is built or validated: every prepared release is then rebuilt (conservative, never silently skipped).
SHARED_PREFIXES = ("scripts/", "catalog/schema/")
SHARED_IGNORED = ("scripts/check_site_", "scripts/import_product_docs", "scripts/run_guide_samples", "scripts/artifact_budget", "scripts/synthetic_fixture", "scripts/gen_castle_retry")


def _git(root, *args):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if r.returncode != 0: raise SystemExit(f"affected-release detection cannot be trusted: git {' '.join(args)}: {r.stderr.strip() or 'failed'}")
    return r.stdout


def _publication_at(root, base):
    r = subprocess.run(["git", "show", f"{base}:publication.json"], cwd=root, capture_output=True, text=True)
    return (json.loads(r.stdout).get("patches", {}) if r.returncode == 0 else {})


def affected_tags(root, base):
    """The prepared (not published) releases a change since `base` can affect. Published releases are never selected. Fails closed (SystemExit) when `base` is not a commit.

    A release is affected when: its own releases/<tag>.json changed or is new; a file of a patch directory that one of its packages comes from changed, was added, deleted or
    renamed; the publication state of such a patch changed; or a shared build/validation path changed (then every prepared release is affected). Documentation and site changes
    affect nothing. This is a path-to-release lookup over the existing records, not a dependency graph."""
    root = pathlib.Path(root)
    _git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    changed = [l for l in _git(root, "diff", "--name-only", "--no-renames", f"{base}...HEAD").splitlines() if l]   # --no-renames: both the old and the new path of a rename
    changed += [l for l in _git(root, "diff", "--name-only", "--no-renames", "HEAD").splitlines() if l]              # uncommitted work counts too
    prepared = {t: r for t, r in release_meta.releases(root).items() if r["status"] != "published"}
    if any(c.startswith(SHARED_PREFIXES) and not c.startswith(SHARED_IGNORED) for c in changed): return sorted(prepared)
    old, new = _publication_at(root, base), release_meta.publication(root)
    flipped = {rel for rel in set(old) | set(new) if old.get(rel) != new.get(rel)}
    hit = set()
    for tag, r in prepared.items():
        if f"releases/{tag}.json" in changed: hit.add(tag); continue
        for pk in r["packages"]:
            if pk.patch.rel in flipped or any(c.startswith(pk.patch.path + "/") for c in changed): hit.add(tag); break
    return sorted(hit)


def _print(root, tag, flag):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): build_packages.main(["--root", str(root), "--release", tag, flag])
    except SystemExit as e:
        if "has no" in str(e): return None
        raise
    return buf.getvalue().strip()


def rebuild(root, tag, work, url, cli=None, cli_ref=None, sdk_dir=None, cc=None):
    work = pathlib.Path(work); out = work / tag; args = ["--root", str(root), "--release", tag, "--out", str(out)]
    ref, pref = _print(root, tag, "--print-writer-ref"), _print(root, tag, "--print-product-ref")
    if ref:
        writer = work / f"segapatch-{ref}.py"
        if not writer.is_file(): work.mkdir(parents=True, exist_ok=True); urllib.request.urlretrieve(url.format(ref=ref), writer)
        args += ["--segapatch", str(writer)]
    if pref:
        if not cli: print(f"FAIL: release {tag} has schema 3 packages: pass --segarecomp built at product revision {pref}", file=sys.stderr); return 1
        args += ["--segarecomp", str(cli), "--segarecomp-ref", cli_ref or ""] + [x for k, v in (("--cc", cc), ("--sdk-dir", sdk_dir)) if v for x in (k, v)]
    try: rc = build_packages.main(args)
    except SystemExit as e: print(f"FAIL: {e}", file=sys.stderr); return 1
    errs = []; check_repo.check_assets(root, out, cli if pref else None, errs, tag)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    return 1 if rc or errs else 0


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--work"); ap.add_argument("--release"); ap.add_argument("--list", action="store_true")
    ap.add_argument("--prepared", action="store_true"); ap.add_argument("--affected-from", metavar="BASE"); ap.add_argument("--all", action="store_true"); ap.add_argument("--writer-url", default=DEFAULT_URL)
    ap.add_argument("--segarecomp"); ap.add_argument("--segarecomp-ref"); ap.add_argument("--sdk-dir"); ap.add_argument("--cc")
    a = ap.parse_args(argv)
    root = pathlib.Path(a.root); rels = release_meta.releases(root)
    if a.list: print("\n".join(sorted(rels))); return 0
    if sum([bool(a.release), a.prepared, a.all, bool(a.affected_from)]) != 1 or not a.work: ap.error("pass --work DIR and exactly one of --release TAG, --affected-from BASE, --prepared or --all")
    work = pathlib.Path(a.work)
    if a.all: tags = sorted(rels)
    elif a.affected_from: tags = affected_tags(root, a.affected_from)
    elif a.prepared: tags = sorted(t for t, r in rels.items() if r["status"] != "published")
    else: tags = [a.release]
    rc = 0
    for t in tags: rc |= rebuild(root, t, work, a.writer_url, a.segarecomp, a.segarecomp_ref, a.sdk_dir, a.cc)
    print(f"{len(tags)} release(s): " + ("ok" if not rc else "FAILED") + (" (nothing to rebuild)" if not tags else "") + (f" [{', '.join(tags)}]" if a.affected_from and tags else "")); return rc


if __name__ == "__main__":
    sys.exit(main())
