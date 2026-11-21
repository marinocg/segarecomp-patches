#!/usr/bin/env python3
"""Refuse to run the release workflow in a way that could alter a published version (docs/artifact-hosting.md).

  release_guard.py --tag v0.1.0 --release-state FILE|none [--root DIR]

`--release-state` is the output of `gh release view TAG --json tagName,isDraft,assets` (or the literal `none` when no release exists).
A published release is immutable: re-running the workflow for its tag, or for any tag the catalog already lists, is refused. Even a
draft must be deleted by a maintainer first (a re-run never overwrites assets).
"""
import argparse, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def guard(tag, state, root=ROOT):
    root = pathlib.Path(root); errs = []
    if not TAG.match(tag or ""): errs.append(f"tag {tag!r} must look like v1.2.3")
    if not (root / "docs" / "release-notes" / f"{tag}.md").is_file(): errs.append(f"docs/release-notes/{tag}.md is missing")
    cat = json.loads((root / "catalog" / "index.json").read_text())
    listed = sorted({p["id"] for p in cat["packages"] if p["release"] == tag})
    if state is not None:
        if not state.get("isDraft", False): errs.append(f"release {tag} is already published: a published release is immutable. Publish a new version under a new tag instead")
        else: errs.append(f"a draft release {tag} already exists: a maintainer must delete it deliberately; the workflow never overwrites release assets")
    elif listed:
        errs.append(f"catalog/index.json already lists {', '.join(listed)} under {tag} but no such release exists: recreating a published tag would change published artifacts")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--tag", required=True); ap.add_argument("--release-state", required=True); ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    state = None if a.release_state == "none" else json.loads(pathlib.Path(a.release_state).read_text())
    errs = guard(a.tag, state, a.root)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
