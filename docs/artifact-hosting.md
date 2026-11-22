# Artifact hosting and the R2 decision

## Decision for the first release (recorded with its numbers)

**Release artifacts live on GitHub Releases. The documentation and catalog site is static files on GitHub Pages. Cloudflare R2 (and any other extra store) is not used.**

Measured by `python3 scripts/artifact_budget.py` on `catalog/index.json` (recorded here and asserted by `tests/test_release_pipeline.py`):

| Measure | Value | Threshold that would justify R2 |
|---|---|---|
| Packages in the catalog | 5 | n/a |
| Largest package | 36613 bytes | more than 20 MiB |
| All packages together | 72442 bytes | more than 500 MiB |
| Static files in the built site | counted in CI, a few dozen | more than 15,000 |

Vendor limits (GitHub Pages: published site up to 1 GB with soft bandwidth guidance; GitHub Release assets up to 2 GiB each) are those documented when the decision was written; re-verify them before relying on a margin. Every package is several orders of magnitude below the thresholds, and a release asset URL is already immutable, versioned and HTTPS. R2 would add an account, a bucket, credentials and a second place a digest could drift, for no measured benefit.

`artifact_budget.py` exits non-zero when a threshold is crossed (also in `pages.yml`, with the real file count of the built site), so the decision is revisited by a failing check, not by an outage. Bandwidth is not measurable from the repository; GitHub Releases and GitHub Pages serve static files without per-request cost to this project, and R2 is reconsidered if a maintainer reports a bandwidth problem, with the measured numbers added here.

## Immutability

* A **published** release is never altered. `.github/workflows/release.yml` runs `scripts/release_guard.py` first (states: new, draft, published, deleted/inconsistent, no metadata, superseding version; see [releases.md](releases.md)); a draft is deleted by a maintainer deliberately and assets are never overwritten. Tests drive the real scripts on synthetic repositories: `tests/test_release_lifecycle.py`.
* A published **catalog entry** never changes (`validate_catalog.py --baseline-ref`, see [catalog format](catalog-format.md)); a fix is a new package version, in a new collection release.
* Every package is tied to a **reachable source commit**: `source_revision.commit` in its `releases/<tag>.json` is the squash commit on `main` that contains the sources (the `v0.1.0` tag points at the pre-squash pull-request head, which is not on `main`; it has the same tree, recorded as `tag_commit`). `scripts/verify_provenance.py` fails if the commit is not an ancestor of the checkout, if the tag no longer resolves to `tag_commit`, or if the sources at that commit differ from the recorded digests.
* **Rebuild from the tagged source reproduces the digest.** `scripts/rebuild_release.py` rebuilds a release from its sources on demand (a published release from Git at its pinned commit, in the layout it had); pull requests and releases only rebuild the packages they prepare, the full audit is the manual `audit` workflow, with the package writer revision recorded for that release (`build.writer_ref`) and fails unless every package equals its metadata; CI runs it for every recorded release on every pull request, the release workflow runs it for the selected tag before creating the draft, and `pages.yml` compares the published assets of a tag with that release's metadata before deployment. `verify-release.yml` then compares the published assets with `release.json` and `SHA256SUMS`.

## Reproducible-build record

A release record carries `source_revision` and, for its schema 1/2 packages, `build` (`writer`, the pinned `writer_ref`, `deterministic`); a schema 3 package records its own `build` (`segarecomp mod pack` at the pinned product revision); the catalog copies both into each entry; each catalog page shows them. Package digests are therefore reproducible from public inputs with no game image.
