# Contributing

This repository distributes working patches, not experiments. A change is welcome when it fits that scope.

## Rules

1. **No commercial content.** Never commit ROMs, firmware, extracted assets, spritesheets, VRAM dumps, frame sequences, disassembly, traces, or other reconstructable game data. CI fails on forbidden file types and private-harness markers.
2. **Exact image identity.** A patch targets exact image SHA-256 digests. Never describe one by title or region alone.
3. **Only real, working patches.** A patch is publishable only if its archive is valid, its advertised behaviour is backed by real validation evidence, it works against the exact supported image, the supported tooling can verify and install it, its source and payload were reviewed, and its limitations are accurate. Experimental, validation-only or partially implemented packages do not belong here.
4. **No invented source.** `source/` contains only reviewed source and the BPS delta that actually produced the package. Never add a provider to a BPS-only patch.
5. **Respect licenses.** Keep the license a package declares; do not relicense a provider because the repository is MPL-2.0.
6. **BPS deltas** live in `source/<package-id>.bps` and must be byte-identical to the `game.bps` inside the released package (checked by CI against `release.json`).
7. **Honest claims.** No claims of universal widescreen support, full-campaign compatibility or guaranteed gameplay preservation that evidence does not support.
8. **Native code is trusted code.** State plainly that it is executable and not sandboxed.

## Process

Work on a branch and open a pull request; `main` is not pushed directly. Run `python3 scripts/check_repo.py` before opening it. A new patch needs `README.md`, `release.json` (see [docs/releases.md](docs/releases.md)) and, if it has native code, `source/provider.c` whose SHA-256 equals the package's native source digest. Regenerate `catalog/index.json` with `python3 scripts/build_catalog.py`.

Commercial verification is recorded only as aggregate, maintainer-attested outcomes (for example "verified against the exact image, all listed scope"), never as logs or captures.
