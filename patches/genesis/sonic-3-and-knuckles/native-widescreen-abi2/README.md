# Sonic 3 & Knuckles (Genesis, lock-on composite): native widescreen as a schema 3 / ABI 2 package (SEG-152-T011, adaptive placement SEG-152-T016)

> The ABI 2 successor of the [Sonic 3 & Knuckles widescreen provider](../native-widescreen/README.md): the same game knowledge, constants and verification logic, the same BPS delta and the same scope (reconstructed scenery of the single-player running levels, the relocated animated HUD), delivered through the exact-frame ABI 2 API (scenery windows, the per-row origin delta of ABI minor 3, the per-row generic mask, one RGBA bitmap, refusal with the ABI 1 reason). The ABI 1 package stays published and unchanged.

**Status: candidate (not approved for release selection).** No release selects it, so it has no catalog entry and no release asset. Its package version `0.2.0` is recorded in [`package.json`](package.json) (identity and SHA-256 from the product's `mod pack` at the revision pinned in `scripts/PRODUCT_REF`).

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Image | the exact 4 MiB Sonic & Knuckles + Sonic 3 lock-on composite, SHA-256 `fba0677fde9f76df93f3e98d6310d8af68b9847bde16e253d73cd4dd8134ed23` (standalone Sonic 3 or Sonic & Knuckles images are different identities). Built as a declared lock-on cartridge: the launcher selects it automatically for this image, a command-line build passes `--mapper lock_on` |
| Package schema / ABI | schema 3, native ABI 2 minor 3 (`abi.minor = 3`: the per-row generic mask of SEG-152-T007 and the per-row scenery origin delta of SEG-152-T017). Trusted native C11 source: executable, **not sandboxed**; the user approves this exact package identity |
| Package identity policy | a **new package id** (`sonic3k-native-widescreen-abi2`), not a new version of `sonic3k-native-widescreen`: the ABI 1 package stays installable and listed beside it (same policy as the Sonic 2 packages of SEG-152-T010) |
| Capabilities | `frame.vdp` (selects the exact-frame `render`), `frame.work_ram`, `overlay.rgba`, `scenery.words`, `state.mod` (448 bytes, schema 1: the registered plane multiples of the last produced frame). No guest memory read |
| BPS delta | `bps/game.bps` is byte-for-byte the delta of the published ABI 1 package (source `fba0677f...`, target `8d31e8b6288f0f35304daaa33a8ea7431b514e4cf2f34993594a21b3d44e7c43`, 172 bytes); `[build] header_repair = "none"` keeps the patched image equal to that target |
| Geometry claim | up to 32:9, scene `level` (scenery and HUD) |
| Placement | adaptive in 4 scenes, centred in the other 24 (`view_left`, ADR 0315): see [Adaptive placement](#adaptive-placement-seg-152-t016). Original and 4:3 stay centred. Compiled with `S3K_PLACEMENT 0` the provider is the centred SEG-152-T011 baseline |

## Adaptive placement (SEG-152-T016)

`left_px` (the columns of the planned `2 * margin` that lie left of the native picture) is a **pure function of the camera and the act's layout width**, with no placement state: 0 at camera 0, `margin` in the middle, `2 * margin` where the camera reaches the layout's end minus 320. It ramps over `6 * margin` pixels of camera travel at each end (`RAMP_DEN` 6, the shape of the Castle of Illusion package), so while the camera scrolls it moves at most 1/6 as fast. A range narrower than `2 * margin` uses the plain rule (picture at the left until the camera is `margin` in); no shifting scene is that narrow.

* **Right boundary = the layout's end, not the game's camera limit.** The game's right limit is often a default far past the layout until an event locks the camera, and a placement computed from it would jump when it changes. The layout width is constant for the act: the view never passes the end of the layout.
* **Partial right alignment.** Where the game's own right limit lies `D` pixels before the layout's end, the picture there is short of `2 * margin` by `D / 6` pixels, and is centred once `D >= 6 * margin` (234 px at 16:9, 606 at 21:9, 1428 at 32:9).
* **Declared on every frame of a shifting scene,** also on frames whose scenery the identity checks decline (the host then extends them generically). Declaring it only with authored scenery recentred the picture for single frames (a jump of up to 238 px, found and fixed during this task). Frames the provider refuses wholly while a level loads (title card) are centred by the host.
* **Background registration** samples the actual extension: the baseline's sample budget, split between the left and right sides in proportion to the placement (identical to the baseline when centred).

### Which scenes shift

A scene shifts only if the local recordings support all of: (1) the game's left limit is 0 in the act's first level frames; (2) a left-to-right run reaches a right limit **the game itself sets** (camera held at it for 60 frames or more) less than 1428 px before the layout's end; (3) no recorded camera loop, act boundary or exit camera reset steps the picture, or leaves it unshown that it would not. Eligibility for authored scenery does not imply eligibility for placement. Everything else keeps its scenery and HUD with the picture centred.

**Shifting (4).** One run per scene, from its first level frame to the camera first held at that limit, no frame gaps; `left_px` at the start (32:9), then at the limit for 32:9 / 21:9 / 16:9 (full right would be 476 / 202 / 78). The centred value is reached in every run.

| Scene | First camera x -> `left_px` at 32:9 | `D` (px) | `left_px` at the game's limit | Frames | Largest step |
|---|---|---|---|---|---|
| Sandopolis 1 | 32 -> 5 | 176 | 447 / 173 / 49 | 1,603 | 3 |
| Marble Garden 1 | 32 -> 5 | 192 | 444 / 170 / 46 | 1,194 | 32, at a camera jump |
| Death Egg 2 | 160 -> 26 | 480 | 396 / 122 / 39 (centred) | 1,346 | 3 |
| Marble Garden 2 | 0 -> 0 | 576 | 380 / 106 / 39 (centred) | 1,858 | 96 (32:9), at a camera jump |

**No shifting scene reaches full right alignment at the game's own limit.** (Marble Garden 2 reaches `2 * margin` only where the debug flight passed that limit.) The camera jumps in the two Marble Garden runs, and later recorded jumps in Sandopolis 1 (67 px of placement) and Death Egg 2 (37 px), come with a visible jump of the **centred** picture (frames before and after compared by eye). They were recorded in debug flights; their cause, and whether normal play makes them, was not established.

**Centred (24):**

| Cause | Scenes |
|---|---|
| Not a left-to-right level traversal: camera static, or script-driven (minimum = maximum = camera, or an automatic scroll) | Sky Sanctuary 2, The Doomsday, Lava Reef boss act, Death Egg final boss |
| No right limit set by the game was observed (the debug flight passed the layout's end at the default limit): right boundary not verified | Hydrocity 1 and 2, Carnival Night 1 and 2, IceCap 1, Launch Base 2, Sandopolis 2, Death Egg 1 |
| The only game right limit observed is 1,428 px or more before the layout's end (5,216 / 2,824 / 5,080 / 2,608 px): the layout's end is not shown to be where the camera ends, and the picture would be centred there even at 32:9 | Flying Battery 1 and 2, Launch Base 1, Mushroom Hill 2 |
| The camera barely moved in the recordings: behaviour not verified | IceCap 2 (one 992 px stretch entered from act 1; static in its own flight), Mushroom Hill 1 (862 px) |
| **Hidden camera loop** that steps the picture: the camera wraps back 508 px while the scenery repeats (the wrap matches at the ordinary scroll offset), and in the ramp this moves the picture 46 px at 32:9 | Angel Island 2 |
| **Seamless exit that steps the picture:** act 1 becomes act 2 under a continuous full-screen fire cover (captured before and after, HUD up, no fade) while the camera is rebased from 12048 to 16; adaptive placement moved the picture 466 px at 32:9 in that frame (the player sprite is not in these debug captures) | Angel Island 1 |
| **Exit flash:** at the exit the camera reads 0 for one frame whose picture is identical to the next frame's (camera 11264), so the placement would go 476 -> 0 -> 444 (32:9) | Lava Reef 1 |
| **Exit not shown to be harmless:** at the game's limit the camera is reset to 0 while the level stays on screen (HUD up, no fade; about 470 px of placement at 32:9). The centred picture changes at the reset, and the generated program stops (the recorded product limit) before the exit can be seen to finish | Sky Sanctuary 1, Hidden Palace |
| The game's left limit at the start is not 0: the act begins at camera 2368, where this placement is centred and cannot give the left value at the first camera position (its right end matched the game's limit exactly) | Lava Reef 2 |

Several centred causes are limits of the **evidence**, not shown faults. More recordings could move scenes into the shifting list.

**Visible step at level start (all four shifting scenes).** While a level loads, its zone title card is shown centred: the layout is not loaded yet, so there is no placement to compute. On the first frame with a layout the card and the picture move to the start position (captured against the centred build on the same frame for Marble Garden 2, 238 px at 32:9, and Sandopolis 1, 233 px: the centred card does not move; Marble Garden 1 and Death Egg 2 make the same kind of step, 233 and 212 px). A function of the current frame alone cannot avoid it.

**Act exits of the shifting scenes: not captured.** They were attempted with a local test variant that writes the game's own "last hit" state to hittable objects at the arena (test ROM and variant only; this package writes no guest memory), then continued with scripted input:

| Scene | How far the attempt got |
|---|---|
| Marble Garden 1 | Boss defeated, the act results screen, the camera limit reopens. The act never changed to act 2 (walking on was a fatal fall, debug flight reached the default limit). Over the results and the reopening, the placement made no step above 4 px |
| Marble Garden 2 | One boss phase defeated; no exit |
| Sandopolis 1 | The guardian has no hit counter; no exit |
| Death Egg 2 | No hittable object appeared; no exit |

**No exit break was observed, and no exit was verified.** All five act exits recorded elsewhere (Angel Island 1, IceCap 1, Lava Reef 1, Sky Sanctuary 1, Hidden Palace) reset the camera without leaving the running-level mode; if a shifting scene's exit does the same, the picture steps there. The entries into Marble Garden 2 and Death Egg 2 from the previous act were not recorded.

**Other camera resets in the four scenes.** Death restarts recorded in Marble Garden 1 and Sandopolis 1 move the placement back to centred while the picture is completely black, with and without placement. The in-play camera jumps recorded in debug flights are described above (the centred picture jumps there too). The 60-frame holds are not proof that a limit is the act's final one, and normal play-throughs were not recorded.

### Placement evidence (local, aggregate only)

Same local test image and debug-fly method as the zone sweep below, with a logging-only variant of the provider.

* **Function:** with placement enabled in all 24 traversal scenes (the build before this classification), 28 scenes x 32:9, 21:9, 16:9 (84 runs): the declared placement equals an independent re-implementation on every level frame with a host verdict except 168 wholly refused level-load frames (centred).
* **This build against those recordings, 84 runs / 553,401 frames:** all 89,256 frames of the 4 shifting scenes are identical to that build; all 464,145 other frames are identical to the SEG-152-T011 provider. The guest-state log and coverage accounting equal T011 and the final work RAM equals the centred build's.
* **Baseline:** with `S3K_PLACEMENT 0` every verdict, the coverage accounting, the guest-state log, the final picture and the final work RAM are identical to the T011 provider (84 runs).
* **Pixels:** 18 captures (Marble Garden 2, Lava Reef 1, Hydrocity 2, Launch Base 2; left, ramp, centred, right) compared with the centred build on the same frame: **0 differing pixels** in the world columns both show (the HUD's screen area excluded). Of these only Marble Garden 2 still shifts; the other captures remain evidence for the window builder. Seen by eye (two captures): at the level start and the layout end the shifted view shows authored scenery where the centred one shows cells outside the level; the HUD keeps its place. The provider submits no virtual sprites.
* **Lifecycle** (Marble Garden 2 and Lava Reef 1, all three ratios, run while both shifted): quick save/load and rewind near both ends: 0 placement mismatches. Reversal flights (7 to 9 camera direction changes): 0 mismatches, maximum step 3, never against the camera. Aspect changes 21:9, 16:9, Original, 4:3, 32:9 mid-level: every extended frame matches the function for its own margin, Original and 4:3 are centred, the run repeats exactly and ends with the uninterrupted run's work RAM.
* **Parallax:** background factors measured at 32:9 from the game's per-line scroll buffer (14 sampled lines, the median over 60-frame windows of steady scrolling, per scene) all lie in 0..1, so the drift of a background layer against the foreground during a ramp is at most `(1 - k) / 6` <= 0.167 of the camera's speed.
* **Bounds:** `tests/test_sonic3k_placement.py` checks the exact scene list over every zone and act byte, and runs the placement and the window builder for three margins and three placements under AddressSanitizer and UBSan on **fabricated** work RAM. The real-image runs were not sanitizer builds.

## What is carried over, what changes

Unchanged from ABI 1: the work-RAM map, the scope (the campaign zones, single-player; competition, bonus stages and every other screen are declined), the display identity check (64x32 planes, per-line horizontal scroll, full-screen vertical scroll, the scroll the VDP applies equal to the game's own buffer), the layout reconstruction by world coordinates, the background registration (`bg_register` / `bg_line_bad` / `bg_ext_agree`: the layout column a background line shows is the scroll-implied position plus an unknown multiple of 512 px horizontally and 256 px vertically), the foreground identity thresholds, the HUD pieces and the label-frame rule.

Changed (only how the answers are delivered):

* the ABI 1 per-cell callback becomes up to two scenery windows per plane (each at most 128 x 32 cells), built from the frame's own copies for exactly the off-picture cells the host asks;
* **the per-line world origin becomes the per-row origin delta plus a group placement.** The host looks plane cell `floor((x - hscroll) / 8) + delta[line]` up and a window is keyed by that cell, so two lines of one cell row that need different words for one cell (the registered background plane multiple differs between parallax bands, the class that blocked Sonic 1, SEG-152-T009) cannot share a place. The provider groups the lines of each cell row by their plane-to-world mapping (multiples and scroll wrap) and gives every group its own whole-cell shift: its natural place (64 cells per 512 px multiple, relative to the row's smallest multiple, plus the row's scroll cell) when that is free, otherwise the nearest free place; cell rows are independent. All answers live in one run of 256 window columns (two windows of 128 columns, at most 32 cell rows), so the cover is exact whatever the bands do. A frame that does not fit is refused honestly, never answered half-way;
* the lines the ABI 1 provider answered from the VDP's own plane (`own_plane`) become the per-row generic mask;
* the HUD overlay becomes one 112 x 216 RGBA bitmap with the same fallback position; a declined frame is a *refusal* with the ABI 1 diagnostic reason.


## Cross-frame state (ADR 0320 decision 3)

The ABI 1 provider kept one cross-frame item, `g_prev_kx` / `g_prev_ky`: the registered plane multiples of the last presented frame, used as a one-point tie-break between candidate multiples that equally explain a line. **Classification: essential state, not a cache.** The test of the decision (clearing it before every frame must reproduce the ABI 1 output) *failed*: the first ABI 2 build, which cleared it, differed from ABI 1 on two frames of Carnival Night Zone Act 1 in the local comparison, and reproduced ABI 1 exactly once the seed was kept. The seed is therefore maintained by `render` exactly as ABI 1 maintained it and serialized through `state.mod` (448 bytes: one byte per line for each plane multiple, schema 1, range-checked on load), so save/load and rewind restore the seed of the saved moment; the lifecycle runs below confirm that frames after a restore equal an uninterrupted run. Like the ABI 1 provider it is updated only by frames that are produced, so a presentation that skips frames changes the seed in the same way it did in ABI 1: an ABI 1 behaviour that is itself presentation-dependent. **Design decision (SEG-152-T011): ABI 1 behaviour is preserved and the operator accepts this limitation**; no guest-frame state update and no new product mechanism is introduced to remove it (the deterministic alternative would need the frame view outside `render`).

## Original image

| Image | Original SHA-256 | Patched image SHA-256 (the BPS target) |
|---|---|---|
| lock-on composite (4 MiB) | `fba0677fde9f76df93f3e98d6310d8af68b9847bde16e253d73cd4dd8134ed23` | `8d31e8b6288f0f35304daaa33a8ea7431b514e4cf2f34993594a21b3d44e7c43` |

You must supply the original image yourself. No game data (ROM bytes, maps, graphics, tables, disassembly, traces, screenshots) is in this repository.

```sh
segarecomp mod check patches/genesis/sonic-3-and-knuckles/native-widescreen-abi2
segarecomp mod build patches/genesis/sonic-3-and-knuckles/native-widescreen-abi2 --out sonic3k.segapatch --cc cc --sdk-dir <product>/platforms
```

## Evidence (local, aggregate only)

Reproduce with `tools/abi_parity_compare.py --scenario-set s3 --mapper lock_on` (needs the legally held image and a product checkout; it prints counts and pass/fail classes only and writes nothing commercial anywhere). Public CI cannot run it and does not depend on it.

**Every zone and act of the ABI 1 scope was compared.** The scripted route of a player cannot leave Angel Island Zone 1, so the sweep uses a **local test image** derived from the legally held one (never committed or redistributed; it enables a level select and the game's debug fly through a few instructions, its BPS delta and package identity are re-derived and the provider source is the unmodified one): each scene is recorded with the ABI 1 program (the debug fly crosses the level) and replayed frame-exactly in the ABI 1 and the ABI 2 program, at 32:9 and 16:9.

* **Zone sweep:** all 28 scene classes of the ABI 1 scope (Angel Island, Hydrocity, Marble Garden, Carnival Night, Flying Battery, IceCap, Launch Base, Mushroom Hill, Sandopolis, Lava Reef, Sky Sanctuary and Death Egg, acts 1 and 2; The Doomsday; the Lava Reef boss act and Hidden Palace; the Death Egg final-boss act): 56 runs, 255,968 produced frames, 144,920 with authored scenery and 181,138 with the HUD, **0 differences** in every mechanism (every ordered verdict occurrence, accounting, authored status, the final picture byte for byte and the final guest RAM). Seven scenes (Flying Battery 1, Lava Reef 1 and 2, Sky Sanctuary 1 and 2, The Doomsday, Hidden Palace) stop the *generated program itself* (a guest stop of the ABI 1 build, in the product's runtime, outside any provider) a few thousand frames into the fly, so their recordings end shortly before that stop (the Sky Sanctuary act 2 scene stops during its load and contributes 159 scenery frames). These are accepted, documented limits and product findings, not provider results.
* **What the sweep found and fixed (the representability gate of the F31 note, measured on the real provider):** the first cover algorithm (two windows over the bounding span) refused 439 of 1,393 scenery frames of Hydrocity Zone 1 at 32:9 (54 at 16:9): a cell row in which some lines scroll their background band by hundreds of pixels more than the rest asks three or four clusters of cells that two windows cannot span. That is not a conflict (0 conflicting window cells in every scene) but a capacity limit; the group placement above removes it (every compared frame is then served exactly as ABI 1 serves it). The same sweep showed that the previous-frame seed is essential state (Carnival Night Zone Act 1, two frames), see above.
* **Per-frame equality on the unmodified image, five presentation modes (32:9, 21:9, 16:9, Original, exact 4:3):** the recorded Angel Island Zone 1 run, 7,003 produced frames per mode (35,015 in total), **0 differences**; scenery served on 5,854 frames in every mode except Original (which asks for none) and the HUD on 4,746, identically for both ABIs. Aspect transitions (32:9 -> 21:9 -> 16:9 -> Original -> exact 4:3 -> 32:9) twice: 0 differences and the replay reproduces every verdict.
* **Save/load and rewind through the real viewer:** for each ABI every occurrence after the restore equals the uninterrupted run's verdict for its frame number except the one newly produced frame after a restore (scenery without the HUD, the same in both ABIs), and the ABI 2 occurrences equal the ABI 1 run's occurrence by occurrence (load: 2,702 occurrences; rewind: 2,702 occurrences, 12 repeated frame numbers; 0 differences between the ABIs). The restored seed is exercised by these runs and by the zone sweep's frame-exact replays.
* **Visual checkpoints, pixel for pixel:** 15 intermediate frames (seven representative scenery frames at 32:9, one at each of 21:9, 16:9, Original and 4:3, two eight frames apart, one in the aspect-transition run, one generic scene the provider declines), each the final capture of an ABI 1 and an ABI 2 run of the same input ending on the SAME guest frame: **0 differing pixels** (960 x 672). Liveness is checked.
* **Falsification:** the variant of this provider that cleared the previous-frame seed before every frame (the first ABI 2 build) differs from ABI 1 on two frames of Carnival Night Zone 1; the variant with the two-window bounding-span cover differs on Hydrocity Zone 1 (439 frames at 32:9) and on one Angel Island frame of the sweep route.
* **Cost (class level):** one exact-frame `render` per produced frame. A 7,003-frame run takes 93.8 s with the ABI 2 package against 87.4 s with the ABI 1 package (+0.9 ms per frame, whole-viewer wall clock while other comparison runs shared the machine, so class-level only and well inside the 16.7 ms frame budget at 32:9). Copies: the host's exact-frame view per frame, one 112 x 216 RGBA bitmap (96,768 bytes), at most two windows of 4,096 words per plane.
* **Not exercised on the real image (stated rather than assumed):** the other playable characters' start sequences beyond the one the scripts select, the competition mode and bonus stages (declined by the verbatim ABI 1 gates), the attract-mode demos (both ABIs decline them: 0 frames served in either), and the parts of the levels the debug fly did not cross (flights are a few thousand frames, not whole levels; the seven stopped scenes are shorter).
