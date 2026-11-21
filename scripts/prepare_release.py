#!/usr/bin/env python3
"""Move patches and releases through their lifecycle (docs/releases.md). Edits only `patches/*/*/*/package.json`, `releases/*.json` and a release-notes stub.

  prepare_release.py pin PATCH_DIR --segarecomp BIN [--cc CC --sdk-dir DIR] --game NAME --gameplay TEXT --scope TEXT [--limitation TEXT ...] [--evidence-tier T]
      Record a schema 3 patch's package version in its package.json: the digest, size and identity come from the product's `segarecomp mod pack`
      (or `mod build` when --cc/--sdk-dir are given), everything else from mod.toml. Re-running it for an unchanged version verifies; a changed one is refused
      (a published or pinned version is never rewritten: bump the version in mod.toml).
  prepare_release.py begin   --tag v0.2.0 --package id@1.0.0 [--package ...]
      Start a release as `prepared` with this EXPLICIT allowlist (releases/v0.2.0.json). Only eligible patches can be selected; unknown, duplicate, internal,
      candidate and already released versions fail. Nothing else is touched: no other release, no other patch.
  prepare_release.py publish --tag v0.2.0 --commit SHA [--tag-commit SHA]
      After a maintainer published the draft: records the release as `published` with its exact source commit. The catalog then lists it.
  prepare_release.py supersede --old id@1.0.0 --new id@1.1.0
      Additive supersession pointer on a published package. Nothing else of the old entry is touched.
"""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_meta

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = "https://github.com/marinocg/segarecomp-patches"
LEGACY_WRITER = "segapatch.py write_zip"
MOD_WRITER = "segarecomp mod pack"
KINDS = {"cartridge-image": "cartridge-image-sha256"}   # the product's source kind -> this repository's catalog vocabulary; anything else is refused


def dump(path, doc):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def _ref(root, name): return (root / "scripts" / name).read_text().strip() if (root / "scripts" / name).is_file() else ""


def begin(root, tag, refs):
    path = root / "releases" / f"{tag}.json"
    if not release_meta.TAG.match(tag): raise SystemExit(f"tag {tag!r} must look like v1.2.3")
    if path.exists(): raise SystemExit(f"release {tag} already exists (releases/{tag}.json): a release is created exactly once")
    refs = list(refs)
    if len(set(refs)) != len(refs): raise SystemExit(f"duplicate package selection: {sorted({r for r in refs if refs.count(r) > 1})}")
    by_ref = {pk.ref: pk for pk in release_meta.packages(root)}
    for r in refs:
        if r not in by_ref: raise SystemExit(f"unknown package {r}: no package.json records it (a schema 3 patch is recorded with `prepare_release.py pin`)")
    doc = {"release_format": 2, "release": tag, "status": "prepared", "source_layout": "patch-dir", "source_revision": {"repository": REPO}}
    if any(not by_ref[r].is_mod for r in refs):
        doc["build"] = {"writer": LEGACY_WRITER, "writer_ref": _ref(root, "SEGAPATCH_REF"), "deterministic": True}
    doc["packages"] = sorted(refs)
    dump(path, doc)
    errs = release_meta.consistency_errors(root)
    if errs:
        path.unlink()
        raise SystemExit("release not created:\n  " + "\n  ".join(errs))
    notes = root / "docs" / "release-notes" / f"{tag}.md"
    if not notes.exists():
        lines = [f"# segarecomp Patches {tag}", "", "Packages in this release:", ""] + [f"* `{r}`: {by_ref[r].p['name']}" for r in sorted(refs)] + ["", "Edit this file before running the release workflow."]
        notes.write_text("\n".join(lines) + "\n")


def publish(root, tag, commit, tag_commit=None):
    path = root / "releases" / f"{tag}.json"
    if not path.is_file(): raise SystemExit(f"no prepared release {tag}")
    doc = json.loads(path.read_text())
    if doc.get("status") != "prepared": raise SystemExit(f"release {tag} is {doc.get('status')}, not prepared")
    sr = {"repository": doc["source_revision"]["repository"], "commit": commit, "tag": tag}
    if tag_commit: sr["tag_commit"] = tag_commit
    doc["status"], doc["source_revision"] = "published", sr; dump(path, doc)


def supersede(root, old, new):
    (oid, _, over), (nid, _, nver) = old.partition("@"), new.partition("@")
    for pt in release_meta.patches(root):
        meta = pt.meta
        for p in (meta or {}).get("packages", []):
            if (p["id"], p["version"]) == (oid, over):
                if p.get("superseded_by") not in (None, new): raise SystemExit(f"{old} is already superseded by {p['superseded_by']}")
                p["superseded_by"] = new; dump(pt.dir / "package.json", meta); return
    raise SystemExit(f"{old} not found")


