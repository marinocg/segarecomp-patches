# Releases and publication review

Installable `.segapatch` archives are **GitHub Release assets**, not files in Git. A *collection release* (`v0.1.0`) groups independently installable packages; its version is unrelated to the versions of the packages inside it. Each package keeps its own `id` and `version`.

## release.json

Every game directory has a `release.json` (format 1) listing its packages with: id, version, revision, schema and native ABI, trust classification (`data-only` or `trusted-native-source`), package SHA-256 and size, package identity (SHA-256 of the manifest), exact source image digest, patched image digest, BPS and native source digests, license, source path, evidence tier, supported scope, limitations and the release asset URL. `catalog/index.json` is generated from these files by `scripts/build_catalog.py` and is the static input for a future documentation site. Hashes are never placeholders: they are computed from the actual archives.

`authoring_revision` is an opaque identifier of the private authoring revision that produced the package.

## Checks

* [Release notes v0.1.0](release-notes/v0.1.0.md).
* `python3 scripts/check_repo.py`: structure, metadata, link and forbidden-content checks, source digests, catalog freshness. Needs no commercial data.
* `python3 scripts/check_repo.py --assets <dir> [--segarecomp <binary>]`: compares the downloaded release assets with `release.json` and `SHA256SUMS`, and (with the shipped CLI) runs `segarecomp patch inspect` and compares the reported manifest facts.

Full reproduction of a package needs the commercial image and the private authoring inputs, so it runs privately; the outcome is recorded only as a maintainer attestation.

## Publication review (v0.1.0)

| Item | Status |
|---|---|
| Provider sources contain no ROM bytes or extracted assets | scanned; two comments refer to unpublished authoring notes |
| Sonic 1 provider license | the package declares none: **maintainer decision required** |
| BPS deltas (47-172 bytes each) are small but derived from commercial images | **maintainer legal clearance required** before the release is made public |
| Release assets verified with the shipped CLI against the exact local images | done (maintainer-attested) |

The release stays a **draft** until the maintainer approves publication.

## Excluded from v0.1.0

Experimental Sonic 1 gameplay package (extended object activation), the presentation-only variants, all native-only validation packages, the earlier `sonic1-widescreen` prototype and the retired Sonic 2 1.0.0/2.0.0 validation package.
