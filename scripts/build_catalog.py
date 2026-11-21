#!/usr/bin/env python3
"""Generate catalog/index.json from patches/*/*/release.json (deterministic). `--check` fails if it is stale.

The catalog is catalog_format 1 (catalog/schema/catalog-1.schema.json, docs/catalog-format.md): additive over the first release,
so every field that already existed keeps its name and meaning. Validation lives in scripts/validate_catalog.py.
"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REQUIRED = ("id", "version", "name", "revision", "region", "schema_version", "trust", "executable_code", "package_sha256", "package_size",
            "package_identity", "source_image_sha256", "patched_image_sha256", "bps_sha256", "evidence_tier", "gameplay", "license",
            "supported_scope", "limitations", "asset")
OPTIONAL = ("native_abi", "capabilities", "native_source_sha256", "license_declared_in_package", "default_widescreen", "default_side_style",
            "widescreen_width_max", "superseded_by")


def build(root=ROOT):
    entries = []
    for rj in sorted((root / "patches").glob("*/*/release.json")):
        rel = json.loads(rj.read_text())
        for p in rel["packages"]:
            e = {"platform": rel["platform"], "game": rel["game"], "game_path": rj.parent.relative_to(root).as_posix(),
                 "source_identity_kind": rel["source_identity_kind"], "bios_requirement": rel["bios_requirement"], "release": rel["release"],
                 "source_revision": rel["source_revision"], "build": rel["build"]}
            e.update({k: p[k] for k in REQUIRED})
            e.update({k: p[k] for k in OPTIONAL if k in p})
            entries.append(e)
    return json.dumps({"catalog_format": 1, "packages": entries}, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    out = ROOT / "catalog" / "index.json"
    text = build()
    if "--check" in sys.argv:
        sys.exit(0 if out.exists() and out.read_text() == text else "catalog/index.json is stale: run scripts/build_catalog.py")
    out.write_text(text)
