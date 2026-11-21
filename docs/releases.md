# Releases

Installable `.segapatch` archives are **GitHub Release assets**, not files in Git. A *collection release* (`v0.1.0`) groups independently installable packages; its version is unrelated to the versions of the packages inside it. Each package keeps its own `id` and `version`.

Adding one patch is a small, bounded operation: **a release contains exactly the package versions it lists, builds only those, and never touches an earlier release.**

## The three records

| Record | Answers | Authority for |
|---|---|---|
| `patches/<platform>/<game>/<patch>/` with `package.json` | what is this package version? | the facts of each package version: digests, size, identity, scope, limitations, evidence tier (schema 1/2: also BPS and source digests; schema 3: derived from `mod.toml` and the product tool) |
| [`publication.json`](../publication.json) | may this patch ever be released? | `internal` (never selectable; the default for anything not listed), `candidate` (developed and tested, not approved), `eligible` (approved for release selection; records its review) |
| `releases/<tag>.json` | what is in this release, and where is it in its lifecycle? | the **explicit, sorted allowlist** of exact `id@version` entries, `status` (`prepared` or `published`), `source_revision`, and the `source_layout` its sources had |

There is no other list of package contents. `catalog/index.json` is generated from these records and is never edited by hand. Eligibility alone never releases anything, and neither does a built archive, a `README.md` or a `mod.toml`: a package ships only when a release record names it.

## Everyday workflow

Worked example: preparing Castle of Illusion widescreen + Practice+ (`castle-of-illusion-widescreen-practice@0.1.0`) as `v0.2.0`. Its sibling projects `debug-fly` and `input-recorder` stay internal and can never be selected.

1. **Develop and test** in `patches/genesis/castle-of-illusion/widescreen-practice/`. `segarecomp mod check <dir>` validates the project; `segarecomp mod build <dir> --out x.segapatch --cc cc --sdk-dir <product>/platforms` additionally compiles the native code with the host-owned flags. `python3 scripts/check_repo.py --segarecomp "$CLI" --cc cc --sdk-dir "$SDK" --changed-from origin/main` does that for the projects you changed.
2. **Record the package version** (schema 3):
   ```text
   python3 scripts/prepare_release.py pin patches/genesis/castle-of-illusion/widescreen-practice \
     --segarecomp "$CLI" --cc cc --sdk-dir "$SDK" --game "Castle of Illusion Starring Mickey Mouse" \
     --gameplay "..." --scope "..." --limitation "..." [--evidence-tier maintainer-attested]
   ```
   The digest, size and identity come from the product's own `segarecomp mod pack` at the revision in `scripts/PRODUCT_REF`; the rest from `mod.toml`. A recorded version is never rewritten: change a source byte and the command refuses until `version` is bumped in `mod.toml`.
3. **Approve for publication** in a pull request that changes `publication.json` from `candidate` to `eligible` (with its `review` text) and records the per-file review: `python3 scripts/check_source_review.py --write`, then read every record ([source-review.md](source-review.md)). Passing the technical scan is not legal clearance; redistribution and licensing remain the maintainer's decision.
4. **Select it for a release:** `python3 scripts/prepare_release.py begin --tag v0.2.0 --package castle-of-illusion-widescreen-practice@0.1.0` (repeat `--package` for more; one release may mix games and schemas). Unknown, duplicate, internal, candidate and already-released selections fail and leave nothing behind. Write `docs/release-notes/v0.2.0.md` (a stub is created) and merge the pull request. CI rebuilds **only this prepared release's packages**.
5. **Create the draft:** run the **release** workflow from `main` with the tag (tick *dry run* first to rebuild and verify without creating anything). `scripts/release_guard.py` refuses a draft, a published release, an inconsistent one and a bad selection; the workflow builds exactly the listed packages (the product CLI at the pinned revision for schema 3, the pinned `segapatch.py` for schema 1/2), verifies each against its recorded digest and `SHA256SUMS`, and creates a **draft** with the assets.
6. **Publish.** A maintainer publishes the draft on GitHub. This is the only publishing action; the `verify-release` and `pages` workflows then compare the published assets of that tag with the metadata.
7. **Record it** in a follow-up pull request: `python3 scripts/prepare_release.py publish --tag v0.2.0 --commit <SHA> [--tag-commit <SHA>]` (the commit the tag points at), then `python3 scripts/build_catalog.py`. The catalog, and after the Pages deployment the site, now list the package with its download button. Never edit `catalog/index.json` by hand: CI rejects a stale one.
8. **Publish an updated version:** change the sources, bump `version` in `mod.toml`, run `pin` again (a new entry is added next to the old one), select `id@new-version` in a new release, and after publication run `prepare_release.py supersede --old id@old --new id@new`. The old entry stays downloadable and unchanged; a published version must be strictly increased, never replaced.

Release lifecycle checks, in the order they run: `release_guard.py` (new / draft / published / deleted / bad selection), repository checks, rebuild of the selected packages, draft, manual publication, `verify-release`, record, Pages.

