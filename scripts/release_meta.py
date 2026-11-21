#!/usr/bin/env python3
"""The one model of patch, publication and release metadata shared by every script (docs/releases.md).

Three small sources, each the single authority for one thing:

* `patches/<platform>/<game>/<patch>/`   the patch project: its sources and, once it has package versions, its `package.json` (the facts of each
                                         package version: digests, scope, evidence). A schema 3 project's `mod.toml` is authoritative for what it declares.
* `publication.json`                     which patches may ever be selected for a public release (`internal` < `candidate` < `eligible`; absent = internal).
* `releases/<tag>.json`                  one collection release: its lifecycle (`prepared` -> `published`) and its EXPLICIT allowlist of `id@version`.

A package version belongs to a release only if that release lists it. Nothing is inferred from a directory, a README or a built archive, and a release
never contains a package it does not list. Published releases are never rebuilt routinely: their stored digests and pinned source revisions are the record,
and `rebuild_release.py` reconstructs one on demand. Only `published` packages reach catalog/index.json.
"""
import json, pathlib, re, subprocess
try: import tomllib
except ImportError: tomllib = None   # Python < 3.11: schema 3 projects cannot be read (reported as a problem by lint_layout, never skipped)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PKGREF = re.compile(r"^([a-z0-9]+(?:-[a-z0-9]+)*)@((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)$")
STATES = ("internal", "candidate", "eligible")   # publication states; the default for any patch not listed is `internal`
LAYOUTS = ("game-dir", "patch-dir")              # where a release's sources lived at its source commit (docs/layout-and-versioning.md, "Historical layout")
MOD_SCHEMA = 3


def semver(v):
    m = SEMVER.match(str(v)); return tuple(map(int, m.groups())) if m else (0, 0, 0)


def read_json(path, default=None):
    path = pathlib.Path(path)
    if not path.is_file(): return default
    return json.loads(path.read_text())


class Patch:
    """One `patches/<platform>/<game>/<patch>/` directory."""
    def __init__(self, root, path):
        self.root, self.dir = pathlib.Path(root), pathlib.Path(path)
        self.platform, self.game, self.name = self.dir.parent.parent.name, self.dir.parent.name, self.dir.name
        self.rel = f"{self.platform}/{self.game}/{self.name}"          # the key used by publication.json
        self.path = self.dir.relative_to(self.root).as_posix()          # patches/<platform>/<game>/<patch>
        self.game_path = self.dir.parent.relative_to(self.root).as_posix()
        self.is_mod = (self.dir / "mod.toml").is_file()

    @property
    def meta(self): return read_json(self.dir / "package.json")

    @property
    def mod(self):
        if tomllib is None or not self.is_mod: return None
        return tomllib.loads((self.dir / "mod.toml").read_text(encoding="utf-8"))


def patches(root=ROOT):
    """Every directory at exactly patches/<platform>/<game>/<patch>/ (lint_layout reports anything else)."""
    root = pathlib.Path(root)
    return [Patch(root, d) for d in sorted((root / "patches").glob("*/*/*")) if d.is_dir()]


def publication(root=ROOT):
    return (read_json(pathlib.Path(root) / "publication.json", {}) or {}).get("patches", {})


def state_of(root, rel):
    """Effective publication state of a patch (platform/game/patch). Default and only fallback: internal (never selectable)."""
    return (publication(root).get(rel) or {}).get("state", "internal")


def release_docs(root=ROOT):
    return {p.stem: (p, json.loads(p.read_text())) for p in sorted((pathlib.Path(root) / "releases").glob("*.json"))}


