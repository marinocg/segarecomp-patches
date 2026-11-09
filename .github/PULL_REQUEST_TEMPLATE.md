## What changes

<!-- One coherent change. Name the package ids / docs touched. -->

## Checklist

- [ ] No ROM, BIOS, disc image, firmware, extracted asset, disassembly, trace, VRAM/frame dump or other reconstructable game data (see `docs/publication-restrictions.md`).
- [ ] No secrets, tokens, keys or private-harness paths.
- [ ] Patches target exact image SHA-256 digests; claims match real evidence (aggregate, maintainer-attested at most).
- [ ] `python3 scripts/check_repo.py`, `python3 scripts/build_catalog.py --check` and `python3 -m unittest discover -s tests -q` pass locally.
- [ ] Native code (`provider.c`) is described as executable and not sandboxed.
