# Cloudflare Pages deployment

`.github/workflows/cloudflare-pages.yml` builds the site, validates every package digest and deploys to Cloudflare Pages:

| Trigger | What runs |
|---|---|
| A release is **published** (or manual dispatch with a tag) | build, then **production** deployment (environment `cloudflare-production`). The published release assets are downloaded and compared with the catalog digests first; a wrong digest fails the run before anything is deployed |
| Pull request from this repository | build and validation, then a **preview** deployment (environment `cloudflare-preview`, branch alias `pr-<number>`) |
| Pull request from a **fork** | build and validation only. The workflow uses `pull_request` (never `pull_request_target`), so no secret exists for a fork, and the deploy jobs are additionally gated on the head repository being this one |

The `build` job has no secrets and `contents: read` only. Only the two deploy jobs see `CLOUDFLARE_API_TOKEN`, from their environment. No job has `contents: write` or `id-token`. The deploy command is `wrangler pages deploy` of the already-built, already-checked artifact; nothing is built after the checks.

## One-time human steps (cannot be done by the workflow)

1. In Cloudflare, create a **Pages** project (Direct Upload, no Git integration) named `segarecomp-patches`, or set the repository variable `CF_PAGES_PROJECT` to the name you used.
2. Create an **API token** scoped to that account with only the permission **Cloudflare Pages: Edit**. No zone, DNS, R2 or account-wide permission.
3. In GitHub, create the environments `cloudflare-production` and `cloudflare-preview`. Restrict `cloudflare-production` to deployment from the default branch and tags (`v*`), and require a reviewer if wanted. Add the secret `CLOUDFLARE_API_TOKEN` to **each environment** (not as a repository secret, so a stray workflow cannot read it).
4. Set the repository variables `CLOUDFLARE_ACCOUNT_ID` and, if the default `https://segarecomp-patches.pages.dev` is not the real address, `CF_SITE_URL` (a custom domain later is only a variable change; the site is built at the root path, `SITE_BASE` is empty).
5. Run the workflow once with **Run workflow** (a tag that already has a published release, for example `v0.1.0`), then record the resulting production URL below and in the SEG-134-T006 evidence. Disable `pages.yml` only after that.
6. Rotate the token if it is ever exposed; the repository's secret scan also looks for credential-shaped strings.

## Production URL

Not yet recorded: the first production deployment needs the human steps above. Record it here and in the task evidence after the first successful run.
