#!/usr/bin/env python3
"""Tie every published package to a reachable source commit and a reproducible source tree (docs/artifact-hosting.md).

  verify_provenance.py [--root DIR] [--head REF]     needs full Git history (CI checks out with fetch-depth: 0)

For every release.json `source_revision`:
  * `commit` exists and is an ancestor of HEAD (a source link that a force-push or an unmerged branch could orphan is refused);
  * when `tag`/`tag_commit` are recorded the tag still resolves to `tag_commit` and has the same tree as `commit`
    (the v0.1.0 tag points at the pre-squash PR head, which is NOT on `main`; its tree equals the squash commit's);
  * at `commit`, each package's manifest, BPS and provider source have exactly the digests recorded in release.json,
    so a rebuild from that commit (scripts/build_packages.py) reproduces the published package.
"""
import argparse, hashlib, json, pathlib, subprocess, sys

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
    for rj in sorted((root / "patches").glob("*/*/release.json")):
        rel = json.loads(rj.read_text()); d = rj.parent.relative_to(root).as_posix(); sr = rel.get("source_revision", {})
        c = sr.get("commit", ""); n = f"{d}"
        if git(root, "cat-file", "-e", f"{c}^{{commit}}").returncode != 0: errs.append(f"provenance: {n}: source commit {c} does not exist"); continue
        if git(root, "merge-base", "--is-ancestor", c, head).returncode != 0: errs.append(f"provenance: {n}: source commit {c} is not an ancestor of {head}")
        tc = sr.get("tag_commit")
        if tc:
            if git(root, "cat-file", "-e", f"{tc}^{{commit}}").returncode != 0: errs.append(f"provenance: {n}: tag commit {tc} does not exist"); 
            else:
                t1, t2 = git(root, "rev-parse", f"{c}^{{tree}}").stdout, git(root, "rev-parse", f"{tc}^{{tree}}").stdout
                if t1 != t2: errs.append(f"provenance: {n}: tag commit tree differs from the source commit tree")
            tag = sr.get("tag")
            r = git(root, "rev-parse", "--verify", "-q", f"refs/tags/{tag}^{{commit}}")
            if r.returncode == 0 and r.stdout.decode().strip() != tc: errs.append(f"provenance: {n}: tag {tag} no longer points at {tc}")
        for p in rel["packages"]:
            files = [(f"{d}/source/{p['id']}.manifest.json", None), (f"{d}/{p['bps']['path']}", p["bps"]["sha256"])]
            if p.get("source"): files.append((f"{d}/{p['source']['path']}", p["source"]["sha256"]))
            for path, want in files:
                data = blob(root, c, path)
                if data is None: errs.append(f"provenance: {p['id']}: {path} not present at {c[:12]}"); continue
                if want and hashlib.sha256(data).hexdigest() != want: errs.append(f"provenance: {p['id']}: {path} at {c[:12]} differs from release.json")
                if want is None:
                    m = json.loads(data); pl = m.get("payloads", {})
                    if (m.get("id"), m.get("version"), pl.get("rom", {}).get("sha256")) != (p["id"], p["version"], p["bps_sha256"]): errs.append(f"provenance: {p['id']}: manifest at {c[:12]} differs from release.json")


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--head", default="HEAD"); a = ap.parse_args(argv)
    errs = []; verify(a.root, errs, a.head)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