## What each check costs

| Where | What runs | Scales with |
|---|---|---|
| Pull request, job `repository` | schemas, uniqueness, eligibility, explicit selection, source review, catalog freshness and immutability against the base branch, provenance at each release's pinned commit | the number of *records* (metadata and Git blobs); builds nothing |
| Pull request, job `exec` | tests of the Castle projects; `check_repo.py --segarecomp ... --changed-from <base>` checks and packs the patches the pull request touched plus the schema 3 packages a pending release selects; `rebuild_release.py --affected-from <base>` rebuilds only the prepared (not published) releases the change affects: a new or edited `releases/<tag>.json`, a changed, added, deleted or renamed file of a patch one of their packages comes from, a changed `publication.json` state of such a patch, or a shared build/validation path (`scripts/`, `catalog/schema/`: then all prepared releases). Documentation and site changes rebuild nothing; an unusable base fails closed (a first push without a base rebuilds every prepared release) | the packages being changed or prepared |
| `release` workflow | `rebuild_release.py --release <tag>`: exactly the listed packages and that release's `SHA256SUMS` | the packages being released |
| `audit` workflow (manual, weekly) | `rebuild_release.py --release <old tag>` for one or every recorded release, each from Git at its pinned commit with its own recorded tool revision | everything ever published, on demand only |

Published releases are never rebuilt routinely. They are protected by their stored digests, the pinned source commit (`verify_provenance.py`) and the immutability check against the base branch.

## Verifying an old release without rebuilding the others

```text
python3 scripts/rebuild_release.py --release v0.1.0 --work /tmp/rebuild          # one release; fetches the segapatch.py revision it was built with
python3 scripts/check_repo.py --assets <downloaded assets dir> --release v0.1.0   # compares the real GitHub assets with the records (hashes, sizes, SHA256SUMS)
```

A release with schema 3 packages also needs `--segarecomp <CLI built at that release's product revision> --segarecomp-ref <that revision>` (`build_packages.py --release TAG --print-product-ref` prints it; `scripts/build_product_cli.sh <ref> <dir>` builds it). A CLI built at another revision is refused. `rebuild_release.py --all` is the full audit; it is never run by a pull request or a release.

Each release records where its sources were: `source_layout` is `game-dir` for `v0.1.0` (sources under `patches/<platform>/<game>/source/` at its commit) and `patch-dir` for later releases. Rebuilds read the files from Git at the recorded commit in that layout, so moving files later never breaks reproducibility ([layout-and-versioning.md](layout-and-versioning.md)).

## Release records

`releases/<tag>.json` (`release_format` 2, schema [`release-2.schema.json`](../catalog/schema/release-2.schema.json)):

```json
{ "release_format": 2, "release": "v0.2.0", "status": "prepared", "source_layout": "patch-dir",
  "source_revision": { "repository": "https://github.com/marinocg/segarecomp-patches" },
  "packages": ["castle-of-illusion-widescreen-practice@0.1.0"] }
```

`build` appears on the release only for the schema 1/2 packages it lists (the shared writer); a schema 3 package records its own `build` (`segarecomp mod pack` at the pinned product revision). `source_revision.commit` and `tag` are added by `publish`. A prepared release cannot pin a commit or tag yet.

`license_declared_in_package` (schema 1/2) is `false` when the package manifest has no license field and the license is established by this repository instead. `authoring_revision` is an opaque identifier of the private authoring revision that produced a package.

## Checks you can run

* [Release notes v0.1.0](release-notes/v0.1.0.md).
* `python3 scripts/check_repo.py`: structure, metadata, links, forbidden content, source digests, catalog freshness. Needs no commercial data and builds nothing.
* `python3 scripts/build_packages.py --release TAG --out DIR --segapatch <segapatch.py> [--segarecomp CLI --segarecomp-ref SHA]`: builds the packages of **one** release with the product's own tools and fails unless each equals its recorded digest, size and identity.
* `python3 scripts/validate_catalog.py [--baseline-ref origin/main]`: schemas, selection rules and immutability.

Rebuilding a package needs no game image. Regenerating a BPS from an original image needs the image and private authoring inputs, so that step runs privately.

## Immutability and provenance

A published release is never altered: the release workflow refuses a tag that is published, drafted or already catalogued, and CI rejects any change to a published catalog entry or a removed one. Each package is tied to a reachable source commit and rebuilds from it to the same digest. Where artifacts live, and why R2 is not used, is recorded with measured numbers in [artifact-hosting.md](artifact-hosting.md); per-file publication review in [source-review.md](source-review.md); site deployment on GitHub Pages in [repository-settings.md](repository-settings.md).

## Excluded from v0.1.0

The presentation-only variants, all native-only validation packages, the earlier `sonic1-widescreen` prototype and the retired Sonic 2 1.0.0/2.0.0 validation package.
