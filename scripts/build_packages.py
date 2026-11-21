#!/usr/bin/env python3
"""Build and verify the packages of ONE collection release, and only those: the packages its releases/<tag>.json lists, nothing else.

  build_packages.py --release TAG --out DIR --segapatch <segarecomp tools/segapatch.py> [--segarecomp BIN [--cc CC --sdk-dir DIR] --segarecomp-ref SHA]
  build_packages.py --release TAG --print-writer-ref      the pinned segapatch.py revision a workflow must fetch for the schema 1/2 packages of TAG
  build_packages.py --release TAG --print-product-ref     the pinned product revision a workflow must build `segarecomp` at for the schema 3 packages of TAG

Every selected package is built by the product's own tool and compared with its recorded digest, size and identity; a mismatch fails the run:

* schema 1/2: `tools/segapatch.py write_zip` (manifest.json + game.bps + provider.c; deterministic: fixed timestamps, entry order, deflate level 9);
* schema 3:   `segarecomp mod pack` (`mod build` when a compiler and SDK are given: the same bytes, plus the host-compiled native units as a gate).
              `pack` is the distributable archive, `build` adds the compile check; they are not interchangeable commands, only equal in output.

Nothing here reads a game image. A package of a published release is rebuilt from Git at its pinned source commit (in the layout that commit had); a
prepared one from the working tree. Also writes DIR/SHA256SUMS for that release only. No other release and no unlisted (internal, candidate or
unselected) patch is ever built.
"""
import argparse, hashlib, importlib.util, pathlib, subprocess, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_meta

ROOT = pathlib.Path(__file__).resolve().parent.parent


def select(root, release):
    rels = release_meta.releases(root)
    if release is None:
        if len(rels) != 1: raise SystemExit(f"{len(rels)} releases are recorded ({', '.join(sorted(rels))}): pass --release TAG")
        release = next(iter(rels))
    if release not in rels: raise SystemExit(f"no release {release} is recorded (releases/{release}.json)")
    if len(rels[release]["packages"]) != len(rels[release]["doc"].get("packages", [])):
        raise SystemExit(f"release {release} lists a package that no package.json defines: run scripts/validate_catalog.py")
    return release, rels[release]["packages"]


def only_ref(pkgs, mod):
    """The one build.writer_ref shared by the packages of one kind in a release (None when it has none of that kind)."""
    refs = {pk.build.get("writer_ref") for pk in pkgs if pk.is_mod == mod}
    if not refs: return None
    if len(refs) != 1 or None in refs: raise SystemExit(f"packages of one kind must share exactly one build.writer_ref, found {sorted(map(str, refs))}")
    return refs.pop()


def _project_dir(root, pk, tmp):
    """The directory `segarecomp mod ...` runs on: the working tree for a prepared package, a clean checkout of the pinned commit for a published one."""
    if pk.status != "published": return pk.dir
    commit = pk.source_revision.get("commit")
    arc = subprocess.run(["git", "archive", f"{commit}:{pk.source_base}"], cwd=root, capture_output=True)
    if arc.returncode != 0: raise SystemExit(f"{pk.ref}: {pk.source_base} cannot be resolved at {commit}")
    out = pathlib.Path(tmp) / pk.id; out.mkdir(parents=True)
    subprocess.run(["tar", "-x", "-C", str(out)], input=arc.stdout, check=True)
    return out


def build_one(root, pk, out, sp=None, cli=None, extra=()):
    """Build one package into `out`; returns (ok, sha256)."""
    p = pk.p; target = pathlib.Path(out) / pk.package_file
    if pk.is_mod:
        import check_repo
        with tempfile.TemporaryDirectory() as t:
            ok, info, _ = check_repo.pack_mod_project(cli, _project_dir(root, pk, t), target, extra)
        ok = ok and info.get("package_identity") == p["package_identity"]
    else:
        files = [("manifest.json", pk.read(f"source/{p['id']}.manifest.json")), ("game.bps", pk.read(p["bps"]["path"]))]
        if p.get("source"): files.append(("provider.c", pk.read(p["source"]["path"])))
        sp.write_zip(target, files); ok = True
    h = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else ""
    return ok and h == p["package_sha256"] and target.stat().st_size == p["package_size"], h


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--segapatch"); ap.add_argument("--out"); ap.add_argument("--release")
    ap.add_argument("--print-writer-ref", action="store_true"); ap.add_argument("--print-product-ref", action="store_true")
    ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--segarecomp"); ap.add_argument("--segarecomp-ref"); ap.add_argument("--sdk-dir"); ap.add_argument("--cc")
    a = ap.parse_args(argv)
    root = pathlib.Path(a.root); tag, pkgs = select(root, a.release)
    if a.print_writer_ref or a.print_product_ref:
        ref = only_ref(pkgs, mod=a.print_product_ref)
        if ref is None: raise SystemExit(f"release {tag} has no {'schema 3' if a.print_product_ref else 'schema 1/2'} package")
        print(ref); return 0
    if not a.out: ap.error("--out is required")
    legacy, mods = [pk for pk in pkgs if not pk.is_mod], [pk for pk in pkgs if pk.is_mod]
    if legacy and not a.segapatch: ap.error("--segapatch is required for the schema 1/2 packages of this release")
    if mods and not a.segarecomp: ap.error("--segarecomp is required for the schema 3 packages of this release")
    if mods and a.segarecomp_ref != only_ref(pkgs, mod=True):
        raise SystemExit(f"release {tag}: its schema 3 packages were built with product revision {only_ref(pkgs, mod=True)}, but --segarecomp-ref is {a.segarecomp_ref}: build the product at the pinned revision")
    sp = None
    if legacy:
        spec = importlib.util.spec_from_file_location("segapatch", a.segapatch); sp = importlib.util.module_from_spec(spec); spec.loader.exec_module(sp)
    extra = [x for k, v in (("--cc", a.cc), ("--sdk-dir", a.sdk_dir)) if v for x in (k, v)]
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    sums, bad = [], 0
    for pk in pkgs:
        ok, h = build_one(root, pk, out, sp, a.segarecomp, extra)
        print(("ok   " if ok else "FAIL ") + f"{tag} {pk.package_file}", h)
        bad += not ok; sums.append(f"{h}  {pk.package_file}")
    (out / "SHA256SUMS").write_text("\n".join(sorted(sums, key=lambda l: l.split("  ")[1])) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
