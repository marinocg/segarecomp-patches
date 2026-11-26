# Sonic 3 & Knuckles (Genesis, lock-on composite): native widescreen as a schema 3 / ABI 2 package (SEG-152-T011)

> The ABI 2 successor of the [Sonic 3 & Knuckles widescreen provider](../native-widescreen/README.md): the same game knowledge, constants and verification logic, the same BPS delta and the same scope (reconstructed scenery of the single-player running levels, the relocated animated HUD), delivered through the exact-frame ABI 2 API (scenery windows, the per-row origin delta of ABI minor 3, the per-row generic mask, one RGBA bitmap, refusal with the ABI 1 reason). The ABI 1 package stays published and unchanged.

**Status: candidate (not approved for release selection).** No release selects it, so it has no catalog entry and no release asset. Its package version `0.1.0` is recorded in [`package.json`](package.json) (identity and SHA-256 from the product's `mod pack` at the revision pinned in `scripts/PRODUCT_REF`).

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Image | the exact 4 MiB Sonic & Knuckles + Sonic 3 lock-on composite, SHA-256 `fba0677fde9f76df93f3e98d6310d8af68b9847bde16e253d73cd4dd8134ed23` (standalone Sonic 3 or Sonic & Knuckles images are different identities). Built as a declared lock-on cartridge: the launcher selects it automatically for this image, a command-line build passes `--mapper lock_on` |
| Package schema / ABI | schema 3, native ABI 2 minor 3 (`abi.minor = 3`: the per-row generic mask of SEG-152-T007 and the per-row scenery origin delta of SEG-152-T017). Trusted native C11 source: executable, **not sandboxed**; the user approves this exact package identity |
| Package identity policy | a **new package id** (`sonic3k-native-widescreen-abi2`), not a new version of `sonic3k-native-widescreen`: the ABI 1 package stays installable and listed beside it (same policy as the Sonic 2 packages of SEG-152-T010) |
| Capabilities | `frame.vdp` (selects the exact-frame `render`), `frame.work_ram`, `overlay.rgba`, `scenery.words`. No guest memory read, no `state.mod` (the provider keeps no state across frames, see below) |
| BPS delta | `bps/game.bps` is byte-for-byte the delta of the published ABI 1 package (source `fba0677f...`, target `8d31e8b6288f0f35304daaa33a8ea7431b514e4cf2f34993594a21b3d44e7c43`, 172 bytes); `[build] header_repair = "none"` keeps the patched image equal to that target |
| Geometry claim | up to 32:9, scene `level` (scenery and HUD) |
| Placement | centred (the ABI 1 presentation): the provider declares no `view_left`. It builds its windows from the margin it learns (`view->side`) and a `left_px` variable (equal to the margin in this baseline), so the adaptive-placement tasks only change how `left_px` is chosen |

## What is carried over, what changes

Unchanged from ABI 1: the work-RAM map, the scope (the campaign zones, single-player; competition, bonus stages and every other screen are declined), the display identity check (64x32 planes, per-line horizontal scroll, full-screen vertical scroll, the scroll the VDP applies equal to the game's own buffer), the layout reconstruction by world coordinates, the background registration (`bg_register` / `bg_line_bad` / `bg_ext_agree`: the layout column a background line shows is the scroll-implied position plus an unknown multiple of 512 px horizontally and 256 px vertically), the foreground identity thresholds, the HUD pieces and the label-frame rule.

Changed (only how the answers are delivered):

* the ABI 1 per-cell callback becomes up to two scenery windows per plane (each at most 128 x 32 cells), built from the frame's own copies for exactly the off-picture cells the host asks;
* **the registered background plane multiple becomes the per-row origin delta.** The host looks plane cell `floor((x - hscroll) / 8) + delta[line]` up. A window is keyed by plane cell, so two lines of one cell row with different multiples would need different words for one cell (the class that blocked Sonic 1, SEG-152-T009). The provider gives every line `delta = 64 * (multiple - smallest multiple of its cell row) + a whole-cell shift per cell row`; both terms are constant inside a cell row apart from the multiple, so they never create a conflict, and they put every cell row's asked cells in the same window columns whatever far-apart world columns the parallax bands are drawn from. Where one window cannot hold the asked cells the provider uses two windows side by side, or two windows stacked by cell rows;
* the lines the ABI 1 provider answered from the VDP's own plane (`own_plane`) become the per-row generic mask;
* the HUD overlay becomes one 112 x 216 RGBA bitmap with the same fallback position; a declined frame is a *refusal* with the ABI 1 diagnostic reason.

A cell asked by two lines that still need different words (a vertical multiple that differs inside a cell row, say) would make the frame unservable and is refused honestly, never answered half-way. None occurred (see the evidence).

## Cross-frame state (ADR 0320 decision 3)

The ABI 1 provider kept one cross-frame item, `g_prev_kx` / `g_prev_ky`, the registered plane multiples of the last presented frame. In the current code `g_prev_ky` is never read across frames, and `g_prev_kx[l]` is read only as a one-point tie-break between candidate multiples that all explain the line equally (the line-to-line carry within one frame is not cross-frame). **Classification: a pure cache within the compared scenes** — the ABI 2 provider clears it by construction (it keeps no state across frames and has no `state.mod`) and reproduces the ABI 1 output frame by frame with the ABI 1 provider's warm cache (evidence below), so clearing it before every presented frame changes nothing, and nothing needs to be maintained across skipped presentation, save/load or rewind (an interrupted run, a restore and a rewind equal an uninterrupted one by construction; the lifecycle runs below confirm it). The evidence covers Angel Island Zone 1 only; for any other zone the claim is unmeasured and a tie that the seed would have broken could differ there (it would show as a verdict or coverage difference in the comparison, none was seen).

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

* **Input.** ONE recorded input session (7,002 guest frames: the intro, the data-select and character menus, then Angel Island Zone 1 played with running and jumping) replayed frame-exactly in the ABI 1 and the ABI 2 program through the viewer's session seam. A host-poll-keyed pad lands a frame differently in two build routes at the level-start edge; the lifecycle runs (which need a scripted pad) use a Start timing for which the unmodified ABI 1 program reproduces its own uninterrupted run.
* **Per-frame equality, five presentation modes (32:9, 21:9, 16:9, Original, exact 4:3):** 7,003 produced frames per mode, 35,015 in total; ABI 2 equals ABI 1 in every mechanism (every ordered verdict occurrence: status, side, placement, accepted components, reason, authored; coverage accounting offered/accepted/presented/rejected for scenery and HUD; the final picture byte for byte; the final guest work RAM): **0 differences**. Scenery was served on 5,854 frames in every mode except Original (which asks for none) and the HUD on 4,746, identically for both ABIs.
* **Aspect transitions** (32:9 -> 21:9 -> 16:9 -> Original -> exact 4:3 -> 32:9) inside the recorded run, run twice: 0 differences and the replay reproduces every verdict.
* **Save/load and rewind through the real viewer:** for each ABI every trace occurrence after the restore equals the uninterrupted run's verdict for its frame number except the one newly produced frame after a restore, and the ABI 2 occurrences equal the ABI 1 run's occurrence by occurrence (load: 2,702 occurrences; rewind: 2,702 occurrences, 12 repeated frame numbers; 0 differences between the ABIs). At that one frame both ABIs serve the scenery without the HUD.
* **Visual checkpoints, pixel for pixel:** 15 intermediate frames (seven representative scenery frames of the run at 32:9, one at each of 21:9, 16:9, Original and 4:3, two eight frames apart, one in the aspect-transition run, one generic scene the provider declines), each the final capture of an ABI 1 and an ABI 2 run of the same input ending on the SAME guest frame: **0 differing pixels** (960 x 672). Liveness is checked (frames eight guest frames apart differ in picture and RAM).
* **Long run, scripted input (30,002 frames at 32:9 and 16:9, ABI 2 instrumented only to count):** the per-frame verdict, accounting and authored status equal ABI 1's on every frame (0 frames differing; picture and RAM are not compared there because a scripted pad is not frame-exact). The bot stayed in Angel Island Zone 1.
* **Answer-representability gate (F31), real-provider measurement over 28,400 produced scenery frames:** frames in which one window cell was asked by two lines needing different words: **0**; frames the windows could not cover (span or rows beyond the capacity, no two-window cover): **0**; frames needing the row origin delta: 28,381; frames needing two windows: 792 (side by side; the stacked cover was never needed); largest window 128 columns, at most 29 cell rows; frames with `own_plane` lines: 9,957, with a cell row that mixes `own_plane` and reconstructed lines: **0** (the generic mask is per screen row, so such a row would be expressible anyway).
* **Cost (class level):** one exact-frame `render` per produced frame. A 7,003-frame run takes 92.8 s with the ABI 2 package against 86.6 s with the ABI 1 package (+0.9 ms per frame, whole-viewer wall clock while other comparison runs shared the machine, so class-level only and well inside the 16.7 ms frame budget at 32:9). Copies: the host's exact-frame view per frame, one 112 x 216 RGBA bitmap (96,768 bytes), at most two windows of 4,096 words per plane.
* **Not exercised on the real image (stated rather than assumed):** every zone and act other than Angel Island Zone 1 (the scripted bot never left it and no level select or save state was available to the harness), Sonic & Knuckles' other characters, competition and bonus stages (declined by the verbatim ABI 1 gates), and attract-mode demos (both ABIs decline them: 0 frames served in either). For the other zones the parity, the cache classification and the window capacity are **unmeasured**; the follow-up is named in the task record.
