# Castle of Illusion Starring Mickey Mouse (Genesis): authored widescreen + Practice+

> One schema 3 / native ABI 2 mod. **Widescreen:** in two verified scrolling scenes the cells beside the 320-pixel picture are rebuilt from the game's own block maps instead of repeating the wrapped VDP plane. **Practice+:** pressing A+B+C together restores Mickey's power to full, only in the verified scenes, only when it is 1 to 4.

**Status: unpublished source (SEG-149-T002 and SEG-149-T003, delivery W04, awaiting human review).** There is no `release.json`, no catalog entry and no release asset. Check, pack and build it locally with the product's `segarecomp mod` tools; nothing here has been released.

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Revision | the one image below (USA, Europe), 524,288 bytes. A title, region or file name is never an identity |
| Package schema / ABI | schema 3, native ABI 2. Trusted native C11 source: executable, **not sandboxed**; the user approves this exact package identity |
| Capabilities | `input.intercept`, `input.read`, `memory.read.m68k.work_ram`, `memory.write.m68k.work_ram`, `overlay.rgba`, `scenery.words`, `state.mod` |
| Guest memory | reads: the block tables, both maps, the scroll records (`mod.toml`). **Writes: only Practice+, three declared ranges** (power word, five HUD slot words, one HUD flag byte) |
| Geometry claim | up to 32:9 (see "Coverage" for what is really delivered) |

| Original image | SHA-256 |
|---|---|
| Castle of Illusion Starring Mickey Mouse (USA, Europe) | `2d535ff7eda650a64a9093ba6fabf8d5ac87801b898a76b591db41a1c8e47c4f` |

You must supply the original image yourself. No game data (ROM bytes, maps, graphics, tables, disassembly, traces, screenshots) is in this repository.

```sh
segarecomp mod check patches/genesis/castle-of-illusion
segarecomp mod build patches/genesis/castle-of-illusion --out castle.segapatch --cc cc --sdk-dir <product>/platforms
```

## Widescreen: how it works

The game keeps, for each of its two scrolling planes, a small record in work RAM (the scroll values, the address and size of a byte map of 16 x 16 pixel blocks, and the address of the table that expands a block to four VDP name-table words). The provider reads those records and maps through the ABI 2 memory service at `frame-end`, rebuilds the name-table words of the cells around the camera for both planes, and submits them as the typed authored `scenery_window` at `render`. The host's own VDP code decodes patterns and palettes; the provider never touches VRAM and invents no tile (a cell outside a map is the game's own empty block). The cartridge is never read at run time and nothing from it is embedded here. The picture inside the original 320 x 224 is Vanilla's.

