"""Generate catalog/index.json from the published releases (releases/*.json) and the package facts of the patches they list. `--check` fails if it is stale.

The catalog is catalog_format 2 (catalog/schema/catalog-2.schema.json, docs/catalog-format.md): catalog_format 1 plus schema 3 mod entries. Every entry
published as format 1 keeps its exact fields and values. Validation lives in scripts/validate_catalog.py.
"""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_meta

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG_FORMAT = 2
REQUIRED = ("id", "version", "name", "revision", "region", "schema_version", "trust", "executable_code", "package_sha256", "package_size",
            "package_identity", "source_image_sha256", "patched_image_sha256", "bps_sha256", "evidence_tier", "gameplay", "license",
            "supported_scope", "limitations", "asset")
OPTIONAL = ("native_abi", "capabilities", "native_source_sha256", "license_declared_in_package", "default_widescreen", "default_side_style",
            "widescreen_width_max", "superseded_by")
# A schema 3 mod is not a BPS/ROM transformation: it lists the images it targets and carries no BPS, patched-image or single source-image digest.
MOD_REQUIRED = ("id", "version", "name", "schema_version", "native_abi", "capabilities", "trust", "executable_code", "package_sha256", "package_size",
                "package_identity", "images", "evidence_tier", "gameplay", "license", "supported_scope", "limitations")
MOD_OPTIONAL = ("superseded_by",)


def build(root=ROOT):
    """Only PUBLISHED packages are listed: a prepared release has no download yet and must never be advertised."""
    entries = []
    for pk in sorted(release_meta.published(root), key=release_meta.sort_key):
        pt, p, meta = pk.patch, pk.p, pk.patch.meta
        e = {"platform": meta["platform"], "game": meta["game"], "game_path": pt.game_path}
        if pk.layout != "game-dir": e["source_path"] = pt.path   # older releases kept their sources directly under game_path (see docs/catalog-format.md)
        e.update({"source_identity_kind": meta["source_identity_kind"], "bios_requirement": meta["bios_requirement"], "release": pk.release,
                  "source_revision": pk.source_revision, "build": pk.build})
        if pk.is_mod:
            e.update({k: p[k] for k in MOD_REQUIRED}); e["asset"] = pk.asset
            e.update({k: p[k] for k in MOD_OPTIONAL if k in p})
        else:
            e.update({k: p[k] for k in REQUIRED})
            e.update({k: p[k] for k in OPTIONAL if k in p})
        entries.append(e)
    return json.dumps({"catalog_format": CATALOG_FORMAT, "packages": entries}, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    args = sys.argv[1:]
    root = pathlib.Path(args[args.index("--root") + 1]) if "--root" in args else ROOT
    out, text = root / "catalog" / "index.json", build(root)
    if "--check" in args:
        sys.exit(0 if out.exists() and out.read_text() == text else "catalog/index.json is stale: run scripts/build_catalog.py")
    out.write_text(text)
