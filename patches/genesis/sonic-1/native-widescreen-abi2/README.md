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

The special stage's maze is sprites, and the game only builds the sprites of the blocks inside its own 320 px view, so in ABI 1 the maze stops at the old 4:3 edges while the background keeps going. The provider reconstructs the blocks the game would have drawn there:

* it extends the game's own 16 x 16 block-position grid to more cells; the extension is verified against all 256 buffered positions of the frame and on any doubt nothing is added;
* it learns the sprite pieces of each block type from the sprites the game DID build in the same frame (they are emitted in cell order; a block's pieces are centred on it, a block whose single piece is not centred takes the next sprite, a block that drew nothing is recognised by its neighbour matching the same sprite). Every later instance of a type must agree with the first, and a quarter of the blocks at most may need the off-centre rule, otherwise the frame is refused (fail-closed: nothing is drawn from a sequence the frame contradicts);
* a block type with no instance in the picture takes its pieces from a type with the same mapping pointer and frame in the game's item table, only its art-tile base differing (verified on every group of the real stage, and re-verified on real pixels by the redraw self-test);
* the pieces that reach into the margins are submitted as one virtual-sprite set (presentation space, art copied from the frame's own VRAM/CRAM, game cell order preserved so overlapping blocks stack as the game stacks them; the pieces the game kept are marked so a host that draws the hardware sprite layer in the margins does not draw them twice).

It remembers nothing between frames, so save/load and rewind need no special care, and no game art or table is stored in this repository.

**Exact scope of what is NOT reconstructed (measured on the recorded special-stage session, 585 frames per presentation; `abi_parity_compare.py --only coverage`):** the maze is delivered in 464 / 461 / 459 frames at 32:9 / 21:9 / 16:9. Every other frame is accounted for: 98 frames (guest frames 885-982) are the level-select / title fade into the stage and the pale transition grid, where the game draws no maze and its sprite table and block grid are stale; 1 frame (1308) has a sprite table one game frame apart from the block positions (every sprite offset by the same few pixels), so it is refused rather than drawn misplaced; 22 / 25 / 27 frames have no block in the margins at all. In the delivered frames eligible blocks are omitted only when their TYPE has no instance in the picture that frame and no same-mapping sibling either: 2,109 of 19,970 eligible blocks at 32:9 (10.6%, of which type 45 alone is 1,125 and is never on screen in this session), 427 of 10,330 at 21:9 (4.1%) and 88 of 5,544 at 16:9 (1.6%), types 37, 39, 41, 45 and 59; type 74 (a further 808 / 687 / 282 instances) draws nothing whenever it is seen, so it costs nothing. Six frames at 32:9 need more than the host's 64 virtual-sprite commands (at most 68; the farthest pieces are dropped, in the game's order). The overlay can carry them exactly: `abi_parity_compare.py --only overflow` records each such frame's complete ordered piece inventory, composes an INDEPENDENT expected picture from the frame's own VRAM/CRAM (validated first on frames within the limit, where production's output is known) and shows that compositing the dropped pieces into one RGBA overlay layer reproduces it with 0 differing pixels in all six frames (every dropped piece's pixels restored); the provider does not do this yet. The omitted types cannot be reconstructed without the game's own mapping data, which a provider cannot read at run time; that is the open completeness limit of the requirement (SEG-152-T018 proposes the product contract: read-only access to declared ROM ranges). Known minor defect, not yet fixed: pieces the game kept (marked `HARDWARE_PIECE`) are drawn by the host beneath the virtual pieces, so where one overlaps a later margin block the stacking differs from the game's by a few pixels (6-9 pixels in 3 of 20 measured frames); the follow-up removes the marking.

## Reproduce the parity comparison (local only; needs the legally held image and a product checkout built at `scripts/PRODUCT_REF`)

```sh
python3 tools/abi_parity_compare.py --product-root <product> --cli <segarecomp> --sdl <sdl3> --cc cc --rom <Sonic 1 image> \
  --abi1 patches/genesis/sonic-1/native-widescreen --abi1-id sonic1-native-widescreen \
  --abi2 patches/genesis/sonic-1/native-widescreen-abi2 --work <dir> --scenario-set s1 \
  --only level,demos,transitions,lifecycle,visual,acts,special,coverage,planes,overflow,fault
```

It prints aggregates only (frame counts and the named mechanisms that differ); there is no tolerance, no skipped frame and no normalisation.
