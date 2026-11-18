#!/usr/bin/env python3
"""Layout and versioning lint for patch projects (docs/layout-and-versioning.md).

  lint_layout.py [--root DIR]

Checks the structure of every `patches/<platform>/<game>/` directory and the versioning fields of its `release.json`.
Digest, license, catalog and forbidden-content checks stay in check_repo.py, which calls `lint()` so a pull request cannot skip it.
"""
import argparse, json, pathlib, re, sys
try: import tomllib
except ImportError: tomllib = None   # Python < 3.11: schema 3 projects cannot be linted there (reported as a problem, never skipped)

PLATFORMS = {"genesis", "master-system", "game-gear", "sega-cd"}
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
COLLECTION = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SCHEMAS = {1, 2}          # .segapatch schemas this repository PUBLISHES (release.json). A schema 3 `mod.toml` project is accepted as an UNPUBLISHED, locally buildable source project only (see _mod_project).
NATIVE_ABIS = {1}
PROJECT_ENTRIES = {"README.md", "release.json", "source", "tests"}
MOD_ENTRIES = {"README.md", "mod.toml", "src", "scripts", "edits", "tests"}   # an unpublished schema 3 project: no release.json, so it can never reach the catalog or a release
MOD_SOURCE_EXT = {"native-c11": {".c", ".h"}, "luau-source": {".luau"}, "rom-edit-set": {".edits"}, "guest-asm": {".asm"}}   # what a schema 3 project may commit as source: text only, never a binary payload
MOD_NATIVE_ABI = 2


def lint(root, errs):
    root = pathlib.Path(root)
    pr = root / "patches"
    if not pr.is_dir():
        errs.append("layout: patches/ is missing"); return
    for platform in sorted(pr.iterdir()):
        if not platform.is_dir():
            errs.append(f"layout: unexpected file patches/{platform.name} (projects live in patches/<platform>/<game>/)"); continue
        if platform.name not in PLATFORMS:
            errs.append(f"layout: unknown platform directory patches/{platform.name} (allowed: {', '.join(sorted(PLATFORMS))})")
        for game in sorted(platform.iterdir()):
            where = f"patches/{platform.name}/{game.name}"
            if not game.is_dir():
                errs.append(f"layout: unexpected file {where}"); continue
            _project(game, platform.name, where, errs)


def mod_projects(root):
    """Every `patches/<platform>/<game>/` directory that holds a `mod.toml` (schema 3, unpublished)."""
    return sorted(p.parent for p in pathlib.Path(root).glob("patches/*/*/mod.toml"))


def _safe_relpath(value):
    return isinstance(value, str) and value != "" and "\\" not in value and not value.startswith("/") and ".." not in value.split("/") and not re.match(r"^[A-Za-z]:", value)


