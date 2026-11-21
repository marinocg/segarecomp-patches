#!/usr/bin/env python3
"""Move release metadata through its lifecycle (docs/releases.md). Edits only `patches/*/*/release.json`.

  prepare_release.py begin   --tag v0.2.0 --game patches/genesis/sonic-1 [--game ...]
      Archives the game's current packages (pins release, source_revision and build on each, so the old release stays verifiable from Git),
      then starts the new release as `prepared`. Add or edit the new package versions (sources, BPS, manifest, digests) afterwards.
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


def dump(path, doc): path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def begin(root, tag, game_dirs):
    ref = (root / "scripts" / "SEGAPATCH_REF").read_text().strip() if (root / "scripts" / "SEGAPATCH_REF").is_file() else ""
    if any(tag == pk.release for pk in release_meta.packages(root)): raise SystemExit(f"release {tag} already has packages")
    for g in game_dirs:
        rj = root / g / "release.json"; doc = json.loads(rj.read_text())
        if doc.get("status") != "published": raise SystemExit(f"{g}: current release {doc.get('release')} is not published; finish it first")
        pin_rev, pin_build, old = doc["source_revision"], doc["build"], doc["release"]
        for p in doc["packages"]:
            if "release" in p: continue
            p["release"], p["status"], p["source_revision"], p["build"] = old, "published", dict(pin_rev), dict(pin_build)
        doc["release"], doc["status"] = tag, "prepared"
        doc["source_revision"] = {"repository": pin_rev["repository"]}
        doc["build"] = {**pin_build, "writer_ref": ref or pin_build["writer_ref"]}
        # keep the key order stable: release, status first
        order = ["release_format", "platform", "source_identity_kind", "bios_requirement", "game", "release", "status", "source_revision", "build", "packages"]
        dump(rj, {**{k: doc[k] for k in order if k in doc}, **{k: v for k, v in doc.items() if k not in order}})


def publish(root, tag, commit, tag_commit=None):
    done = 0
    for rj, doc in release_meta.games(root):
        if doc.get("release") == tag and doc.get("status") == "prepared":
            sr = {"repository": doc["source_revision"]["repository"], "commit": commit, "tag": tag}
            if tag_commit: sr["tag_commit"] = tag_commit
            doc["status"], doc["source_revision"] = "published", sr; dump(rj, doc); done += 1
    if not done: raise SystemExit(f"no prepared release {tag}")


def supersede(root, old, new):
    (oid, _, over), (nid, _, nver) = old.partition("@"), new.partition("@")
    for rj, doc in release_meta.games(root):
        for p in doc["packages"]:
            if (p["id"], p["version"]) == (oid, over):
                if p.get("superseded_by") not in (None, new): raise SystemExit(f"{old} is already superseded by {p['superseded_by']}")
                p["superseded_by"] = new; dump(rj, doc); return
    raise SystemExit(f"{old} not found")


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(ROOT)); sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("begin"); b.add_argument("--tag", required=True); b.add_argument("--game", action="append", required=True)
    p = sub.add_parser("publish"); p.add_argument("--tag", required=True); p.add_argument("--commit", required=True); p.add_argument("--tag-commit")
    s = sub.add_parser("supersede"); s.add_argument("--old", required=True); s.add_argument("--new", required=True)
    a = ap.parse_args(argv); root = pathlib.Path(a.root)
    if a.cmd == "begin": begin(root, a.tag, a.game)
    elif a.cmd == "publish": publish(root, a.tag, a.commit, a.tag_commit)
    else: supersede(root, a.old, a.new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
