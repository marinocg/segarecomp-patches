# Sonic the Hedgehog (Genesis): native widescreen as a schema 3 / ABI 2 package (SEG-152-T009): BLOCKED, NOT RELEASABLE

> The source of the ABI 2 port of the [Sonic 1 widescreen provider](../native-widescreen/README.md), kept as **internal** public source so the blocking evidence is reproducible. It is **not** a candidate, has no package pin, is never selected by a release and must not be installed to replace the published ABI 1 package. SEG-152-T009 stopped on its own rule: *if exact parity is impossible because of an architectural limitation, stop, record the evidence and return to refinement*.

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Revision | USA/Europe REV00 only: original image SHA-256 `46160baa06362c711c9f1a5017cb7371026444936c8af5e93a78996cf32ff2a6` |
| Package schema / ABI | schema 3, native ABI 2 minor 2 (`bps-image` + `native-c11`; capabilities `frame.vdp`, `frame.work_ram`, `overlay.rgba`, `scenery.words`) |
| BPS delta | `bps/game.bps` is byte-for-byte the delta of the published ABI 1 package (source and target digests unchanged); `[build] header_repair = "none"` keeps the patched image equal to that target |
| Status | **internal, blocked**: see below |

## Why it is blocked

The port keeps the ABI 1 provider's game knowledge, constants and verification logic unchanged and only changes how the answers are delivered (scenery windows instead of the per-cell callback, the generic mask for the special stage, one RGBA bitmap for the HUD, a refusal with the ABI 1 reason instead of a decline). Its window builder asks exactly the cells the host asks (only off-picture pixels, per line). Played in the real viewer next to the ABI 1 package with identical input, the HUD and the foreground plane match, but **the background plane of Green Hill Zone cannot be expressed by the ABI 2 scenery windows** (the mechanism, with a synthetic schematic: [docs/abi2-scenery-line-origins.md](../../../../docs/abi2-scenery-line-origins.md)):

* The ABI 1 provider answers every off-picture cell of every screen line with the world cell at *that line's own* world origin. The ABI 2 window is keyed by **plane cell** (`plane x = screen x - hscroll`, `plane y = line + vscroll`, unwrapped): one word per plane cell for the whole frame.
* In the lower background region the game scrolls every line by a different amount. As that per-line scroll ramps, the nearest-alias world origin of adjacent lines flips by 512 px (64 plane cells), so two lines of one plane-cell row ask the same plane cell with origins 512 px apart and need two different words. This is the "origin-multiple" class that SEG-152-T001 recorded as *watched* with a synthetic failing fixture only. The per-row generic mask of SEG-152-T007 answers a line with the VDP's *own* plane word, which is not the world cell the ABI 1 provider serves in the margin columns, so it cannot express it either.
* Measured (aggregate): the HUD is served on the same 3,775 frames for both packages, but of the 3,775 frames in which the ABI 1 provider authors scenery the ABI 2 port can serve **877**; **2,898 (77%) differ** in accepted components, authored status and coverage accounting (the window builder refuses the frame's scenery: a refusal, not a fault). Every refused frame contains a conflict and every conflict frame is refused (one-to-one, one constant frame-number offset between the provider's and the viewer's numbering). A conflict is always plane B, one or two plane-cell rows and 118 to 215 cells at 32:9 (18 to 21 at 16:9), always a difference of exactly 64 cells. The conflicting cells and their two words were **recomputed independently from the game's work RAM** (not from this source) and match the instrumented port exactly at the previous-onset RAM in every captured conflict frame; where no such pair exists the port is pixel-identical to ABI 1. Serving only the cells that do not conflict would be a documented difference and a regression, which the task forbids.

No tolerance, no skipped frame, no exception and no ad hoc API addition was used. The way forward is the product-side capability proposed as SEG-152-T017 (a per-row scenery origin delta), which is a refinement decision, not a patches change.

## Reproduce (local only; needs the legally held image and a product checkout)

```sh
python3 tools/abi_parity_compare.py --product-root <product> --cli <segarecomp> --sdl <sdl3> --cc cc --rom <Sonic 1 image> \
  --abi1 patches/genesis/sonic-1/native-widescreen --abi1-id sonic1-native-widescreen \
  --abi2 patches/genesis/sonic-1/native-widescreen-abi2 --work <dir> --scenario-set s1 --only level-wide,level-w169
python3 tools/sonic1_conflict_diagnosis.py --product-root <product> --cli <segarecomp> --sdl <sdl3> --cc cc --rom <Sonic 1 image> --work <dir> --diag <a directory OUTSIDE this repository>
```

The first prints aggregates only (frame counts and the named mechanisms that differ). The second writes side-by-side captures, difference pictures and conflict overlays of the real game into `--diag` (refused inside the repository: real-game pictures are never committed or uploaded) and prints aggregates only.
