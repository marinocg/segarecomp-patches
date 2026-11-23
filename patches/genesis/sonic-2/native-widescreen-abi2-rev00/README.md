# Sonic the Hedgehog 2 (Genesis, World REV00): native widescreen as a schema 3 / ABI 2 package (SEG-152-T010)

> The ABI 2 successor of the [Sonic 2 widescreen provider](../native-widescreen/README.md) for **World REV00** only: the same game knowledge, constants and verification logic, the same BPS delta and the same scope (reconstructed scenery of the single-player running levels and attract demos, the relocated animated HUD), delivered through the exact-frame ABI 2 API (scenery windows, the per-row generic mask, one RGBA bitmap, refusal with the ABI 1 reason). The ABI 1 package of this revision stays published and unchanged.

**Status: candidate (not approved for release selection).** It is not released: no release selects it, so it has no catalog entry and no release asset. Its package version `0.1.0` is recorded in [`package.json`](package.json) (identity and SHA-256 from the product's `mod pack` at the revision pinned in `scripts/PRODUCT_REF`).

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Revision | World REV00 only: original image SHA-256 `07329f4561044a504923eb0742894485c61fc42ebb0891eebff247ca2e086d61` (the other revision is its own project, `native-widescreen-abi2-rev01`, because a `bps-image` payload targets exactly one image) |
| Package schema / ABI | schema 3, native ABI 2 minor 2 (`abi.minor = 2`: the per-row generic mask of SEG-152-T007). Trusted native C11 source: executable, **not sandboxed**; the user approves this exact package identity |
| Package identity policy | a **new package id** (`sonic2-native-widescreen-abi2-rev00`), not a new version of `sonic2-native-widescreen`: the ABI 1 package stays installable and listed beside it, and package ids are unique across the repository. SEG-152-T011 follows the same policy |
| Capabilities | `frame.vdp` (selects the exact-frame `render`), `frame.work_ram`, `overlay.rgba`, `scenery.words`, `memory.read.m68k.work_ram`, `state.mod` |
| BPS delta | `bps/game.bps` is byte-for-byte the delta of the published ABI 1 package (source `07329f4561044a504923eb0742894485c61fc42ebb0891eebff247ca2e086d61`, target `1dc384e493b0ac53424046bcd0acc793ef0fde6427de323f1f047550dbf8ecac`); `[build] header_repair = "none"` keeps the patched image equal to that target |
| Guest memory | six read-only ranges (game mode, level-started flag, split-screen flag, HUD flash phase, ring count, timer minutes) read at `frame-end`. **No guest write** |
| Geometry claim | up to 32:9, scene `level` (scenery and HUD) |
| Placement | centred (the ABI 1 presentation): the provider declares no `view_left`. It builds its windows from the margin it learns (`view->side`) and a `left_px` variable (equal to the margin in this baseline) so the adaptive-placement task only changes how `left_px` is chosen |

## What is carried over, what changes

Unchanged from ABI 1: the work-RAM map, the per-zone background wrap rules, the identity check against the VDP (tolerances, edge bands, at most 32 own-plane lines per plane), the scope (Emerald Hill, Metropolis, Hill Top, Oil Ocean, Mystic Cave, Casino Night, Chemical Plant, Death Egg, Aquatic Ruin, Wing Fortress, Sky Chase; split-screen, special stages and bonus stages are declined), the HUD pieces and the label-frame rule.

Changed (only how the answers are delivered): the ABI 1 per-cell callback becomes up to two scenery windows per plane built from the frame's own copies (a cell asked by two lines that need different words would make the frame unservable and is refused honestly, never answered half-way; none occurred, see the evidence); the lines the ABI 1 provider answered from the VDP's own plane (the last two lines, and lines the identity check found unlike the layout) become the per-row generic mask; the HUD overlay becomes one 104 x 216 RGBA bitmap with the same fallback position; a declined frame is a *refusal* with the ABI 1 diagnostic reason.

## Cross-frame state (ADR 0320 decision 3)

The ABI 1 provider kept two values across frames, both written at presentation time: `g_prev_level` (the HUD is accepted only when the previous produced frame was also a level frame) and `g_hud_frame` (the label frame the game last really built, shown unchanged during the level-restart fade after a death). **Classification: both are essential state, not caches.** Clearing `g_prev_level` before every presented frame declines the HUD on every frame, and clearing `g_hud_frame` loses the held label frame (both are demonstrated by falsification variants in the local comparison; a state dropped on restore also changes the occurrences after a load). They are therefore maintained in the `frame-end` phase (which runs for every guest frame whether or not it is presented) in a four-entry record ring keyed by guest frame number, serialized through `state.mod` (schema 1, 64 bytes), and read at `render` for the guest frame whose end-of-frame RAM is the view's copy. After save/load, rewind and any skipped presentation the provider accepts exactly the frames an uninterrupted run accepts; no frame is conservatively declined by the provider (the host's own `STALE_STATE` for the first newly produced frame after a restore applies to ABI 1 and ABI 2 alike).

## Original image

