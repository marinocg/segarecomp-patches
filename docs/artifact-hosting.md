# Artifact hosting and the R2 decision

## Decision for the first release (recorded with its numbers)

**Release artifacts live on GitHub Releases. The documentation and catalog site is static files on GitHub Pages. Cloudflare R2 (and any other extra store) is not used.**

Measured by `python3 scripts/artifact_budget.py` on `catalog/index.json` (recorded here and asserted by `tests/test_release_pipeline.py`):

| Measure | Value | Threshold that would justify R2 |
|---|---|---|
| Packages in the catalog | 5 | n/a |
| Largest package | 9099 bytes | more than 20 MiB |
| All packages together | 35829 bytes | more than 500 MiB |
| Static files in the built site | counted in CI, a few dozen | more than 15,000 |

Vendor limits (GitHub Pages: published site up to 1 GB with soft bandwidth guidance; GitHub Release assets up to 2 GiB each) are those documented when the decision was written; re-verify them before relying on a margin. Every package is several orders of magnitude below the thresholds, and a release asset URL is already immutable, versioned and HTTPS. R2 would add an account, a bucket, credentials and a second place a digest could drift, for no measured benefit.

`artifact_budget.py` exits non-zero when a threshold is crossed (also in `pages.yml`, with the real file count of the built site), so the decision is revisited by a failing check, not by an outage. Bandwidth is not measurable from the repository; GitHub Releases and GitHub Pages serve static files without per-request cost to this project, and R2 is reconsidered if a maintainer reports a bandwidth problem, with the measured numbers added here.

## Immutability

* A **published** release is never altered. `.github/workflows/release.yml` runs `scripts/release_guard.py` first and refuses to run for a tag whose release is published, whose draft already exists (a maintainer deletes a draft deliberately; assets are never overwritten) or that the catalog already lists without a release. Tests: `tests/test_release_pipeline.py` (`Guard`).
* A published **catalog entry** never changes (`validate_catalog.py --baseline-ref`, see [catalog format](catalog-format.md)); a fix is a new package version, in a new collection release.
* Every package is tied to a **reachable source commit**: `source_revision.commit` in `release.json` is the squash commit on `main` that contains the sources (the `v0.1.0` tag points at the pre-squash pull-request head, which is not on `main`; it has the same tree, recorded as `tag_commit`). `scripts/verify_provenance.py` fails if the commit is not an ancestor of the checkout, if the tag no longer resolves to `tag_commit`, or if the sources at that commit differ from the recorded digests.
* **Rebuild from the tagged source reproduces the digest.** `scripts/build_packages.py` rebuilds every package from the committed sources with the pinned writer (`scripts/SEGAPATCH_REF`) and fails unless each equals `release.json`; CI runs it on every pull request, the release workflow before creating the draft, and `pages.yml` (against the published assets) before deployment. `verify-release.yml` then compares the published assets with `release.json` and `SHA256SUMS`.

## Reproducible-build record

`release.json` carries `build` (`writer`, the pinned `writer_ref`, `deterministic`) and `source_revision`; the catalog copies both into each entry; each catalog page shows them. Package digests are therefore reproducible from public inputs with no game image.
