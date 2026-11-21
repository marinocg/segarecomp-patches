# Source review record

`docs/source-review.json` holds one record per source file of every patch that `publication.json` marks `eligible` (a schema 1/2 patch: its `source/` files; a schema 3 patch: `mod.toml` and the files under `src/`, `scripts/` and `edits/`): path, SHA-256, size, class, the longest run of consecutive byte literals, the publication decision and its rationale; plus the list of **excluded items** with a reason each. `python3 scripts/check_source_review.py` fails when a file has no record, when a recorded file changed (it must be re-reviewed, then `--write`), when a BPS exceeds 4 KiB, or when a source file contains 16 or more consecutive byte literals (the signature of an embedded data table).

This is a **technical content classification**, not a legal clearance. Redistribution and licensing decisions belong to the maintainer and are not recorded or implied here. The classes are:

| Class | Why it is publishable |
|---|---|
| `bps-delta` | at most 4 KiB of opcodes and a few literal bytes; it does not contain the original image and is useless without the exact source image (the migrated deltas are 50 to 172 bytes) |
| `package-manifest` | identifiers, digests and declared presentation defaults; no image content |
| `native-provider-source` | original C11 provider code written against the public SDK; no embedded table, asset or disassembly |
| `guest-asm-source`, `rom-edit-set`, `luau-source`, `mod-manifest-source` | original assembly or script text, a typed edit set (offsets and asserted values, no image content) and the `mod.toml` manifest of a schema 3 project |

Making a patch `eligible`, or changing any source file of an eligible patch, therefore needs a reviewed record in the same pull request: a patch without current records fails the check, so a patch cannot be approved for release without its review. Candidate and internal patches need none until they are proposed for approval. Items that were deliberately **not** migrated are listed under `excluded` in the JSON and in [releases.md](releases.md).