| Revision | Original image SHA-256 | Patched image SHA-256 (the BPS target) |
|---|---|---|
| World REV00 | `07329f4561044a504923eb0742894485c61fc42ebb0891eebff247ca2e086d61` | `1dc384e493b0ac53424046bcd0acc793ef0fde6427de323f1f047550dbf8ecac` |

You must supply the original image yourself. No game data (ROM bytes, maps, graphics, tables, disassembly, traces, screenshots) is in this repository.

```sh
segarecomp mod check patches/genesis/sonic-2/native-widescreen-abi2-rev00
segarecomp mod build patches/genesis/sonic-2/native-widescreen-abi2-rev00 --out sonic2.segapatch --cc cc --sdk-dir <product>/platforms
```

## Evidence (local, aggregate only)

* **Per-frame equality, five presentation modes (32:9, 21:9, 16:9, Original, exact 4:3), one scripted level run each:** 31,010 produced frames compared in total (6,202 per mode); ABI 2 equals ABI 1 in every mechanism (producer verdict per frame: status, side, placement, accepted components, reason, authored status; coverage accounting offered/accepted/presented/rejected for scenery and HUD; the presented final picture byte for byte; the final guest work RAM): **0 differences**. Scenery was served on 5,029 frames in every mode except Original (which asks for none: 0 in both ABIs) and the HUD on 5,028 frames in every mode, identically for both ABIs.
* **Attract-mode demos (title left idle), 32:9 and 16:9:** 28,010 produced frames, 9,840 scenery frames, 0 differences. Scene classes reached (running level, act 1 each): Aquatic Ruin, Casino Night, Chemical Plant, Emerald Hill (Emerald Hill by the scripted level run, the others by the demos), plus the title, menu and level-start frames the provider declines with the ABI 1 reason.
* **Aspect transitions inside a level (32:9 -> 21:9 -> 16:9 -> Original -> exact 4:3 -> 32:9):** 6,202 frames, 0 differences; the replay of the same run reproduces every verdict and the final picture for both ABIs.
* **Save/load and rewind through the real viewer** (quick save, quick load into a later position, a visual rewind with repeated frame numbers): for each ABI every trace occurrence after the restore equals the uninterrupted run's verdict for its frame number except the single newly produced frame after the restore, which the host reports as `STALE_STATE` for ABI 1 and ABI 2 alike (load: 2,702 occurrences, 1 forward discontinuity; rewind: 2,702 occurrences, 9 repeated frame numbers). The ABI 2 occurrences, final pictures and final RAM equal the ABI 1 run's occurrence by occurrence, so no frame that an uninterrupted run presents is conservatively declined after a restore.
* **Falsification (each variant of the real ABI 2 source must FAIL the same comparison):** a wrong frame lag fails on accepted-components, coverage-accounting; `g_prev_level` cleared before every presented frame fails on accepted-components, coverage-accounting, picture; the held label frame cleared fails on picture (so the classification of both values as essential state is demonstrated, not asserted); the maintained state dropped on restore changes the occurrences after a load; an injected range fault (an oversized bitmap layer) fails on accepted-components, authored, coverage-accounting, picture, reason.
* **Injected fault:** exactly 1 `E_MOD_FAULT cause=range` disables the provider; the presented frame and the guest RAM equal those of the BPS-patched image with no provider at all (picture equal: True, RAM equal: True); the fault never touches the guest.
* **Cost (class level):** one exact-frame `render` and one `frame-end` per produced frame. A 6,202-frame level run takes 81.5 s with the ABI 2 package against 75.8 s with the ABI 1 package (+5.7 s, about +0.92 ms per frame; whole-viewer wall clock measured while other comparison runs shared the machine, so class-level only and inside the 16.7 ms frame budget by an order of magnitude). Copies: the host's exact-frame view is 188,416 bytes per frame (SEG-152-T008); the provider adds one 104 x 216 RGBA bitmap (89,856 bytes) and at most four windows of 4,096 words.
* **Scenery gate (SEG-152-T001/T007):** no frame of any compared scene asked one plane cell with two different answers; the own-plane lines of the ABI 1 provider are expressed with the per-row generic mask (the same `authored` and coverage accounting as ABI 1, zero pixel-row differences). The conflict class that blocks Sonic 1 (SEG-152-T009) did not occur in any compared frame of these scenes (a conflicting frame would have been refused and shown up as an accepted-component difference).
* **Not exercisable on the real image, stated rather than assumed:** split-screen (two-player), special-stage and bonus-stage frames, and frames at a width other than 320 px. Their declines are the verbatim ABI 1 gates (`hud_state`, `level_mode`, `width != 320`) ported unchanged; the title, menu and level-start frames that the scripted runs do reach are declined with the ABI 1 reason in both ABIs.

Reproduce with `tools/abi_parity_compare.py` (needs the legally held image and a product checkout; it prints counts and pass/fail classes only and writes nothing commercial anywhere). Public CI cannot run it and does not depend on it; the repository checks (`check_repo.py`, the catalog check, the unit tests, a deterministic rebuild of the package with the pinned product CLI) are what CI runs.
