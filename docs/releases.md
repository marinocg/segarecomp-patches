# Releases

Installable `.segapatch` archives are **GitHub Release assets**, not files in Git. A *collection release* (`v0.1.0`) groups independently installable packages; its version is unrelated to the versions of the packages inside it. Each package keeps its own `id` and `version`.

## release.json

Every game directory has a `release.json` (format 1) listing its packages with: id, version, revision, schema and native ABI, trust classification (`data-only` or `trusted-native-source`), package SHA-256 and size, package identity (SHA-256 of the manifest), exact source image digest, patched image digest, BPS and native source digests, license, source path, BPS path, evidence tier, supported scope, limitations and the release asset URL. `catalog/index.json` is generated from these files by `scripts/build_catalog.py` and is the static input for a future documentation site. Hashes are never placeholders: they are computed from the actual archives.

`license_declared_in_package` is `false` when the package manifest has no license field and the license (MPL-2.0, the repository license) is established by this repository instead.

`authoring_revision` is an opaque identifier of the private authoring revision that produced the package.

## Checks

* [Release notes v0.1.0](release-notes/v0.1.0.md).
* `python3 scripts/check_repo.py`: structure, metadata, link and forbidden-content checks, source digests, catalog freshness. Needs no commercial data.
* `python3 scripts/build_packages.py --segapatch <segarecomp tools/segapatch.py> --out <dir>`: rebuilds every `.segapatch` from `source/` (manifest, BPS, provider) with the product's own deterministic writer and fails unless each equals the digest in `release.json`. It needs no game image.
* `python3 scripts/check_repo.py --assets <dir> [--segarecomp <binary>]`: compares the downloaded release assets with `release.json` and `SHA256SUMS`, and (with the shipped CLI) runs `segarecomp patch inspect` and compares the reported manifest facts.

Rebuilding a package from `source/` needs no game image. Regenerating the BPS from an original image needs the image and the private authoring inputs, so that step runs privately.

## Creating the draft release

Run the **release** workflow (Actions, *Run workflow*, tag such as `v0.1.0`). It rebuilds the packages from source, checks them against `release.json` (hashes, sizes and a mandatory `SHA256SUMS`), and creates a **draft** GitHub Release with the rebuilt packages, `SHA256SUMS` and `docs/release-notes/<tag>.md`. Nothing is published automatically. The product's `segapatch.py` writer is fetched at the commit in `scripts/SEGAPATCH_REF`. Pull-request CI performs the same rebuild and verification, so what the release workflow does is already exercised before merge. `dry_run` runs everything except the release creation. Delete any manually created draft of the same tag before running it.

## Excluded from v0.1.0

The presentation-only variants, all native-only validation packages, the earlier `sonic1-widescreen` prototype and the retired Sonic 2 1.0.0/2.0.0 validation package.
