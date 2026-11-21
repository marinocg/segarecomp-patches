#!/usr/bin/env python3
"""Rebuild and verify the packages of one (or every) collection release, each with the package writer revision recorded for it.

  rebuild_release.py --release v0.1.0 --work DIR      rebuild one release into DIR/<tag>/ (+ SHA256SUMS) and verify it against its metadata
  rebuild_release.py --all --work DIR                 every recorded release, published or prepared, each independently

The writer (the product's `tools/segapatch.py`) is fetched at `build.writer_ref` of the release, so an old release is verified with the writer
that built it. `--writer-url` may be any URL template with `{ref}` (tests use file://). Needs no game image and no secrets.
"""
import argparse, pathlib, sys, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_packages, check_repo, release_meta

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_URL = "https://raw.githubusercontent.com/marinocg/segarecomp/{ref}/tools/segapatch.py"


def rebuild(root, tag, work, url):
    ref = None
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): build_packages.main(["--root", str(root), "--release", tag, "--print-writer-ref"])
    ref = buf.getvalue().strip()
    writer = work / f"segapatch-{ref}.py"
    if not writer.is_file(): work.mkdir(parents=True, exist_ok=True); urllib.request.urlretrieve(url.format(ref=ref), writer)
    out = work / tag
    rc = build_packages.main(["--root", str(root), "--release", tag, "--segapatch", str(writer), "--out", str(out)])
    errs = []; check_repo.check_assets(root, out, None, errs, tag)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    return 1 if rc or errs else 0


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--work", required=True); ap.add_argument("--release"); ap.add_argument("--all", action="store_true")
    ap.add_argument("--writer-url", default=DEFAULT_URL); a = ap.parse_args(argv)
    if bool(a.release) == a.all: ap.error("pass exactly one of --release TAG or --all")
    root, work = pathlib.Path(a.root), pathlib.Path(a.work)
    tags = sorted(release_meta.releases(root)) if a.all else [a.release]
    rc = 0
    for t in tags: rc |= rebuild(root, t, work, a.writer_url)
    print("ok" if not rc else "FAILED"); return rc


if __name__ == "__main__":
    sys.exit(main())
