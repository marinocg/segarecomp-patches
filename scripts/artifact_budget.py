#!/usr/bin/env python3
"""Numbers behind the artifact-hosting decision (docs/artifact-hosting.md): is R2 (or any extra store) justified yet?

  artifact_budget.py [--root DIR]

Reads catalog/index.json and compares the measured package sizes with the thresholds below. Exits non-zero when a threshold is crossed, so
the day a package outgrows the chosen store the CI check forces the decision to be revisited instead of failing silently in production.
"""
import argparse, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIB = 1024 * 1024
# Vendor limits as documented when the decision was recorded (re-verify before relying on them): GitHub Pages sites are limited to 1 GB
# (published) and soft 100 GB/month bandwidth; Cloudflare R2 would be the alternative store; GitHub Release assets 2 GiB each. Thresholds are deliberately well below those limits.
LIMITS = {"largest_package_bytes": 20 * MIB, "all_packages_bytes": 500 * MIB, "site_static_files": 15000}


def measure(root):
    cat = json.loads((pathlib.Path(root) / "catalog" / "index.json").read_text()); sizes = [p["package_size"] for p in cat["packages"]]
    return {"packages": len(sizes), "largest_package_bytes": max(sizes, default=0), "all_packages_bytes": sum(sizes)}


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--site-files", type=int, default=0, help="file count of a built site/dist")
    a = ap.parse_args(argv); m = measure(a.root); m["site_static_files"] = a.site_files
    bad = [k for k, v in LIMITS.items() if m[k] > v]
    print(json.dumps({"measured": m, "thresholds": LIMITS, "r2_justified": bool(bad), "exceeded": bad}, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
