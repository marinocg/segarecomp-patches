# Castle of Illusion Starring Mickey Mouse (Genesis): authored widescreen

> A schema 3 / native ABI 2 source project: the cells beside the 320-pixel picture of two verified scrolling scenes are rebuilt from the game's own block maps instead of being a repeat of the wrapped VDP plane.

**Status: unpublished source (work in progress, SEG-149-T002 and SEG-149-T003, delivery W04).** There is no `release.json`, no catalog entry and no release asset. You can check, pack and build it locally with the product's `segarecomp mod` tools.

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Revision | the exact image below (USA, Europe), 524,288 bytes. A title, region or file name is never an identity |
| Package schema / ABI | schema 3, native ABI 2 (trusted native C11 source: executable, **not sandboxed**; the user approves this exact package identity) |
| Capabilities | `memory.read.m68k.work_ram`, `overlay.rgba`, `scenery.words`, `state.mod` |
| Guest memory | read only: four declared work-RAM ranges (see `mod.toml`). Nothing is written in this step |

| Original image | SHA-256 |
|---|---|
| Castle of Illusion Starring Mickey Mouse (USA, Europe) | `2d535ff7eda650a64a9093ba6fabf8d5ac87801b898a76b591db41a1c8e47c4f` |

You must supply the original image yourself. No game data (ROM bytes, maps, graphics, tables, disassembly, traces, screenshots) is in this repository.

## How it works

The game keeps, for each of its two scrolling planes, a small record in work RAM (scroll values, the address and size of a byte map of 16 x 16 pixel blocks and the address of the table that expands a block to four VDP name-table words). The provider reads those records and the maps with the ABI 2 memory service at `frame-end`, rebuilds the name-table words of the cells around the camera for both planes and submits them as the typed authored `scenery_window` at `render`. The host's own VDP code decodes the patterns and palettes; the provider never touches VRAM and no tile is invented: a cell outside the map is the game's own empty block. The cartridge is never read at run time, nothing from it is embedded here, and the picture inside the original 320 x 224 is the Vanilla picture.

A scene is accepted only when the records are exactly the verified shape of a running level (the addresses of both maps and both tables and the map sizes of one of the scenes below); a menu, cutscene, level load or any other layout is declined and the host presents the generic extension for that frame.

## Verified scenes

| Scene | Identification | Where verified |
|---|---|---|
| `enchanted-forest` | plane A map 16 x 240 blocks, plane B map 16 x 32 | first level, controllable play |
| `castle-interior` | plane A map 32 x 112 blocks, plane B map 32 x 32 | the interior level of the attract demo |

Every other level, screen and boss is **unverified**: it is not touched by this package.
