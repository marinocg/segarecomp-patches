# Trust classes and licensing

## Trust classes

Trust is decided by what a package can *execute*, not by who published it. The classes follow the product's trust policy (`docs/architecture/luau-trust-policy.md` and ADR 0284 in the segarecomp repository, which is authoritative). Every class, including data-only, is **untrusted input** to the importer and the build: archives are parsed with bounds and digest checks, and a digest proves integrity, never authorship.

| Class | `release.json` `trust` | Executes code? | Status in this repository | User consent in the launcher |
|---|---|---|---|---|
| BPS-only (data-only) | `data-only` | No. A verified BPS delta produces a patched image that is then recompiled. | Published today (schema 1). | Install; no native-code approval. |
| Native (trusted native source) | `trusted-native-source` | **Yes.** `provider.c` is compiled into the Patched program and runs with its operating-system permissions. **Not sandboxed.** | Published today (schema 2). | Explicit approval of the exact package identity (author, licence, source digest, capabilities, "contains executable source, not sandboxed"). |
| Luau-only | _reserved_ | Scripted logic in the product's Luau runtime. | **Not available.** Not accepted by `scripts/check_repo.py`; no package of this class is published. | Would need consent but not native-code approval. |
| Mixed (native + Luau) | _reserved_ | Inherits the **native** class: a mixed package is exactly as trusted as native. | **Not available.** | Native approval. |

Rules that follow:

1. A package that contains any native source is native, whatever else it contains. A BPS delta next to a provider does not lower the class.
2. Safety is a property of host bindings, configuration and adversarial tests, never of "it is only a script" or of the language alone. This repository makes no sandbox claim for any class.
3. `check_repo.py` accepts only the classes marked "Published today"; adding a class is a policy change that must update this table, the CI check and the product's launcher together.
4. There are no signatures. Do not describe a digest or a catalog entry as a trust endorsement.

## Licensing

| Path | Licence | Notes |
|---|---|---|
| Repository default (tooling in `scripts/`, `tests/`, `.github/`, catalog, `site/`) | MPL-2.0 (`LICENSE`) | |
| `docs/` and `site/src/content/docs/` prose | MPL-2.0 (the repository default) | A separate documentation licence (for example CC-BY-4.0) is **not** adopted; adopting one is a maintainer decision recorded here first. |
| `patches/<platform>/<game>/source/provider.c` | The licence the package declares in `release.json` (`MIT` or `MPL-2.0`); text in `LICENSES/MIT.txt` or `LICENSE` | Never relicense a provider because the repository is MPL-2.0 (CONTRIBUTING rule 5). |
| `patches/<platform>/<game>/source/*.bps` | Covered by the package licence; contains no game content | See [publication restrictions](publication-restrictions.md). |
| `site/public/fonts/Silkscreen-*.ttf` | SIL Open Font License 1.1 (`LICENSES/Silkscreen-OFL.txt`) | Used for headings and labels of the documentation site; copied unmodified from the product launcher assets. |
| Imported product documentation under `site/src/content/docs/product/` | MPL-2.0 per the product repository | The product repository stays authoritative; see [docs/product-docs.md](product-docs.md). |

Commercial games, firmware and assets are never covered by any licence here because they are never committed.

## Secret scan and forbidden files

`scripts/check_repo.py` (run by the `check` workflow on every pull request and push to `main`) fails on:

- forbidden file types (ROM, disc, archive, dump and save extensions), any file over 512 KiB and any `.bps` outside `patches/<platform>/<game>/source/`;
- private-harness markers in text files;
- credential-shaped strings in any tracked text file (private key blocks, GitHub, npm, Slack, AWS, Google and Cloudflare-style tokens, and `password =`/`secret =`/`token =` assignments with a long literal value).

Negative fixtures for each rule are in `tests/test_check_repo.py`. The scan is a tripwire, not a guarantee: a leaked credential must still be revoked, not merely removed.
