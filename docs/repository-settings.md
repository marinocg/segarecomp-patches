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

`check / repository` is the job `repository` in `.github/workflows/check.yml` (repository checks, catalog freshness, unit tests, synthetic fixture, package rebuild). `site / build` (static build, link check, search test) and `site / samples` (pinned-docs import and drift checks, claim lint, execution of every guide sample) are the jobs `build` and `samples` in `.github/workflows/site.yml`.

The `site / visual` job (browser rendering, screenshots uploaded as an artifact) is informational and deliberately **not** required: it depends on a downloaded browser, so a CDN outage must not block merges. Review its screenshots on design changes.

## Publishing

`pages.yml` builds `site/` on every push to `main` that touches the site, re-runs the link and search checks on the exact build output and deploys it with `actions/deploy-pages`. Only `main` may deploy (environment protection). The site base path is `/segarecomp-patches` (`SITE_BASE`, read by `site/astro.config.mjs` and the checks in `scripts/` and `site/scripts/`); a custom domain later means setting `SITE_URL`/`SITE_BASE=` and nothing else.

## Workflow permissions

Default `GITHUB_TOKEN` permission is read-only (`contents: read`); every workflow declares its permissions explicitly. Pull requests from forks never receive secrets. Workflows that publish (release) run only on manual dispatch.

## Keeping this document true

A change to a required check name, a workflow `name`/job id or a branch rule must update this file in the same pull request. `scripts/check_repo.py` verifies that the workflow files named above exist and that the required check names appear in this document.
