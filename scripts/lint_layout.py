#!/usr/bin/env python3
"""Layout and versioning lint for patch projects (docs/layout-and-versioning.md).

  lint_layout.py [--root DIR]

Checks the structure of every `patches/<platform>/<game>/` directory and the versioning fields of its `release.json`.
Digest, license, catalog and forbidden-content checks stay in check_repo.py, which calls `lint()` so a pull request cannot skip it.
"""
import argparse, json, pathlib, re, sys

PLATFORMS = {"genesis", "master-system", "game-gear", "sega-cd"}
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
COLLECTION = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SCHEMAS = {1, 2}          # .segapatch schemas this repository publishes; 3 (mod.toml) is reserved, not accepted
NATIVE_ABIS = {1}
PROJECT_ENTRIES = {"README.md", "release.json", "source", "tests"}


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


def _project(d, platform, where, errs):
    if not SLUG.match(d.name): errs.append(f"layout: {where}: directory name must be a lowercase slug")
    for e in sorted(d.iterdir()):
        if e.name == "mod.toml":
            errs.append(f"layout: {where}/mod.toml is reserved for schema 3 and is not accepted yet")
        elif e.name not in PROJECT_ENTRIES:
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