class Pkg:
    """One package version with its effective release facts (release, status, source revision, build). `release` is None while no release lists it."""
    def __init__(self, root, patch, p, tag=None, rdoc=None):
        self.root, self.patch, self.p, self.rdoc = pathlib.Path(root), patch, p, rdoc or {}
        self.id, self.version = p.get("id"), p.get("version")
        self.release, self.dir = tag, patch.dir
        self.status = self.rdoc.get("status", "unreleased")
        self.source_revision = self.rdoc.get("source_revision") or {}
        self.build = p.get("build") or self.rdoc.get("build") or {}
        self.is_mod = p.get("schema_version") == MOD_SCHEMA

    @property
    def key(self): return (self.id, self.version)

    @property
    def ref(self): return f"{self.id}@{self.version}"

    @property
    def package_file(self): return self.p.get("package_file") or f"{self.id}.segapatch"

    @property
    def asset(self):
        """Stored for packages published before the layout migration; derived from the release for every newer one (never a second copy to keep in sync)."""
        if self.p.get("asset"): return self.p["asset"]
        repo = self.source_revision.get("repository") or "https://github.com/marinocg/segarecomp-patches"
        return {"name": self.package_file, "url": f"{repo}/releases/download/{self.release}/{self.package_file}"}

    @property
    def layout(self): return self.rdoc.get("source_layout", "patch-dir")

    @property
    def source_base(self):
        """Directory (repo-relative) that holds this package's sources at its source commit. Old releases kept `source/` directly in the game directory."""
        return self.patch.game_path if self.layout == "game-dir" else self.patch.path

    def read(self, rel_path):
        """Bytes of a package source file: the working tree while the release is not published, Git at the pinned source commit once it is."""
        if self.status != "published": return (self.dir / rel_path).read_bytes()
        commit = self.source_revision.get("commit")
        r = subprocess.run(["git", "show", f"{commit}:{self.source_base}/{rel_path}"], cwd=self.root, capture_output=True)
        if r.returncode != 0: raise FileNotFoundError(f"{self.source_base}/{rel_path} at {commit}")
        return r.stdout


def all_packages(root=ROOT):
    """(patch, entry) for every package version recorded in any patch's package.json."""
    out = []
    for pt in patches(root):
        meta = pt.meta
        if isinstance(meta, dict):
            out += [(pt, p) for p in meta.get("packages", []) if isinstance(p, dict)]
    return out


def membership(root=ROOT):
    """{ "id@version": tag } from every release record; a package listed twice maps to its first release (consistency_errors reports it)."""
    out = {}
    for tag, (_, doc) in release_docs(root).items():
        for ref in doc.get("packages", []) if isinstance(doc, dict) else []:
            out.setdefault(ref, tag)
    return out


def packages(root=ROOT):
    """Every package version, each bound to the release that lists it (or unreleased)."""
    root, docs, member = pathlib.Path(root), release_docs(root), membership(root)
    out = []
    for pt, p in all_packages(root):
        tag = member.get(f"{p.get('id')}@{p.get('version')}")
        out.append(Pkg(root, pt, p, tag, docs[tag][1] if tag else None))
    return out


def releases(root=ROOT):
    """{tag: {"status", "doc", "packages": [Pkg]}} in the release record's own (sorted) order; unresolvable references are consistency_errors."""
    root = pathlib.Path(root); by_ref = {pk.ref: pk for pk in packages(root)}
    out = {}
    for tag, (_, doc) in release_docs(root).items():
        refs = doc.get("packages", []) if isinstance(doc, dict) else []
        out[tag] = {"status": doc.get("status"), "doc": doc, "packages": [by_ref[r] for r in refs if r in by_ref and by_ref[r].release == tag]}
    return out


def published(root=ROOT): return [pk for pk in packages(root) if pk.status == "published"]


def sort_key(pk): return (pk.patch.game_path, pk.patch.path, pk.id, semver(pk.version))