A scene is accepted only when the records have exactly the verified shape of a running level (the addresses of both maps and both tables, and the map sizes of one of the scenes below). A menu, cutscene, level load, any other level or any other layout is declined and the host presents its generic extension for that frame. Windows are a pure function of the world cell (rows outside a map are the game's own empty block, as the VDP planes hold them) and cover 40 cells to the left and 88 to the right of the camera, which absorbs the camera's motion between the `frame-end` read and the frame that is produced two guest frames later.

## Verified scenes

The game's stage loader reads a level index and a sub-stage index; the stage table has 4 reachable levels with up to 6 sub-stages each. A **private, uncommitted debug build** (a local runtime copy with an environment-driven seam that pokes the two stage words before the loader runs, and a "float" mode that moves Mickey with the d-pad while neutralising gravity, collisions and damage) was used to enter and fly through every stage instead of trusting the attract demo. For each stage that has the shape below, 60 samples along a scripted flight (right, down, right, left) were compared with the VDP: every on-screen cell of both planes equalled the game's own VRAM word (about 134,000 cells per stage, no mismatch), and a modded run at 32:9 over the same flight had no unanswered margin cell outside the first few frames of the level.

A scene is a map shape (plane A rows x columns, plane B rows and its row stride); it is named by that shape because several stages share one.

| Scene | Plane A map | Plane B map | Stages (level, sub-stage) where verified |
|---|---|---|---|
| `a16x240-b16` | 16 x 240 | 16 x 32 | (0,0) first level, played normally and flown |
| `a48x160-b16` | 48 x 160 | 16 x 32 | (0,2), (0,4) |
| `a48x128-b48` | 48 x 128 | 48 x 32 | (0,3) |
| `a16x32-b16` | 16 x 32 | 16 x 32 | (0,5) |
| `a192x48-b192` | 192 x 48 (vertical) | 192 x 32 | (1,0) |
| `a32x112-b32` | 32 x 112 | 32 x 32 | (1,1), also the attract demo |
| `a14x320-b14` | 14 x 320 | 14 x 32 | (1,2) |
| `a17x32-b17` | 17 x 32 | 17 x 32 | (1,3) |
| `a80x80-b80x80` | 80 x 80 | 80 x 80 | (3,0) to (3,4) |
| `a32x128-b32x128` | 32 x 128 | 32 x 128 | (4,1) |
| `a96x64-b96` | 96 x 64 | 96 x 32 | (4,2) |

**Found but not supported (declined, shown by the host's generic extension):** stages that scroll plane B (or A) in bands, whose per-band scroll is not in the records the provider reads, namely (0,1), (2,0), (2,1), (2,3); stages (2,2) and (3,5), whose records do not follow the verified layout in flight; any stage not listed. Stage indices above 4 do not load a level. The first sub-stage of level 4 and the other stages reached by the attract loop were covered as far as the table shows; **boss arenas and cutscenes not named here were not examined individually**, so "every level" is not claimed: the claim is exactly the table above.

## Coverage (local runs on the exact image, aggregates only)

Method: the generated-native viewer program of the original image, built through `segarecomp build --native-package`, played under the dummy video driver with finite instruction budgets and a scripted pad, compared with the Vanilla program of the same image at the same budget; the viewer's own `SEGARECOMP_COVERAGE_REPORT` supplies the per-scene accounting.

| Scene | 4:3 | 16:9 | 21:9 | 32:9 |
|---|---|---|---|---|
| `a16x240-b16`, `a32x112-b32` (played, compared with Vanilla at every aspect) | identical to Vanilla; nothing requested | served; 0 pixels differ inside the picture | served; 0 inside | served; 0 inside |
| the other nine scenes (flown, modded run at 32:9 only) | not run | not run | not run | served in every frame except the first ~7 of each level start; no fault |

* **The first frames of a level are not served** (the VDP scroll registers are still being set; about five frames per level start) and the host presents the generic extension there. Frames of motion, jumps and the camera stopping at a wall had no unanswered cell in either scene (every other frame of the runs was served).
* **Where the generic extension already agrees, the output equals it**: at 16:9 only the Practice+ panel differs from Vanilla; at 21:9 and 32:9 the margins beyond what the game itself keeps in VRAM now show the true level (the generic extension repeats the wrapped plane, which is visibly wrong there, for example a platform edge repeated on the other side of Mickey).
* **Credit limitation (host rule, not a defect of the data):** the game draws its status bar with the VDP window plane on the bottom four cell rows. The host never credits "authored scenery" on a frame whose window plane owns a picture edge, so the report counts the scenery of every frame as `requested` and `missing` (0 covered) even though the rows above the status bar are served from the authored window. The status-bar rows beside the picture stay the host's generic presentation (plane A omitted there).
* **Not delivered:** virtual sprites (an actor beside the picture is clipped at the picture edge, as in Vanilla: no actor identity, world position and artwork were established), a relocated or enlarged HUD (the original status bar is left where it is), widescreen at any aspect in an unverified scene.
* **Evidence of the scenery itself** (independent of the provider): in 103 frames sampled across the first two scenes, 230,720 of 230,720 on-screen cells of both planes equal the name-table words the game itself had written into VRAM (no mismatch); cells beyond the screen that the game had already streamed agree too (84,633 equal, 543 stale because the game had not rewritten them yet).

## Practice+

| | |
|---|---|
| Gesture | **A + B + C together** on controller 1 (Start is never used). One restoration per press: holding the chord does nothing more, and a chord that was already down when a level started never fires later. **While a verified level runs the complete chord is taken away from what the game reads** (`input.intercept`), so Practice+ never makes Mickey jump or attack; buttons that arrive a frame before the chord is complete still reach the game, and nothing is intercepted outside the two scenes |
| Where | only in the verified scenes (the same records and map shapes as the widescreen check, read again at the moment of the press). The chord is Practice+'s there even at full power, where it does nothing |
| When | only while Mickey's power is 1 to 4. At 0 (dead) or at 5 (full) nothing is written |
| Effect | power (work RAM `0xF322`) becomes 5, the five HUD slot words (`0xF244`..`0xF24D`) and the HUD upload flag (bit 0 of `0xF409`) are set exactly as the game's own heal routine leaves them, so the on-screen power row updates. Seven staged writes, three declared read-write ranges. Lives, items, score and everything else are untouched |
| Why these facts | power runs 0..5 (the game's own routines cap it at 5 and its HUD has five slots; observed: a value above 5 written into RAM is brought back to 5 by the game); a direct write to the power word alone leaves the HUD stale until the next game event, which is why the HUD words and flag are written too. No function hook was needed |
| Indicator | a small "P+" panel (with the number of restorations and a "POWER" notice for 1.5 seconds after one) in the HUD layer. **It is a widescreen HUD layer: the host presents it at 16:9 and wider, not at 4:3**, where Practice+ still works but shows no panel |
| State | the previous chord state, the counter and the notice timer are in the mod state: save states, rewind and replay reproduce them |

**Practice+ changes the game** (it is a practice aid, not a presentation effect) and it is the only part of this package that does. Widescreen alone never writes guest memory.

## What was verified (local, real image) and what was not

Verified: exact-image build through the launcher flow (install, approval, select, build, play, return to Vanilla, an unapproved or a tampered package refused, own cache and save identities, Vanilla untouched); an unrelated or partial chord (A with Right) is identical to Vanilla in a bounded Vanilla-versus-Modded run (no divergence, no write); pressing the chord on the title screen is identical to Vanilla too; with the chord in a verified level the first divergence from Vanilla is the next frame; of the watched guest bytes, the power byte (2 to 5) and the three HUD slot bytes that were empty carry the restoration, and the only other differing bytes are Mickey's own state words, which react to the chord in Vanilla (the modded game never sees it); the modded picture after a restoration differs from Vanilla's (same Right input, no chord) only inside the power row of the status bar, while Vanilla given the chord changes the whole picture (Mickey acts), which shows the chord never reaches the game; the chord held for 100 frames and pressed again at full power commits exactly one restoration (seven writes); replay of identical input reproduces the frame, the guest RAM and the write and overlay accounting; a quick save taken after a restoration is restored by a new process (power 5 and the mod's panel); a scripted rewind is accepted; no fault in any run.

Not verified: audio output after a restoration (no confound-free comparison was made); Practice+ in stages other than (0,0) and the castle demo stage (it uses the same checks, but only those were played with the chord); any stage not in the table; the title, menus, boss fights and cutscenes (they are declined, not tested for visual quality); behaviour when power is changed by pickups while a chord is held; invulnerability or other transitional states beyond "power 1 to 4 in a verified level"; other regions or revisions of the game.

Synthetic public tests (no game data): `tests/test_castle_provider.py` compiles the provider against the product's ABI 2 header with a mock host over fabricated RAM and checks the window against an independent construction (including the VDP's 10-bit scroll wrap), every decline case, the exact seven writes, edge triggering, the fixed/dead/unverified cases, declared ranges only, and the state round trip. It needs `SEGARECOMP_SDK_DIR`; the real-game evidence above can only be produced locally.
