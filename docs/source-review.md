# Source review record

`docs/source-review.json` holds one record per file under `patches/*/*/source/`: path, SHA-256, size, class, the longest run of consecutive byte literals, the publication decision and its rationale; plus the list of **excluded items** with a reason each. `python3 scripts/check_source_review.py` fails when a file has no record, when a recorded file changed (it must be re-reviewed, then `--write`), when a BPS exceeds 4 KiB, or when a source file contains 16 or more consecutive byte literals (the signature of an embedded data table).

This is a **technical content classification**, not a legal clearance. Redistribution and licensing decisions belong to the maintainer and are not recorded or implied here. The classes are:

| Class | Why it is publishable |
|---|---|
| `bps-delta` | at most 4 KiB of opcodes and a few literal bytes; it does not contain the original image and is useless without the exact source image (the migrated deltas are 50 to 172 bytes) |
| `package-manifest` | identifiers, digests and declared presentation defaults; no image content |
| `native-provider-source` | original C11 provider code written against the public SDK; no embedded table, asset or disassembly |

Adding or changing any source file therefore needs a reviewed record in the same pull request. Items that were deliberately **not** migrated are listed under `excluded` in the JSON and in [releases.md](releases.md).
