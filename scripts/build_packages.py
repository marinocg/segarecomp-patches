#!/usr/bin/env python3
"""Reconstruct every .segapatch from the committed sources and fail unless it equals release.json.

  build_packages.py --segapatch <segarecomp tools/segapatch.py> --out DIR

A package is manifest.json + game.bps (+ provider.c), written by the product's own `write_zip` (deterministic: fixed timestamps,
entry order, deflate level 9). Needs no game image. Also writes DIR/SHA256SUMS.
"""
import argparse, hashlib, importlib.util, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--segapatch", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--root", default=str(ROOT)); a = ap.parse_args(argv)
    spec = importlib.util.spec_from_file_location("segapatch", a.segapatch); sp = importlib.util.module_from_spec(spec); spec.loader.exec_module(sp)
    root, out = pathlib.Path(a.root), pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    sums, bad = [], 0
    for rj in sorted((root / "patches").glob("*/*/release.json")):
        d = rj.parent
        for p in json.loads(rj.read_text())["packages"]:
            files = [("manifest.json", (d / "source" / f"{p['id']}.manifest.json").read_bytes()), ("game.bps", (d / p["bps"]["path"]).read_bytes())]
            if p.get("source"): files.append(("provider.c", (d / p["source"]["path"]).read_bytes()))
            target = out / p["package_file"]; sp.write_zip(target, files)
            h = hashlib.sha256(target.read_bytes()).hexdigest()
            ok = h == p["package_sha256"] and target.stat().st_size == p["package_size"]
            print(("ok   " if ok else "FAIL ") + p["package_file"], h)
            bad += not ok; sums.append(f"{h}  {p['package_file']}")
    (out / "SHA256SUMS").write_text("\n".join(sorted(sums, key=lambda l: l.split("  ")[1])) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
