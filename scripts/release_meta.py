#!/usr/bin/env python3
"""The one model of release metadata shared by build_catalog, check_repo, build_packages, release_guard and prepare_release.

A game's `release.json` holds every package version ever released for it (docs/releases.md, "Release lifecycle"):

* top level `release` + `status` describe the CURRENT collection release: `prepared` (metadata and sources exist, no public release yet) or `published`;
* a package entry with its own `release` is ARCHIVED: it belongs to an older, published collection release and pins its own `source_revision` and `build`.
  Its sources are not in the working tree any more (a newer version of the same id replaced them); they are verified at the pinned commit by Git;
* every other package takes `release`, `status`, `source_revision` and `build` from the top level.

Only `published` packages reach catalog/index.json, so the site never advertises a download that does not exist.
"""
import json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def semver(v):
    m = SEMVER.match(str(v)); return tuple(map(int, m.groups())) if m else (0, 0, 0)


def games(root=ROOT):
    root = pathlib.Path(root)
    for rj in sorted((root / "patches").glob("*/*/release.json")):
        yield rj, json.loads(rj.read_text())


class Pkg:
    """One package version with its effective release facts."""
    def __init__(self, root, rj, doc, p):
        self.root, self.path, self.doc, self.p = pathlib.Path(root), rj, doc, p
        self.dir = rj.parent
        self.archived = "release" in p
        self.release = p.get("release", doc.get("release"))
        self.status = p.get("status", doc.get("status", "published"))
        self.source_revision = p.get("source_revision", doc.get("source_revision")) or {}
        self.build = p.get("build", doc.get("build")) or {}
        self.id, self.version = p.get("id"), p.get("version")

    @property
    def key(self): return (self.id, self.version)

    def read(self, rel_path):
        """Bytes of a source file: the working tree for the current release, Git at the pinned commit for an archived one."""
        if not self.archived: return (self.dir / rel_path).read_bytes()
        import subprocess
        d = self.dir.relative_to(self.root).as_posix()
        r = subprocess.run(["git", "show", f"{self.source_revision.get('commit')}:{d}/{rel_path}"], cwd=self.root, capture_output=True)
        if r.returncode != 0: raise FileNotFoundError(f"{d}/{rel_path} at {self.source_revision.get('commit')}")
        return r.stdout


def packages(root=ROOT):
    root = pathlib.Path(root)
    return [Pkg(root, rj, doc, p) for rj, doc in games(root) for p in doc.get("packages", [])]


def releases(root=ROOT):
    """{tag: {"status": ..., "packages": [Pkg]}} (a tag with conflicting statuses reports the conflict in consistency_errors)."""
    out = {}
    for pk in packages(root):
        r = out.setdefault(pk.release, {"status": pk.status, "packages": []}); r["packages"].append(pk)
    return out


def published(root=ROOT): return [pk for pk in packages(root) if pk.status == "published"]


def consistency_errors(root=ROOT):
    """Cross-file rules a per-file schema cannot express."""
    errs, pkgs = [], packages(root)
    seen = {}
    for pk in pkgs:
        n = f"{pk.id}@{pk.version}"
        if pk.key in seen: errs.append(f"{n}: duplicate (id, version): a version is released exactly once")
        seen[pk.key] = pk
        if pk.archived:
            if pk.status != "published": errs.append(f"{n}: an archived package must be published")
            if pk.release == pk.doc.get("release"): errs.append(f"{n}: has its own release equal to the current one; archive only older releases")
            if not (pk.source_revision.get("commit") and pk.build): errs.append(f"{n}: an archived package pins its own source_revision.commit and build")
        if pk.status == "published" and not pk.source_revision.get("commit"): errs.append(f"{n}: a published package needs source_revision.commit")
        if not pk.build.get("writer_ref"): errs.append(f"{n}: build.writer_ref missing")
    tags = {}
    for pk in pkgs: tags.setdefault(pk.release, set()).add(pk.status)
    for tag, st in sorted(tags.items()):
        if len(st) > 1: errs.append(f"release {tag}: packages disagree on status {sorted(st)}")
    by_id = {}
    for pk in pkgs: by_id.setdefault(pk.id, []).append(pk)
    for pid, vs in sorted(by_id.items()):
        order = sorted(vs, key=lambda x: (semver(x.release.lstrip("v")), semver(x.version)))
        for a, b in zip(order, order[1:]):
            if a.release != b.release and semver(a.version) >= semver(b.version):
                errs.append(f"{pid}: version {b.version} in {b.release} must be higher than {a.version} in {a.release}")
    return errs
