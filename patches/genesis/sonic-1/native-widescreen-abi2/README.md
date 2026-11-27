# Sonic the Hedgehog (Genesis): native widescreen as a schema 3 / ABI 2 package (SEG-152-T009)

> The source of the ABI 2 port of the [Sonic 1 widescreen provider](../native-widescreen/README.md). It reproduces the published ABI 1 package's behaviour frame for frame, with two additions: the special-stage maze is drawn into the widescreen margins, and the native picture shifts within the widescreen surface with the camera (adaptive placement, below). It has no package pin yet, is not selected by any release and does not replace the published ABI 1 package (which stays published and unchanged).

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Revision | USA/Europe REV00 only: original image SHA-256 `46160baa06362c711c9f1a5017cb7371026444936c8af5e93a78996cf32ff2a6` |
| Package schema / ABI | schema 3, native ABI 2 minor 3 (`bps-image` + `native-c11`; capabilities `frame.vdp`, `frame.work_ram`, `memory.read.m68k.rom` (four declared ranges, 1,935 bytes), `overlay.rgba`, `scenery.words`) |
| BPS delta | `bps/game.bps` is byte-for-byte the delta of the published ABI 1 package (source and target digests unchanged); `[build] header_repair = "none"` keeps the patched image equal to that target |
| Special stage | the maze blocks the game culls at the 4:3 edges are drawn in the margins on every special stage and ratio (virtual sprites, overlay beyond 64 commands; the native picture stays pixel-identical to ABI 1; `actors` is declared for the `special-stage` scene) |
| Presentation | adaptive native-picture placement in the running level of **Green Hill acts 1-3 only** (SEG-152-T014, `view_left`; every other act with scenery keeps its scenery and HUD with the picture centred): left aligned at the level's first camera position, centred in the middle, right aligned at the last one, with slow ramps; the special stage stays centred; building with `S1_PLACEMENT` 0 gives the centred SEG-152-T009 baseline |

## Adaptive native-picture placement (SEG-152-T014)

The host plans one total of `2 * margin` extension columns from the display ratio; the provider only chooses how many of them lie left of the 320-pixel picture (`left_px`) and declares it with `view_left` for the very frame whose scenery windows it built for that placement and margin (ADR 0315 / ADR 0320: the exact-frame `render` of this provider, so there is no lag to manage). The placement is a **pure function of the camera and the camera's right limit** (no state: replay, rewind, save/load and an aspect change see the same value for the same camera, and a placement is never served with windows built for another margin):

