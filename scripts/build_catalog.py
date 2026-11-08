#!/usr/bin/env python3
"""Generate catalog/index.json from patches/*/*/release.json (deterministic). `--check` fails if it is stale."""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def build(root=ROOT):
    entries = []
    for rj in sorted((root / "patches").glob("*/*/release.json")):
        rel = json.loads(rj.read_text())
        for p in rel["packages"]:
            entries.append({
                "platform": rel["platform"], "game": rel["game"], "game_path": rj.parent.relative_to(root).as_posix(),
                "source_identity_kind": rel["source_identity_kind"], "bios_requirement": rel["bios_requirement"],
                "release": rel["release"], **{k: p[k] for k in (
                    "id", "version", "revision", "schema_version", "native_abi", "trust", "package_sha256", "package_size",
                    "package_identity", "source_image_sha256", "evidence_tier", "gameplay", "license", "asset")}})
    return json.dumps({"catalog_format": 1, "packages": entries}, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    out = ROOT / "catalog" / "index.json"
    text = build()
    if "--check" in sys.argv:
        sys.exit(0 if out.exists() and out.read_text() == text else "catalog/index.json is stale: run scripts/build_catalog.py")
    out.write_text(text)