def pin(root, patch_dir, cli, extra, game, gameplay, scope, limitations, tier):
    import tempfile, check_repo
    pt = release_meta.Patch(root, (root / patch_dir).resolve())
    if not pt.is_mod: raise SystemExit(f"{patch_dir}: only a schema 3 project (mod.toml) is pinned this way; schema 1/2 packages are recorded by hand with their BPS")
    mod = pt.mod; m = mod["mod"]
    rc, chk = check_repo._cli(cli, "mod", "check", pt.dir, *extra)
    if rc != 0 or chk.get("ok") is not True: raise SystemExit(f"segarecomp mod check refused {patch_dir}: {chk.get('error', chk)}")
    if chk.get("trust_class") != "native": raise SystemExit(f"{patch_dir}: trust class {chk.get('trust_class')!r}; only native (trusted source) schema 3 packages are published today")
    if chk.get("source_identity_kind") not in KINDS: raise SystemExit(f"{patch_dir}: unsupported source identity kind {chk.get('source_identity_kind')!r}")
    with tempfile.TemporaryDirectory() as t:
        ok, info, data = check_repo.pack_mod_project(cli, pt.dir, pathlib.Path(t) / "p.segapatch", extra)
        ok2, info2, data2 = check_repo.pack_mod_project(cli, pt.dir, pathlib.Path(t) / "q.segapatch", extra)
    if not (ok and ok2) or data != data2: raise SystemExit(f"{patch_dir}: the product build failed or is not deterministic: {info.get('error', '')}")
    import hashlib
    entry = {"id": m["id"], "version": m["version"], "name": m["name"], "schema_version": 3, "native_abi": mod["abi"]["native"],
             "capabilities": mod["capabilities"]["required"], "trust": "trusted-native-source", "executable_code": True,
             "package_sha256": hashlib.sha256(data).hexdigest(), "package_size": len(data), "package_identity": info["package_identity"],
             "images": [{"label": r["label"], "sha256": r["sha256"]} for r in mod["target"]["revision"]], "license": m["license"],
             "author": m.get("author"), "evidence_tier": tier, "gameplay": gameplay, "supported_scope": scope, "limitations": limitations,
             "build": {"writer": MOD_WRITER, "writer_ref": _ref(root, "PRODUCT_REF"), "deterministic": True}}
    entry = {k: v for k, v in entry.items() if v is not None}
    meta = pt.meta or {"package_format": 1, "platform": pt.platform, "source_identity_kind": KINDS[chk["source_identity_kind"]], "bios_requirement": "none", "game": game, "packages": []}
    if not meta["packages"] and not game: raise SystemExit("--game NAME is required the first time a patch is recorded")
    for p in meta["packages"]:
        if p["version"] == entry["version"]:
            if p != entry: raise SystemExit(f"{entry['id']}@{entry['version']} is already recorded with different facts: a recorded version is never rewritten, bump `version` in mod.toml")
            print(f"ok: {entry['id']}@{entry['version']} already recorded and unchanged"); return
    meta["packages"] = sorted(meta["packages"] + [entry], key=lambda p: release_meta.semver(p["version"]))
    dump(pt.dir / "package.json", meta)
    pinfile = pt.dir / "tests" / "package.json"
    if pinfile.is_file(): dump(pinfile, {"package_identity": entry["package_identity"], "package_sha256": entry["package_sha256"]})
    print(f"recorded {entry['id']}@{entry['version']} in {pt.path}/package.json ({entry['package_sha256'][:12]}, {entry['package_size']} bytes)")


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(ROOT)); sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("begin"); b.add_argument("--tag", required=True); b.add_argument("--package", action="append", required=True)
    p = sub.add_parser("publish"); p.add_argument("--tag", required=True); p.add_argument("--commit", required=True); p.add_argument("--tag-commit")
    s = sub.add_parser("supersede"); s.add_argument("--old", required=True); s.add_argument("--new", required=True)
    n = sub.add_parser("pin"); n.add_argument("patch_dir"); n.add_argument("--segarecomp", required=True); n.add_argument("--cc"); n.add_argument("--sdk-dir")
    n.add_argument("--game", default=""); n.add_argument("--gameplay", required=True); n.add_argument("--scope", required=True)
    n.add_argument("--limitation", action="append", default=[]); n.add_argument("--evidence-tier", default="synthetic-only", choices=["synthetic-only", "maintainer-attested", "automated"])
    a = ap.parse_args(argv); root = pathlib.Path(a.root)
    if a.cmd == "begin": begin(root, a.tag, a.package)
    elif a.cmd == "publish": publish(root, a.tag, a.commit, a.tag_commit)
    elif a.cmd == "supersede": supersede(root, a.old, a.new)
    else: pin(root, a.patch_dir, a.segarecomp, [x for k, v in (("--cc", a.cc), ("--sdk-dir", a.sdk_dir)) if v for x in (k, v)], a.game, a.gameplay, a.scope, a.limitation, a.evidence_tier)
    return 0


if __name__ == "__main__":
    sys.exit(main())