def consistency_errors(root=ROOT):
    """Cross-file rules a per-file schema cannot express: explicit selection, eligibility, uniqueness, immutability of membership and version order."""
    root = pathlib.Path(root); errs = []
    pub, docs = publication(root), release_docs(root)
    names = {pt.rel for pt in patches(root)}
    for rel, v in sorted(pub.items()):
        if rel not in names: errs.append(f"publication.json: {rel} is not a patch directory (patches/<platform>/<game>/<patch>)")
        if not isinstance(v, dict) or v.get("state") not in STATES: errs.append(f"publication.json: {rel}: state must be one of {', '.join(STATES)}"); continue
        if v["state"] == "eligible" and not str(v.get("review", "")).strip(): errs.append(f"publication.json: {rel}: an eligible patch records its publication review (`review`)")
    defined, owner = {}, {}
    for pt, p in all_packages(root):
        ref = f"{p.get('id')}@{p.get('version')}"
        if ref in defined: errs.append(f"{ref}: defined twice ({defined[ref]} and {pt.rel}): a version is released exactly once")
        defined.setdefault(ref, pt.rel)
        if owner.setdefault(p.get("id"), pt.rel) != pt.rel: errs.append(f"{p.get('id')}: package id used by two patches ({owner[p.get('id')]} and {pt.rel})")
    first = {}
    for tag, (path, doc) in docs.items():
        w = f"releases/{path.name}"
        if not isinstance(doc, dict): errs.append(f"{w}: not an object"); continue
        if not TAG.match(tag): errs.append(f"{w}: file name must be a collection release tag such as v1.2.3.json")
        if doc.get("release") != tag: errs.append(f"{w}: `release` {doc.get('release')!r} differs from the file name")
        if doc.get("status") not in ("prepared", "published"): errs.append(f"{w}: status must be prepared or published")
        if doc.get("source_layout") not in LAYOUTS: errs.append(f"{w}: source_layout must be one of {', '.join(LAYOUTS)}")
        refs = doc.get("packages")
        if not isinstance(refs, list) or not refs: errs.append(f"{w}: packages must be a non-empty explicit list of id@version"); continue
        if refs != sorted(refs): errs.append(f"{w}: packages must be sorted (deterministic membership)")
        if len(set(refs)) != len(refs): errs.append(f"{w}: duplicate package selection {sorted({r for r in refs if refs.count(r) > 1})}")
        sr = doc.get("source_revision") or {}
        if doc.get("status") == "published":
            if not sr.get("commit"): errs.append(f"{w}: a published release pins source_revision.commit")
            if not sr.get("tag"): errs.append(f"{w}: a published release records its tag")
        elif sr.get("commit") or sr.get("tag") or sr.get("tag_commit"): errs.append(f"{w}: a prepared release cannot pin a commit or tag yet")
        for r in dict.fromkeys(refs):
            if not isinstance(r, str) or not PKGREF.match(r): errs.append(f"{w}: {r!r} is not an exact id@version selection"); continue
            if r in first: errs.append(f"{r}: selected by {first[r]} and {tag}: a version is released exactly once"); continue
            first[r] = tag
            if r not in defined: errs.append(f"{w}: unknown package {r}: no package.json records it"); continue
            st = state_of(root, defined[r])
            if st != "eligible": errs.append(f"{w}: {r}: patch {defined[r]} is {st}, not eligible for a public release")
    by_id = {}
    for pk in packages(root):
        if pk.release is None: continue
        if not pk.build.get("writer_ref"): errs.append(f"{pk.ref}: build.writer_ref missing (the entry's or its release's)")
        by_id.setdefault(pk.id, []).append(pk)
    for pid, vs in sorted(by_id.items()):
        order = sorted(vs, key=lambda x: (semver(x.release.lstrip("v")), semver(x.version)))
        for a, b in zip(order, order[1:]):
            if a.release != b.release and semver(a.version) >= semver(b.version):
                errs.append(f"{pid}: version {b.version} in {b.release} must be higher than {a.version} in {a.release}")
    return errs


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


def changed_paths(root, base):
    """Repo-relative paths changed between `base` and the working tree (both sides of a rename, deletions, uncommitted work). Fails closed (SystemExit) when `base` is not a commit."""
    root = pathlib.Path(root)
    _git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    return sorted({l for cmd in (("diff", "--name-only", "--no-renames", f"{base}...HEAD"), ("diff", "--name-only", "--no-renames", "HEAD")) for l in _git(root, *cmd).splitlines() if l})


def is_shared_change(changed):
    return any(c.startswith(SHARED_PREFIXES) and not c.startswith(SHARED_IGNORED) for c in changed)


def affected_tags(root, base):
    """The prepared (not published) releases a change since `base` can affect. Published releases are never selected. Fails closed (SystemExit) when `base` is not a commit.

    A release is affected when: its own releases/<tag>.json changed or is new; a file of a patch directory that one of its packages comes from changed, was added, deleted or
    renamed; the publication state of such a patch changed; or a shared build/validation path changed (then every prepared release is affected). Documentation and site changes
    affect nothing. This is a path-to-release lookup over the existing records, not a dependency graph."""
    root = pathlib.Path(root); changed = changed_paths(root, base)
    prepared = {t: r for t, r in releases(root).items() if r["status"] != "published"}
    if is_shared_change(changed): return sorted(prepared)
    old, new = _publication_at(root, base), publication(root)
    flipped = {rel for rel in set(old) | set(new) if old.get(rel) != new.get(rel)}
    hit = set()
    for tag, r in prepared.items():
        if f"releases/{tag}.json" in changed: hit.add(tag); continue
        for pk in r["packages"]:
            if pk.patch.rel in flipped or any(c.startswith(pk.patch.path + "/") for c in changed): hit.add(tag); break
    return sorted(hit)