* aligned **left** (`left_px` 0, every extension column right of the picture) at the level's first camera position, **centred** (`left_px` = margin) in the middle and aligned **right** (`left_px` = 2 x margin, every extension column left of the picture) at the last camera position, so no void is shown left of the level and the view never passes its end;
* it ramps **slowly** at both ends, over `RAMP_DEN` (6) margins of camera travel (`zone = min(range / 2, 6 x margin)`, at most 1/6 of a pixel per camera pixel and never faster than the camera moves), and is constant elsewhere. The slowness is the parallax: the guest draws the background for its own camera, so while `left_px` changes every background layer drifts against the foreground at `(1 - k) x d(left_px)/d(camera)`. This game's background cameras are exactly 3/8 and 1/2 of the foreground camera in all three acts (measured; the finer per-line bands move at fractions of those), so the worst drift is `(1 - k) / 6` of the camera's speed (at most 1/6, the camera's own maximum speed is 16 px/frame); a 1:1 slide froze the world and slid every background layer backwards (the "dizzying parallax" of the first Castle of Illusion sketch). The reference shape is the Castle of Illusion package's `placement(cam, range, margin)`; its limits, RAM and ramp are not assumed;
* in the adaptive acts the camera's **first value is 0** (the layout's first column is world x 0) and its **last value is the game's right limit** word (`v_limitright2`, work RAM `0xF722`; constant per act in the supported scope, and the camera never passes it). The left limit word is deliberately not read: the end-of-act sequence sets it to the right limit to lock the screen, which would collapse a camera-only range and make the placement jump. A right limit the world cannot hold, or zero, keeps the picture centred (the "verified boundary not obtainable" fallback; none occurs in the supported scope);
* a level whose range is narrower than the planned total (`range < 2 x margin`, not reached by any supported act: the shortest measured range is 4,271 px, Labyrinth act 2, against a planned total of at most 476 px) keeps the plain rule: the picture at the left until the camera is `margin` in;
* the **special stage** (the VDP's own wrapped plane, no left/right world boundary) and the level start sequence stay centred / declined exactly as in the baseline; Original and 4:3 present no extension and stay centred. The HUD overlay and the virtual-sprite anchoring follow the host's existing behaviour for a placement;
* a frame whose scenery is not served (any decline) is presented centred by the host; the provider declares `view_left` only for a frame it serves.

### Verified adaptive acts and centred fallbacks

Eligibility for authored scenery (`k_scenery_acts`: acts 1-3 of all six zones and the fourth slot of zone 1, as in ABI 1) is separate from eligibility for placement (`k_placement_acts`):

| Acts | Placement | Why |
|---|---|---|
| Green Hill 1, 2, 3 | **adaptive** | camera start 0, right limit word = last camera value, ramp, windows, save/load, rewind and aspect transitions verified at 16:9, 21:9 and 32:9 |
| Labyrinth, Marble, Star Light, Spring Yard, Scrap Brain (acts 1-3 where present) and the fourth slot of zone 1 | **centred fallback** (scenery and HUD exactly as the centred baseline) | boundaries were flown at 32:9 only (camera start and right-limit agreement, placement function) and without the per-ratio, lifecycle and reversal evidence; the fallback is a recorded not-yet-verified class, pending operator approval or further evidence |
| Special stage, level start sequence, other modes, Original, 4:3 | unchanged | as in the baseline |

### Windows for any placement (the capacity rework this needed)

Aligned right, the extension is all on one side, and the lower background's bands scroll independently, so a plane can ask many more distinct world columns than the SEG-152-T009 baseline's single contiguous span allowed (the baseline already declined the whole frame in the far part of Green Hill 1 and 3 at 32:9, and act 3 at 21:9). The provider now:

1. asks and builds only what the host asks (never the picture itself, never a side with no extension) and covers it with at most two windows of at most 128 columns by a greedy cover of the asked columns;
2. when that is not enough, splits the plane's rows once and gives each group of rows one window over the columns its own lines ask;
3. when two windows still cannot hold every line (the same limit as the host's two-window API), the lines that do not fit are answered by the VDP's own plane (the per-row generic mask, the ABI 1 `own_plane` lines) and every other line keeps its authored scenery. Measured on the traversals below: only at 32:9 in the far right part of Green Hill 1 (3.1 % of the frames, at most 46 of 224 lines) and 3 (5.7 %, at most 47 lines), and at 21:9 in act 3 (0.7 %, at most 2 lines); never at 16:9 or in act 2.

Nothing outside the asked cells is ever read from the world (the synthetic-RAM test under AddressSanitizer/UBSan checks every asked cell against a window and the window limits).

## How the scenery is delivered

The game scrolls every line of the lower background by a different amount, so two lines of one plane-cell row can ask the same plane cell with world origins 512 px (64 cells) apart ([the mechanism](../../../../docs/abi2-scenery-line-origins.md)). The provider therefore states, per produced row and plane, the line's whole-cell world shift with `scenery_row_origin` (ABI 2 minor 3) and keys its windows by the translated world column (packing as in the previous section: at most two windows per plane, rows split once when needed, the lines no two windows can hold on the per-row generic mask). The special-stage wrapped plane stays on the per-row generic mask, the HUD is one RGBA bitmap, and refusals carry the ABI 1 reason.

## The special-stage maze in the margins

The special stage's maze is sprites, and the game only builds the sprites of the blocks inside its own 320 px view, so in ABI 1 the maze stops at the old 4:3 edges while the background keeps going. The provider reconstructs the blocks the game would have drawn there:

* it extends the game's own 16 x 16 block-position grid to more cells; the extension is verified against all 256 buffered positions of the frame and on any doubt nothing is added;
* the sprite pieces of every block type come from the game's own mapping tables: the game's item table (work RAM) names, per block type, a mapping pointer, a frame and an art-tile base, and the mapping bytes are read from the cartridge through the four `m68k.rom` ranges the manifest declares (1,935 bytes in all, SEG-152-T018 / ADR 0321: the host materialises exactly those bytes from the user's own image at build; the record format is generic Genesis sprite-mapping layout and no mapping byte is stored in this repository). A pointer or frame outside the declared ranges is never read: the type is then unavailable and its blocks are left out;
* the game's own sprite table of the frame is a witness, not a source: the sprites that follow the leading non-block sprites must be exactly the mapping's pieces of the blocks the game drew, in cell order (position, size and tile word); any difference refuses the frame (the intro frames, where the sprite table is not the maze, are refused this way);
* the pieces that reach into the margins are submitted as one virtual-sprite set (presentation space, art copied from the frame's own VRAM/CRAM, game cell order preserved so overlapping blocks stack as the game stacks them);
* pieces beyond the host's 64 virtual-sprite commands are composited into RGBA overlay layers (one per side, at most 256 x 256 and 65,536 pixels in all) with exactly the hardware sprite pixels; the overlay set is closed under the game's stacking (a sprite the game draws above an overlay piece it overlaps joins the overlay), so the order of overlapping blocks is unchanged. Where the layers cannot hold the pieces the farthest ones are dropped instead (never a fault; not observed on the verified image).

It remembers nothing between frames, so save/load and rewind need no special care, and no game art or table is stored in this repository.

**Exact scope (measured with `abi_parity_compare.py`, local only; aggregates, no frame data):**

* **Complete coverage.** On the recorded special-stage session (585 frames per presentation) the maze is delivered in 464 / 461 / 459 frames at 32:9 / 21:9 / 16:9 and **no eligible block is omitted** (0 of 19,970 / 10,330 / 5,544; before the ROM read 2,109 / 427 / 88). The rest are accounted for: 74 frames of the fade into the stage, where the game's sprite table is not the maze, are refused by the witness (the generic background is served), and 22 / 25 / 27 frames have no block in the margins. The same holds on all six special stages (a quicksave of the level-select screen with the stage number set, one run each at 32:9, 21:9 and 16:9): no block type's mapping is unreadable, the block-position grid is reproduced in every frame, and the only other refusals are the stage-entry fade (73-76 frames per stage) and an isolated single frame here and there where the game's sprite table lags its position buffer by one game frame (at most three per stage and ratio, refused rather than drawn misplaced).
* **Pixel correctness.** Paused special-stage frames are compared with an independent model composed from the frame's own VRAM/CRAM and the maze-free picture: every checked frame is pixel-exact (0 differing pixels), the native 320-pixel picture is identical to the maze-free one, and nothing faults. Verified: the recorded stage (3 frames within the limit and 23 of the 27 over-limit frames, up to 83 pieces), and every stage at 32:9 (4 frames within the limit and up to 6 over-limit frames each, up to 89 pieces seen, 85 verified), 21:9 and 16:9 (2 frames each). The redraw self-test (every reconstructed piece of the blocks the game drew, redrawn whole over the picture) leaves 0 pixels different outside the leading non-maze sprites at nine frames and a deliberately wrong mapping is caught (10,903 pixels).
* **The command limit.** At 32:9 up to 83 pieces are needed (89 in other stages; 27 frames of the recorded session exceed 64, none at 21:9 or 16:9); the pieces beyond the 64 commands are carried exactly by the overlay layers; every over-limit frame that was checked was pixel-exact and none fell back to dropping pieces (the fallback logs nothing, it is covered by the same pixel check).
* **Not measured:** a frame the pause cannot freeze exactly (two of the 27 over-limit frames of the recorded session) is recorded, not hidden; the isolated one-frame lag refusals are visible as a single frame without margin maze; the emerald-collection sequence itself is not played (the emerald and its burst frames are item types of the same tables, 0x3A and 0x42-0x45, whose frames are inside the declared ranges).

## Reproduce the parity comparison (local only; needs the legally held image and a product checkout built at `scripts/PRODUCT_REF`)

```sh
python3 tools/abi_parity_compare.py --product-root <product> --cli <segarecomp> --sdl <sdl3> --cc cc --rom <Sonic 1 image> \
  --abi1 patches/genesis/sonic-1/native-widescreen --abi1-id sonic1-native-widescreen \
  --abi2 patches/genesis/sonic-1/native-widescreen-abi2 --work <dir> --scenario-set s1 \
  --only level,demos,transitions,lifecycle,visual,acts,special,coverage,planes,overflow,fault
```

It prints aggregates only (frame counts and the named mechanisms that differ); there is no tolerance, no skipped frame and no normalisation.