def _mod_project(d, platform, where, errs):
    """Schema 3 source project (docs/layout-and-versioning.md): `mod.toml` plus the files it declares. The product's `segarecomp mod check/pack` is the authority for the manifest and package;
    this lint only checks what the repository itself promises: layout, declared files, safe paths, text-only sources and the schema/ABI combination. No release.json: nothing here is published."""
    if not SLUG.match(d.name): errs.append(f"layout: {where}: directory name must be a lowercase slug")
    for e in sorted(d.iterdir()):
        if e.name == "release.json": errs.append(f"layout: {where}: release.json cannot accompany mod.toml (a schema 3 project is unpublished source; published schema 3 releases are not supported yet)")
        elif e.name not in MOD_ENTRIES: errs.append(f"layout: {where}: unexpected entry {e.name!r} (allowed: README.md, mod.toml, src/, scripts/, edits/, tests/)")
    if not (d / "README.md").is_file(): errs.append(f"layout: {where}: missing README.md")
    tests = d / "tests"
    if tests.is_dir():
        for f in tests.rglob("*"):
            if f.is_file() and f.suffix not in {".json", ".md"}: errs.append(f"layout: {where}/tests/{f.name}: only synthetic .json/.md expectations are allowed")
    if tomllib is None:
        errs.append(f"layout: {where}: Python 3.11+ is required to lint a schema 3 project"); return
    try: m = tomllib.loads((d / "mod.toml").read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        errs.append(f"layout: {where}/mod.toml is malformed: {e}"); return
    if (m.get("target") or {}).get("platform") != platform: errs.append(f"layout: {where}: mod.toml target platform differs from directory {platform!r}")
    sources = m.get("source") or []
    if not isinstance(sources, list) or not sources:
        errs.append(f"layout: {where}: mod.toml declares no [[source]]"); return
    declared, kinds = set(), set()
    for src in sources:
        kind, path = (src or {}).get("kind"), (src or {}).get("path")
        if not _safe_relpath(path): errs.append(f"layout: {where}: unsafe or empty source path {path!r}"); continue
        kinds.add(kind)
        if kind not in MOD_SOURCE_EXT: errs.append(f"layout: {where}: source kind {kind!r} is not accepted in a repository project (allowed: {', '.join(sorted(MOD_SOURCE_EXT))})"); continue
        if pathlib.PurePosixPath(path).suffix not in MOD_SOURCE_EXT[kind]: errs.append(f"layout: {where}/{path}: disallowed file type for {kind}")
        top = pathlib.PurePosixPath(path).parts[0]
        if top not in {"src", "scripts", "edits"}: errs.append(f"layout: {where}/{path}: sources live under src/, scripts/ or edits/")
        if not (d / path).is_file(): errs.append(f"layout: {where}: declared source {path} is missing")
        declared.add(path)
    abi = (m.get("abi") or {}).get("native")
    if "native-c11" in kinds and abi != MOD_NATIVE_ABI: errs.append(f"layout: {where}: native-c11 source requires [abi] native = {MOD_NATIVE_ABI} (got {abi!r})")
    if "native-c11" not in kinds and abi is not None: errs.append(f"layout: {where}: [abi] native is declared but no native-c11 source is")
    for top in ("src", "scripts", "edits"):
        base = d / top
        if not base.exists(): continue
        for f in sorted(base.rglob("*")):
            if not f.is_file(): continue
            rel = f.relative_to(d).as_posix()
            if f.is_symlink(): errs.append(f"layout: {where}/{rel}: links are not allowed")
            elif rel not in declared: errs.append(f"layout: {where}/{rel}: not a declared source file (declare it as a [[source]] in mod.toml or remove it)")


def _project(d, platform, where, errs):
    if (d / "mod.toml").exists():
        _mod_project(d, platform, where, errs); return
    if not SLUG.match(d.name): errs.append(f"layout: {where}: directory name must be a lowercase slug")
    for e in sorted(d.iterdir()):
        if e.name not in PROJECT_ENTRIES:
            errs.append(f"layout: {where}: unexpected entry {e.name!r} (allowed: README.md, release.json, source/, tests/)")
    for need, kind in (("README.md", "is_file"), ("release.json", "is_file"), ("source", "is_dir")):
        if not getattr(d / need, kind)(): errs.append(f"layout: {where}: missing {need}")
    tests = d / "tests"
    if tests.exists():
        if not tests.is_dir(): errs.append(f"layout: {where}/tests must be a directory")
        else:
            for f in tests.rglob("*"):
                if f.is_file() and f.suffix not in {".json", ".md"}:
                    errs.append(f"layout: {where}/tests/{f.name}: only synthetic .json/.md expectations are allowed")
    rj = d / "release.json"
    if not rj.is_file(): return
    try: rel = json.loads(rj.read_text())
    except ValueError as e:
        errs.append(f"layout: {where}/release.json is not valid JSON: {e}"); return
    if rel.get("platform") != platform: errs.append(f"layout: {where}: release.json platform {rel.get('platform')!r} differs from directory {platform!r}")
    if rel.get("release_format") != 1: errs.append(f"layout: {where}: unsupported release_format {rel.get('release_format')!r}")
    if not COLLECTION.match(str(rel.get("release", ""))): errs.append(f"layout: {where}: release must look like v1.2.3")
    pkgs = rel.get("packages")
    if not isinstance(pkgs, list) or not pkgs:
        errs.append(f"layout: {where}: packages must be a non-empty list"); return
    allowed = set(); native = False
    for p in pkgs:
        pid = str(p.get("id", ""))
        n = f"{where}:{pid or '?'}"
        if not SLUG.match(pid): errs.append(f"layout: {n}: package id must be a lowercase slug")
        if not SEMVER.match(str(p.get("version", ""))): errs.append(f"layout: {n}: version {p.get('version')!r} is not SemVer (MAJOR.MINOR.PATCH)")
        if p.get("schema_version") not in SCHEMAS: errs.append(f"layout: {n}: unsupported schema_version {p.get('schema_version')!r}")
        if p.get("package_file") != f"{pid}.segapatch": errs.append(f"layout: {n}: package_file must be '{pid}.segapatch'")
        allowed |= {f"{pid}.bps", f"{pid}.manifest.json"}
        if p.get("schema_version") == 2:
            native = True
            if p.get("native_abi") not in NATIVE_ABIS: errs.append(f"layout: {n}: native_abi {p.get('native_abi')!r} is not a supported SDK ABI")
            if not p.get("capabilities"): errs.append(f"layout: {n}: native package must declare capabilities")
        elif p.get("native_abi") is not None: errs.append(f"layout: {n}: only schema 2 packages declare native_abi")
    if native: allowed.add("provider.c")
    src = d / "source"
    if src.is_dir():
        for f in sorted(src.iterdir()):
            if f.name not in allowed: errs.append(f"layout: {where}/source/{f.name}: not a declared package file (allowed: {', '.join(sorted(allowed))})")


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parent.parent))
    errs = []; lint(ap.parse_args(argv).root, errs)
    for e in errs: print("FAIL:", e, file=sys.stderr)
    print("ok" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
