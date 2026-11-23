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

The port keeps the ABI 1 provider's game knowledge, constants and verification logic unchanged and only changes how the answers are delivered (scenery windows instead of the per-cell callback, the generic mask for the special stage, one RGBA bitmap for the HUD, a refusal with the ABI 1 reason instead of a decline). Played in the real viewer next to the ABI 1 package with identical input (the product's own `segarecomp build` for both, the same scripted run), the HUD and the foreground plane match, but **the background plane of Green Hill Zone cannot be expressed by the ABI 2 scenery windows**:

* The ABI 1 provider answers every off-picture cell of every screen line with the world cell at *that line's own* world origin (each background parallax band has its own scroll). The ABI 2 window is keyed by **plane cell** (`plane x = screen x - hscroll`, `plane y = line + vscroll`, unwrapped), one word per plane cell for the whole frame.
* Two bands that share a plane cell row (their boundary falls inside an 8-line cell row) ask the same plane cell with origins that differ by a multiple of 512 pixels (64 cells), so the same plane cell needs two different words. This is the "origin-multiple" class that SEG-152-T001 recorded as a *watched* class with a synthetic failing fixture only (no real-provider measurement existed for Sonic 1). The per-row generic mask of SEG-152-T007 expresses a line answered by the VDP's *own* plane word, which is not the world cell the ABI 1 provider serves in the margin columns, so it cannot express it either.
* Measured with the local comparison below (one scripted 5,000-frame run of the verified scene, identical results at 32:9 and 16:9): the HUD is served on the same 3,775 frames for both packages, but of the 3,775 frames in which the ABI 1 provider authors scenery the ABI 2 port can serve **877**; **2,898 (77%) differ** in accepted components, authored status and coverage accounting (the window builder refuses the frame's scenery honestly: a refusal, not a fault). A probe build of the port on a second, longer scripted run classified the conflicts: 3,436 of 4,064 authored frames (85%), always plane B, always a difference of exactly 64 cells, one to three plane cell rows and 98 to 1,946 asked cells per conflicting frame. Serving only the cells that do not conflict would be a documented difference and a regression, which the task forbids.

No tolerance, no skipped frame and no ad hoc API addition was used. The way forward is a product-side decision (a scenery answer that is aware of per-line origins, or a bounded per-line origin-adjusted window), which is a refinement question, not a patches change.

## Reproduce (local only; needs the legally held image and a product checkout)

```sh
python3 tools/abi_parity_compare.py --product-root <product> --cli <segarecomp> --sdl <sdl3> --cc cc --rom <Sonic 1 image> \
  --abi1 patches/genesis/sonic-1/native-widescreen --abi1-id sonic1-native-widescreen \
  --abi2 patches/genesis/sonic-1/native-widescreen-abi2 --work <dir> --scenario-set s1 --only level-wide
```

The tool prints aggregates only (frame counts and the named mechanisms that differ); nothing commercial is written.
