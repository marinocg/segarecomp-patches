# Sonic 3 & Knuckles

> Native 16:9 for the Sonic 3 & Knuckles lock-on composite, with reconstructed foreground scenery, background reconstruction where the level layout explains it, a relocated HUD and widened actor coverage.

![Sonic 3 and Knuckles, Angel Island Zone 1, in 16:9 with extended jungle scenery and the relocated HUD](https://raw.githubusercontent.com/marinocg/segarecomp/main/docs/assets/showcase/sonic-3-knuckles-angel-island-patched-16x9.png)

*Angel Island Zone 1 at 16:9: foreground scenery reconstructed from the game's level data, relocated HUD. On this act the background beside the picture is partly the VDP's own wrapped plane, so its texture repeats.* Screenshot from the [segarecomp showcase](https://github.com/marinocg/segarecomp/tree/main/docs/assets/showcase).

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Revision | Lock-on composite, `Sonic and Knuckles & Sonic 3 (JUE) [!].bin` (4 MiB) |
| Package schema | 2: BPS + trusted native C11 source (executable, not sandboxed) |
| Native SDK ABI | 1 (capabilities: frame.work_ram, frame.vdp, scenery.words, overlay.rgba) |
| Required segarecomp | A build that includes the patch installer and native patch SDK (not part of v0.7.0; first shipped in the next release) |
| Supported target | 16:9 (Widescreen Width 100) |
| Suggested starting presentation | Enhanced Widescreen · 16:9 · Raw Extension (a starting point, not a forced setting; your own choice is kept per installed variant) |
| Package version | 1.0.1 (collection release `v0.1.0`) |
| Evidence tier | maintainer-attested |

## Original image

The patch only applies to the exact image below; anything else is refused by digest, never by title or region.

| Package | Revision | Original image SHA-256 | Package SHA-256 |
|---|---|---|---|
| `sonic3k-native-widescreen.segapatch` | lock-on composite (JUE) | `fba0677fde9f76df93f3e98d6310d8af68b9847bde16e253d73cd4dd8134ed23` | `8d08e4dbf13642331ba821fc46e29d576d8c6c6c017bbaea17f5f52771bf995a` |

You must supply the original image yourself. No game data is included in this repository or in the packages.

## Compatibility

**Playable widescreen (maintainer-tested).** Native 16:9 has been tested across the Sonic campaign. Foreground scenery, HUD relocation and extended actor rendering work as intended. Some scenes may exhibit minor background wrapping, visual seams or other graphical imperfections.

Automated tests cover all 27 Sonic-route acts with high frame acceptance. Boss encounters, transitions, endings and alternative character routes have not received the same exhaustive automated verification. These validation limitations should not be interpreted as known gameplay blockers.

## Composite lock-on requirement

The image is the 4 MiB lock-on composite: the lower 2 MiB are Sonic & Knuckles, the upper 2 MiB Sonic 3. It must be built as a **declared lock-on cartridge**. The launcher recognises this exact image from its header contents and selects the lock-on mapper automatically; for a command-line build pass `--mapper lock_on`. Without the lock-on declaration the composite stops a few frames after power-on. Standalone Sonic & Knuckles and standalone Sonic 3 images are not covered and are refused by identity.

## What the patch changes

* Reconstructs the foreground beyond the picture in the single-player zones, and the background where its layout can be derived. Elsewhere the background is the VDP's own wrapped plane, which repeats.
* Relocates the original HUD to the left edge of the widened picture.
* Widens the sprite builder, multi-sprite writer and ring manager window by 64 pixels per side so actors and rings appear in the margins.

## What it intentionally does not change

* Does not make every background seamless: some zones draw background bands from sources the level model does not describe, and those use wrapped scenery.
* Does not cover standalone Sonic 3 or standalone Sonic & Knuckles images: they are different identities.

## Gameplay

Changes slightly: objects and rings in the margins count as on screen, so some enemies activate earlier and rings can be collected or attracted from the margins. More sprites are submitted, so busy scenes can reach the sprite limits sooner.

## Installation

See [docs/installation.md](../../../docs/installation.md) for the full steps. In short:

1. Download the package (and `SHA256SUMS`) from the release and check the digest.
2. In the segarecomp launcher open your game's **Details** page, then **Patches / Variants**, **Install patch...**, and choose the `.segapatch` file.
3. Read the approval sheet: this package contains executable C11 source that is compiled into the Patched program and is **not sandboxed**. Approve only if you trust it.
4. Select **Patched**, **Build patched version**, then **Play Patched**. Vanilla stays untouched.

## Known limitations

* Only the exact 4 MiB lock-on composite is covered; standalone Sonic 3 or Sonic & Knuckles images are different identities.
* Must be built as a declared lock-on cartridge (the launcher selects it automatically for this image; CLI builds need --mapper lock_on).
* Some backgrounds still use the VDP's own wrapped scenery.
* Some scenes may exhibit minor background wrapping (the VDP's own wrapped scenery), visual seams or other graphical imperfections.
* Gameplay can differ slightly: additional actors and rings become active in the widened margins.
* Sprite budget and per-line limits can be reached sooner in busy scenes.

## Verification evidence

Maintainer-attested: generated-native sweeps of 27 Sonic-route acts (97.7-100 % of level frames accepted per act; the foreground is reconstructed in every accepted frame, the background on 0-100 % of lines depending on the act), a natural play route of 11,000+ frames, and a HUD check against Vanilla (audio and virtual frames identical, only the ten HUD sprite Y words differ). Aggregate evidence only.

The archive, manifest, source image digest and patched image digest were additionally checked with the shipped `segarecomp patch verify` against the exact local image (maintainer-attested; the image is never published). Public CI cannot repeat this because it needs the commercial image.

## Source and licensing

* [`source/provider.c`](source/provider.c): the provider shipped byte-for-byte in the package (SHA-256 `881f1e2d702a9ab7af2426b36f6aae285a56419d5b8de119a755901ee24bd5da`). License: **MIT**.
* Comments inside the provider point to private authoring notes that are not published. The file is kept unchanged so its digest matches the package.
* The BPS delta is in `source/` ([`sonic3k-native-widescreen.bps`](source/sonic3k-native-widescreen.bps)); each file is byte-identical to the `game.bps` inside its package (SHA-256 in `release.json`).

## Download

* `sonic3k-native-widescreen.segapatch`: 8941 bytes, SHA-256 `8d08e4dbf13642331ba821fc46e29d576d8c6c6c017bbaea17f5f52771bf995a`

Download it from the [Releases page](https://github.com/marinocg/segarecomp-patches/releases) (collection `v0.1.0`) and check it against `SHA256SUMS`.

## Credits and trademarks

Patch authoring: segarecomp. Original game by SEGA and its developers. SEGA, Sega Genesis, Mega Drive, Sonic the Hedgehog, Streets of Rage and related names are trademarks of SEGA Corporation. The games and their artwork belong to their owners. segarecomp and this repository are not affiliated with or endorsed by SEGA, and no game data is distributed here.
