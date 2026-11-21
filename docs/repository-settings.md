# Repository settings

GitHub settings are not versioned by git. This document is the checked-in record of what `marinocg/segarecomp-patches` is expected to have, so drift is visible in review. A maintainer applies and re-verifies it in **Settings** (the agent that prepared this file cannot change admin settings). Verify with `gh api repos/marinocg/segarecomp-patches` and `gh api repos/marinocg/segarecomp-patches/branches/main/protection`.

## General

| Setting | Value |
|---|---|
| Visibility | Public |
| Default branch | `main` |
| Licence | MPL-2.0 |
| Merge method | Squash merge only; delete head branches on merge |
| Issues | Enabled, blank issues disabled (see `.github/ISSUE_TEMPLATE/config.yml`) |
| GitHub Pages | Source: **GitHub Actions** (`.github/workflows/pages.yml`); site at https://marinocg.github.io/segarecomp-patches/ ; environment `github-pages` deploys from `main` only; HTTPS enforced |
| Private vulnerability reporting | Enabled (referenced by `SECURITY.md`) |
| Secret scanning and push protection | Enabled |
| Dependabot alerts | Enabled |

## Branch protection for `main`

| Rule | Value |
|---|---|
| Require a pull request before merging | Yes; no direct pushes |
| Required approvals | 1 (the maintainer; a sole maintainer may use the admin bypass only for emergency revert, recorded in the PR) |
| Require review from Code Owners | Yes (`.github/CODEOWNERS`) |
| Dismiss stale approvals when new commits are pushed | Yes |
| Require status checks before merging | Yes, branch must be up to date |
| Required checks | `check / repository`, `site / build`, `site / samples` |
| Require conversation resolution | Yes |
| Block force pushes and deletions | Yes |
| Restrict who can create tags matching `v*` | Maintainer only (releases are drafted by `release.yml` and published by a maintainer) |

`check / repository` is the job `repository` in `.github/workflows/check.yml` (metadata-only repository checks, catalog freshness and immutability, provenance, unit tests, synthetic fixture; it builds no package). The job `exec` (`check / exec`) builds the pinned product CLI, runs the Castle executable tests, checks and packs the schema 3 projects the pull request changed and rebuilds only releases that are prepared but not published. It is informational by default; make it a required check once a pending release is expected to be validated before merge (the `release` workflow rebuilds and verifies the selected packages again before it creates any draft, so an unrequired `exec` can never publish a wrong package). The `audit` workflow is manual and weekly; it is not a check. `site / build` (static build, link check, search test) and `site / samples` (pinned-docs import and drift checks, claim lint, execution of every guide sample) are the jobs `build` and `samples` in `.github/workflows/site.yml`.

The `site / visual` job (browser rendering, screenshots uploaded as an artifact) is informational and deliberately **not** required: it depends on a downloaded browser, so a CDN outage must not block merges. Review its screenshots on design changes.

## Publishing

`pages.yml` builds `site/` on every push to `main` that touches the site, re-runs the link and search checks on the exact build output and deploys it with `actions/deploy-pages`. Only `main` may deploy (environment protection). The site base path is `/segarecomp-patches` (`SITE_BASE`, read by `site/astro.config.mjs` and the checks in `scripts/` and `site/scripts/`); a custom domain later means setting `SITE_URL`/`SITE_BASE=` and nothing else.

## GitHub Pages deployment

`pages.yml` deploys the documentation and catalog site (the only deployment target; no secret and no third-party deployment service is involved):

| Trigger | Checked out | What is verified before deploying |
|---|---|---|
| push to `main` touching `site/**`, `catalog/**`, the product-docs pin or the workflow; manual dispatch | the pushed / dispatched ref | catalog schema, provenance (full history, tags), source review, links, accessibility, SEO/JSON-LD/sitemap/robots/public-JSON checks, search |
| release **published** (or dispatch with a tag) | the repository's **default branch**, never the tag | the same, plus: the published assets of that tag are downloaded and compared with that release's metadata (`check_repo.py --assets DIR --release TAG`), so a wrong digest stops the deployment |

A release event's own ref is the tag, and the `v0.1.0` tag predates the site, so checking out the tag would deploy an old tree. The tag only selects which published assets are verified. `verify-release.yml` follows the same rule. The workflows have `contents: read` (deploy jobs add `pages: write` and `id-token: write`); pull requests only build and check the site (`site.yml`), GitHub Pages has no per-PR previews, and no secret exists for a fork.

Environment `github-pages`: the deployment's ref is the tag for a release event, so the environment must allow deployment from `main` **and** from release tags (`v*`); otherwise environment protection rejects the release-triggered run. The recorded production URL (https://marinocg.github.io/segarecomp-patches/) is an acceptance fact to be confirmed from the first real deployment after the merge, not before.

## Workflow permissions

Default `GITHUB_TOKEN` permission is read-only (`contents: read`); every workflow declares its permissions explicitly. Pull requests from forks never receive secrets. Workflows that publish (release) run only on manual dispatch.

## Keeping this document true

A change to a required check name, a workflow `name`/job id or a branch rule must update this file in the same pull request. `scripts/check_repo.py` verifies that the workflow files named above exist and that the required check names appear in this document.
