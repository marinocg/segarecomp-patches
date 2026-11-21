#!/usr/bin/env python3
"""Tie every published package to a reachable source commit and a reproducible source tree (docs/artifact-hosting.md).

  verify_provenance.py [--root DIR] [--head REF]     needs full Git history (CI checks out with fetch-depth: 0)

Per published release (releases/<tag>.json), resolving each package's sources at its pinned commit in the layout that commit actually had
(`source_layout`: `game-dir` for v0.1.0, `patch-dir` afterwards), so moving files later never breaks an old release. For every `source_revision`:
  * `commit` exists and is an ancestor of HEAD (a source link that a force-push or an unmerged branch could orphan is refused);
  * the declared tag EXISTS (a missing tag fails) and equals the release; it resolves to `commit`, or, where the historical exception applies
    (`tag_commit` recorded: the v0.1.0 tag points at the pre-squash PR head, which is NOT on `main`), exactly to `tag_commit`, whose tree equals the source commit's;
  * at `commit`, each schema 1/2 package's manifest, BPS and provider source have exactly the digests recorded in package.json, and each schema 3
    package's `mod.toml` names its id and version, so a rebuild from that commit (scripts/rebuild_release.py --release TAG) reproduces the package.
This reads Git blobs only; it builds nothing.
"""
import argparse, hashlib, json, pathlib, subprocess, sys
try: import tomllib
except ImportError: tomllib = None
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_meta

ROOT = pathlib.Path(__file__).resolve().parent.parent


def git(root, *a):
    return subprocess.run(["git", *a], cwd=root, capture_output=True)


def blob(root, commit, path):
    r = git(root, "show", f"{commit}:{path}")
    return r.stdout if r.returncode == 0 else None


def verify(root, errs, head="HEAD"):
    root = pathlib.Path(root)
    if git(root, "rev-parse", "--git-dir").returncode != 0: errs.append("provenance: not a Git checkout"); return
    if git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == b"true": errs.append("provenance: shallow clone; fetch full history (fetch-depth: 0)"); return
    done = set()
    for pk in release_meta.packages(root):
        if pk.status != "published":
            if pk.source_revision.get("tag") or pk.source_revision.get("tag_commit"): errs.append(f"provenance: {pk.id}@{pk.version}: a prepared release cannot declare a tag yet")
            continue
        sr, d, c = pk.source_revision, pk.source_base, pk.source_revision.get("commit", "")
        n = f"{pk.release} {pk.id}@{pk.version}"
        if (pk.release, c) not in done:   # one commit/tag verdict per release, not per package
            done.add((pk.release, c))
            if git(root, "cat-file", "-e", f"{c}^{{commit}}").returncode != 0: errs.append(f"provenance: {n}: source commit {c} does not exist"); continue
            if git(root, "merge-base", "--is-ancestor", c, head).returncode != 0: errs.append(f"provenance: {n}: source commit {c} is not an ancestor of {head}")
            tag, tc = sr.get("tag"), sr.get("tag_commit")
            if tc and not tag: errs.append(f"provenance: {n}: tag_commit without a tag")
            if not tag: errs.append(f"provenance: {n}: a published release must declare its tag")
            else:
                if tag != pk.release: errs.append(f"provenance: {n}: source_revision.tag {tag!r} is not the release {pk.release!r}")
                r = git(root, "rev-parse", "--verify", "-q", f"refs/tags/{tag}^{{commit}}")
                if r.returncode != 0: errs.append(f"provenance: {n}: declared tag {tag} does not exist (fetch tags: fetch-depth: 0)")
                else:
                    got = r.stdout.decode().strip()
                    if tc:   # the historical exception: the tag points at a pre-squash head that is NOT on main but has the same tree
                        if got != tc: errs.append(f"provenance: {n}: tag {tag} resolves to {got[:12]}, not the recorded tag_commit {tc[:12]}")
                        elif git(root, "rev-parse", f"{c}^{{tree}}").stdout != git(root, "rev-parse", f"{tc}^{{tree}}").stdout: errs.append(f"provenance: {n}: tag commit tree differs from the source commit tree")
                    elif got != c: errs.append(f"provenance: {n}: tag {tag} resolves to {got[:12]}, not the source commit {c[:12]}")
        p = pk.p
        if pk.is_mod:
            data = blob(root, c, f"{d}/mod.toml")
            if data is None: errs.append(f"provenance: {p['id']}: {d}/mod.toml not present at {c[:12]}"); continue
            try: m = (tomllib.loads(data.decode()) if tomllib else {}).get("mod", {})
            except ValueError: m = {}
            if (m.get("id"), m.get("version")) != (p["id"], p["version"]): errs.append(f"provenance: {p['id']}: mod.toml at {c[:12]} does not declare {p['id']}@{p['version']}")
            continue
        files = [(f"{d}/source/{p['id']}.manifest.json", None), (f"{d}/{p['bps']['path']}", p["bps"]["sha256"])]
        if p.get("source"): files.append((f"{d}/{p['source']['path']}", p["source"]["sha256"]))
        for path, want in files:
            data = blob(root, c, path)
            if data is None: errs.append(f"provenance: {p['id']}: {path} not present at {c[:12]}"); continue
            if want and hashlib.sha256(data).hexdigest() != want: errs.append(f"provenance: {p['id']}: {path} at {c[:12]} differs from package.json")
            if want is None:
                m = json.loads(data); pl = m.get("payloads", {})
                if (m.get("id"), m.get("version"), pl.get("rom", {}).get("sha256")) != (p["id"], p["version"], p["bps_sha256"]): errs.append(f"provenance: {p['id']}: manifest at {c[:12]} differs from package.json")


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--head", default="HEAD"); a = ap.parse_args(argv)
    errs = []; verify(a.root, errs, a.head)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
