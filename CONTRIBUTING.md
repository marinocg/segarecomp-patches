# Contributing

This repository distributes working patches, not experiments. A change is welcome when it fits that scope.

## Rules

1. **No commercial content.** Never commit ROMs, firmware, extracted assets, spritesheets, VRAM dumps, frame sequences, disassembly, traces, or other reconstructable game data. CI fails on forbidden file types and private-harness markers.
2. **Exact image identity.** A patch targets exact image SHA-256 digests. Never describe one by title or region alone.
3. **Only real, working patches.** A patch is publishable only if its archive is valid, its advertised behaviour is backed by real validation evidence, it works against the exact supported image, the supported tooling can verify and install it, its source and payload were reviewed, and its limitations are accurate. Experimental, validation-only or partially implemented packages do not belong here.
4. **No invented source.** A patch contains only reviewed source and, for a schema 1/2 package, the BPS delta that actually produced it (`source/`). Never add a provider to a BPS-only patch.
5. **Respect licenses.** Keep the license a package declares; do not relicense a provider because the repository is MPL-2.0.
6. **BPS deltas** live in `source/<package-id>.bps` and must be byte-identical to the `game.bps` inside the released package (checked by CI against the patch's `package.json`).
7. **Honest claims.** No claims of universal widescreen support or guaranteed gameplay preservation that evidence does not support.
8. **Native code is trusted code.** State plainly that it is executable and not sandboxed.

## Process

Work on a branch and open a pull request; `main` is not pushed directly. Run `python3 scripts/check_repo.py` before opening it.

A patch lives in `patches/<platform>/<game>/<patch>/` ([layout](docs/layout-and-versioning.md)): `README.md`, `mod.toml` and its `src/` for a schema 3 mod, or `package.json` and `source/` for a schema 1/2 package. **A patch is internal by default**: it is public source that can be built and tested, but it only becomes releasable when `publication.json` marks it `eligible` in a reviewed pull request, and it only ships when a release explicitly selects its `id@version` (`scripts/prepare_release.py begin`). Neither step publishes anything by itself; the maintainer publishes the GitHub Release. The whole path is in [docs/creating-patches.md](docs/creating-patches.md) and [docs/releases.md](docs/releases.md). Never edit `catalog/index.json`; it is generated (`python3 scripts/build_catalog.py`).

Commercial verification is recorded only as aggregate, maintainer-attested outcomes (for example "verified against the exact image, all listed scope"), never as logs or captures.

## Policy documents

- [Publication restrictions](docs/publication-restrictions.md): what may and may never be committed.
- [Trust classes and licensing](docs/policy.md): what each kind of package can do, who is trusted, and the licence of each directory.
- [Layout and versioning](docs/layout-and-versioning.md): the project layout `scripts/lint_layout.py` enforces and the versioning rules.
- [Repository settings](docs/repository-settings.md): branch protection and required checks.
- [Code of conduct](CODE_OF_CONDUCT.md).

CI also scans every text file for credentials and fails on forbidden file types.
