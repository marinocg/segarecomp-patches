#!/usr/bin/env python3
"""Refuse to run the release workflow in a way that could alter a published version (docs/artifact-hosting.md, docs/releases.md).

  release_guard.py --tag v0.2.0 --release-state FILE|none [--root DIR]

`--release-state` is the output of `gh release view TAG --json tagName,isDraft` (or the literal `none` when no release exists). The guard
reads the repository's release metadata (scripts/release_meta.py) and distinguishes:

  * a genuinely new release     metadata `prepared` + no GitHub release            -> allowed
  * an existing draft           metadata `prepared` + draft                         -> refused: a maintainer deletes a draft deliberately
  * an already published one    metadata `published` + published release           -> refused: immutable
  * a deleted/inconsistent one  published without a release, a draft, or a published release whose metadata is still `prepared` -> refused
  * a tag with no metadata      nothing prepared for it                             -> refused
  * a superseding version       a prepared package id that already has published versions must be strictly higher; re-releasing a
                                 published (id, version) is refused. Supersession itself is recorded additively after publication.
"""
import argparse, json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_meta

ROOT = pathlib.Path(__file__).resolve().parent.parent
TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def supersedes(tag, root=ROOT):
    """[(new, old)] pairs: prepared packages of `tag` and the published version of the same id each one supersedes."""
    pkgs = release_meta.packages(root); out = []
    for new in (p for p in pkgs if p.release == tag and p.status == "prepared"):
        old = [o for o in pkgs if o.id == new.id and o.status == "published" and o.release != tag]
        if old: out.append((f"{new.id}@{new.version}", f"{max(old, key=lambda o: release_meta.semver(o.version)).id}@{max(old, key=lambda o: release_meta.semver(o.version)).version}"))
    return out


def guard(tag, state, root=ROOT):
    root = pathlib.Path(root); errs = []
    if not TAG.match(tag or ""): return [f"tag {tag!r} must look like v1.2.3"]
    meta = release_meta.releases(root).get(tag)
    if meta is None:
        return [f"no packages are recorded for {tag}: prepare its metadata first (scripts/prepare_release.py begin)"]
    if not (root / "docs" / "release-notes" / f"{tag}.md").is_file(): errs.append(f"docs/release-notes/{tag}.md is missing")
    published = meta["status"] == "published"
    if state is None:
        if published: errs.append(f"{tag} is recorded as published but no GitHub release exists (deleted or inconsistent): recreating a published tag would change published artifacts")
    elif published:
        errs.append(f"release {tag} is already published and immutable. Publish a new version under a new tag instead" if not state.get("isDraft", False)
                    else f"{tag} is recorded as published but its GitHub release is a draft: inconsistent, resolve manually")
    elif state.get("isDraft", False):
        errs.append(f"a draft release {tag} already exists: a maintainer must delete it deliberately; the workflow never overwrites release assets")
    else:
        errs.append(f"release {tag} is already published on GitHub but its metadata is still `prepared`: record it with scripts/prepare_release.py publish; the workflow never recreates it")
    if not published:
        pkgs = release_meta.packages(root)
        for new in (p for p in meta["packages"] if p.status == "prepared"):
            for o in (p for p in pkgs if p.id == new.id and p.status == "published" and p.release != tag):
                if release_meta.semver(new.version) <= release_meta.semver(o.version):
                    errs.append(f"{new.id}@{new.version} does not supersede published {o.id}@{o.version}: a published version is never replaced, publish a higher version")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--tag", required=True); ap.add_argument("--release-state", required=True); ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    state = None if a.release_state == "none" else json.loads(pathlib.Path(a.release_state).read_text())
    errs = guard(a.tag, state, a.root)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    if not errs:
        for new, old in supersedes(a.tag, a.root): print(f"note: {new} supersedes published {old} (the old version stays available and unchanged)")
    print("ok" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
