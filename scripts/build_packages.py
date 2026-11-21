#!/usr/bin/env python3
"""Reconstruct the .segapatch files of ONE collection release from committed sources and fail unless each equals release.json.

  build_packages.py --segapatch <segarecomp tools/segapatch.py> --out DIR [--release TAG]
  build_packages.py --release TAG --print-writer-ref      the pinned segapatch.py revision a workflow must fetch for TAG

A package is manifest.json + game.bps (+ provider.c), written by the product's own `write_zip` (deterministic: fixed timestamps,
entry order, deflate level 9). Needs no game image. The packages of the selected release are rebuilt from the working tree when they
belong to the current release, or from Git at the pinned source commit when the release is archived, so an old release stays
independently verifiable after newer versions replaced its files. Also writes DIR/SHA256SUMS for that release only.
Without --release this is only unambiguous while a single release exists.
"""
import argparse, hashlib, importlib.util, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_meta

ROOT = pathlib.Path(__file__).resolve().parent.parent


def select(root, release):
    rels = release_meta.releases(root)
    if release is None:
        if len(rels) != 1: raise SystemExit(f"{len(rels)} releases are recorded ({', '.join(sorted(rels))}): pass --release TAG")
        release = next(iter(rels))
    if release not in rels: raise SystemExit(f"no packages are recorded for release {release}")
    return release, rels[release]["packages"]


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--segapatch"); ap.add_argument("--out"); ap.add_argument("--release")
    ap.add_argument("--print-writer-ref", action="store_true")
    ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--segarecomp"); ap.add_argument("--sdk-dir"); ap.add_argument("--cc"); a = ap.parse_args(argv)
    root = pathlib.Path(a.root); tag, pkgs = select(root, a.release)
    if a.print_writer_ref:
        refs = {pk.build.get("writer_ref") for pk in pkgs}
        if len(refs) != 1 or None in refs: raise SystemExit(f"release {tag}: packages must share exactly one build.writer_ref, found {sorted(map(str, refs))}")
        print(refs.pop()); return 0
    if not (a.segapatch and a.out): ap.error("--segapatch and --out are required")
    spec = importlib.util.spec_from_file_location("segapatch", a.segapatch); sp = importlib.util.module_from_spec(spec); spec.loader.exec_module(sp)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    sums, bad = [], 0
    for pk in pkgs:
        p = pk.p
        files = [("manifest.json", pk.read(f"source/{p['id']}.manifest.json")), ("game.bps", pk.read(p["bps"]["path"]))]
        if p.get("source"): files.append(("provider.c", pk.read(p["source"]["path"])))
        target = out / p["package_file"]; sp.write_zip(target, files)
        h = hashlib.sha256(target.read_bytes()).hexdigest()
        ok = h == p["package_sha256"] and target.stat().st_size == p["package_size"]
        print(("ok   " if ok else "FAIL ") + f"{tag} {p['package_file']}", h)
        bad += not ok; sums.append(f"{h}  {p['package_file']}")
    if a.segarecomp:   # unpublished schema 3 projects: rebuilt by the product's own `mod pack` into out/unpublished/ (never SHA256SUMS, never a release asset)
        import check_repo, lint_layout
        extra = [x for k, v in (("--cc", a.cc), ("--sdk-dir", a.sdk_dir)) if v for x in (k, v)]
        for d in lint_layout.mod_projects(root):
            target = out / "unpublished" / f"{d.name}.segapatch"; target.parent.mkdir(parents=True, exist_ok=True)
            ok, info, data = check_repo.pack_mod_project(a.segarecomp, d, target, extra)
            print(("ok   " if ok else "FAIL ") + f"unpublished/{target.name}", info.get("package_identity", ""))
            bad += not ok
    (out / "SHA256SUMS").write_text("\n".join(sorted(sums, key=lambda l: l.split("  ")[1])) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
