# Releases

Installable `.segapatch` archives are **GitHub Release assets**, not files in Git. A *collection release* (`v0.1.0`) groups independently installable packages; its version is unrelated to the versions of the packages inside it. Each package keeps its own `id` and `version`.

## release.json

Every game directory has a `release.json` (format 1) listing its packages with: id, version, revision, schema and native ABI, trust classification (`data-only` or `trusted-native-source`), package SHA-256 and size, package identity (SHA-256 of the manifest), exact source image digest, patched image digest, BPS and native source digests, license, source path, BPS path, evidence tier, supported scope, limitations and the release asset URL. `catalog/index.json` is generated from these files by `scripts/build_catalog.py` and is the static input of the documentation site's catalog pages. Its format, schemas, immutability and supersession rules are in [catalog-format.md](catalog-format.md); each release carries its `source_revision` (repository URL and exact commit) and `build` record. Hashes are never placeholders: they are computed from the actual archives.

`license_declared_in_package` is `false` when the package manifest has no license field and the license (MPL-2.0, the repository license) is established by this repository instead.

`authoring_revision` is an opaque identifier of the private authoring revision that produced the package.

## Checks

* [Release notes v0.1.0](release-notes/v0.1.0.md).
* `python3 scripts/check_repo.py`: structure, metadata, link and forbidden-content checks, source digests, catalog freshness. Needs no commercial data.
* `python3 scripts/build_packages.py --segapatch <segarecomp tools/segapatch.py> --out <dir>`: rebuilds every `.segapatch` from `source/` (manifest, BPS, provider) with the product's own deterministic writer and fails unless each equals the digest in `release.json`. It needs no game image.
* `python3 scripts/check_repo.py --assets <dir> [--segarecomp <binary>]`: compares the downloaded release assets with `release.json` and `SHA256SUMS`, and (with the shipped CLI) runs `segarecomp patch inspect` and compares the reported manifest facts.

Rebuilding a package from `source/` needs no game image. Regenerating the BPS from an original image needs the image and the private authoring inputs, so that step runs privately.

## Release lifecycle

A game's `release.json` holds **every** package version ever released for it. Top level `release` and `status` describe the current collection release: `prepared` (sources and metadata exist, nothing is public) or `published`. A package entry that carries its own `release`, `source_revision` and `build` is **archived**: it belongs to an older published release, and its sources are verified at its pinned commit in Git (a newer version of the same id may have replaced the working-tree files). `scripts/release_meta.py` is the one model of this; only `published` packages reach `catalog/index.json`, so the site never lists a download that does not exist.

1. **Prepare.** `python3 scripts/prepare_release.py begin --tag v0.2.0 --game patches/genesis/sonic-1` archives the game's current packages and starts the new release as `prepared`. Add the new package versions (sources, BPS, manifest, digests, asset URL under the new tag) and `docs/release-notes/v0.2.0.md`. A new version of an existing id must be strictly higher; a published `(id, version)` is never released again. Merge this in a pull request: CI validates the schema, rebuilds **every** release independently (`scripts/rebuild_release.py --all`: published releases from Git at their pinned commit, prepared ones from the working tree, each with the writer revision recorded for it) and checks provenance.
2. **Draft.** Run the **release** workflow from `main` with the tag. `scripts/release_guard.py` distinguishes a genuinely new release (allowed), an existing draft (refused: a maintainer deletes a draft deliberately), an already published release (refused: immutable), a published release whose GitHub release is missing or a draft (refused: inconsistent) and a tag with no prepared metadata (refused). It prints which published versions the new packages supersede. The workflow rebuilds the release, verifies it against its metadata and creates a **draft** with the assets and `SHA256SUMS`.
3. **Publish.** A maintainer publishes the draft on GitHub. This is the only publishing action. The `verify-release` and `pages` workflows then compare the published assets of that tag with the metadata.
4. **Record.** In a follow-up pull request run `python3 scripts/prepare_release.py publish --tag v0.2.0 --commit <SHA> [--tag-commit <SHA>]` (the commit the tag points at) and, for each replaced version, `prepare_release.py supersede --old id@1.0.0 --new id@1.1.0`, then `scripts/build_catalog.py`. The catalog now lists the release; the old entry only gained the additive `superseded_by` pointer and stays downloadable, unchanged, under its historical identity and URL.

Verification is always scoped to **one** release: `check_repo.py --assets DIR --release TAG` requires exactly that release's packages and `SHA256SUMS` and ignores the others, so a historical package is never skipped and never confused with a newer one. Without `--release` it only works while a single release exists.

## Immutability and provenance

A published release is never altered: the release workflow refuses a tag that is published, drafted or already catalogued, and CI rejects any change to a published catalog entry. Each package is tied to a reachable source commit and rebuilds from it to the same digest. Where artifacts live, and why R2 is not used, is recorded with measured numbers in [artifact-hosting.md](artifact-hosting.md); per-file publication review in [source-review.md](source-review.md); site deployment on GitHub Pages in [repository-settings.md](repository-settings.md).

## Excluded from v0.1.0

The presentation-only variants, all native-only validation packages, the earlier `sonic1-widescreen` prototype and the retired Sonic 2 1.0.0/2.0.0 validation package.
