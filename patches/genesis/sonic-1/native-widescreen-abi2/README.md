# Sonic the Hedgehog (Genesis): native widescreen as a schema 3 / ABI 2 package (SEG-152-T009)

> The source of the ABI 2 port of the [Sonic 1 widescreen provider](../native-widescreen/README.md). It reproduces the published ABI 1 package's behaviour frame for frame, with one operator-approved addition: the special-stage maze is drawn into the widescreen margins (below). It has no package pin yet, is not selected by any release and does not replace the published ABI 1 package (which stays published and unchanged).

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Revision | USA/Europe REV00 only: original image SHA-256 `46160baa06362c711c9f1a5017cb7371026444936c8af5e93a78996cf32ff2a6` |
| Package schema / ABI | schema 3, native ABI 2 minor 3 (`bps-image` + `native-c11`; capabilities `frame.vdp`, `frame.work_ram`, `overlay.rgba`, `scenery.words`) |
| BPS delta | `bps/game.bps` is byte-for-byte the delta of the published ABI 1 package (source and target digests unchanged); `[build] header_repair = "none"` keeps the patched image equal to that target |
| Special stage | the maze blocks the game culls at the 4:3 edges are drawn in the margins (virtual sprites; the native picture stays pixel-identical to ABI 1; `actors` is declared for the `special-stage` scene) |
| Presentation | the centred baseline (the provider declares no `view_left`); windows are built from the planned margin and a `left_px` variable |

## How the scenery is delivered

The game scrolls every line of the lower background by a different amount, so two lines of one plane-cell row can ask the same plane cell with world origins 512 px (64 cells) apart ([the mechanism](../../../../docs/abi2-scenery-line-origins.md)). The provider therefore states, per produced row and plane, the line's whole-cell world shift with `scenery_row_origin` (ABI 2 minor 3) and keys its windows by the translated world column: one window when the translated width is at most 128 columns, else two equal halves up to 256, else the scenery is declined (`bad_state`). The special-stage wrapped plane stays on the per-row generic mask, the HUD is one RGBA bitmap, and refusals carry the ABI 1 reason.

## The special-stage maze in the margins

The special stage's maze is sprites, and the game only builds the sprites of the blocks inside its own 320 px view, so in ABI 1 the maze stops at the old 4:3 edges while the background keeps going. The provider reconstructs the blocks the game would have drawn there: it extends the game's own 16 x 16 block-position grid to more cells (the extension is verified against all 256 buffered positions of the frame; on any doubt nothing is added), learns the sprite pieces of each block type from the sprites the game DID build in the same frame (they are emitted one block after the other, centred on the block), and submits the pieces that reach into the margins as one virtual-sprite set (presentation space, art copied from the frame's own VRAM/CRAM, pieces the game kept are marked so a host that draws the hardware sprite layer in the margins does not draw them twice). It remembers nothing between frames, so save/load and rewind need no special care, and no game art or table is stored in this repository. A block type that has no instance inside the picture in that frame cannot be learned and is left out of that frame; at most 64 pieces are submitted per frame (the nearest to the picture first; 52 was the maximum measured at 32:9).

## Reproduce the parity comparison (local only; needs the legally held image and a product checkout built at `scripts/PRODUCT_REF`)

```sh
python3 tools/abi_parity_compare.py --product-root <product> --cli <segarecomp> --sdl <sdl3> --cc cc --rom <Sonic 1 image> \
  --abi1 patches/genesis/sonic-1/native-widescreen --abi1-id sonic1-native-widescreen \
  --abi2 patches/genesis/sonic-1/native-widescreen-abi2 --work <dir> --scenario-set s1 \
  --only level,demos,transitions,lifecycle,visual,acts,special
```

It prints aggregates only (frame counts and the named mechanisms that differ); there is no tolerance, no skipped frame and no normalisation.
