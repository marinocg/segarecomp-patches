# Imported product documentation

The documentation site republishes three product documents (`patch-packages.md`, `native-patch-sdk.md`, `widescreen-and-patches.md`). The **product repository stays authoritative**; this repository only carries mechanical copies.

## The pinned-revision rule

[`product-docs.pin.json`](product-docs.pin.json) records:

- `pinned_commit`: the exact product commit the pages were imported from, and the commit the compatibility-ledger links point at;
- `minimum_commit`: the oldest product revision whose documentation this site is allowed to describe;
- the list of imported files and the page each becomes.

`scripts/import_product_docs.py` has three modes:

| Mode | What it does | Fails when |
|---|---|---|
| `--write` | Regenerates `site/src/content/docs/product/*.md` from the pin (links to other imported documents become site routes; every other relative link points at the pinned product revision) | the source file is missing at the pin |
| `--check` | Regenerates in memory and compares with the committed pages | a page was edited by hand or the pin moved without re-importing |
| `--drift` | Asks Git (or the GitHub compare API) whether `pinned_commit` is at or after `minimum_commit` | the pin is **behind** the declared minimum |

Never edit an imported page by hand. To change wording, change it in the product repository, move `pinned_commit` forward, run `--write` and review the diff. To require newer documentation, raise `minimum_commit`: the drift check then fails until the pin catches up.

## Executable samples

Every code block in `site/src/content/docs/getting-started.md` carries a marker line above it: `<!-- sample: exec -->` (run by `scripts/run_guide_samples.py` in CI against the product tools at `scripts/SEGAPATCH_REF` and the shipped CLI release recorded in the pin), `<!-- sample: exec-cli -->` (the same, needing the shipped `segarecomp` binary) or `<!-- sample: non-executable: <reason> -->`. An unmarked block fails the check.

## Support claims

Site pages written here make no support claim. `scripts/check_site_content.py` rejects blanket-support wording in authored pages, rejects mentions of unimplemented formats (schema 3, ABI 2, scripting) that are not clearly negated, and requires the support page to point at the product compatibility ledger. Imported pages are exempt because they are verbatim product text.
