# Sonic the Hedgehog

> Native 16:9 for Sonic the Hedgehog (Genesis, REV00): the level scenery is reconstructed beyond the original 320-pixel picture from the game's own level data, and the original HUD is moved to the left edge of the wider picture.

![Sonic the Hedgehog, Green Hill Zone 1, in generated-native 16:9 with reconstructed scenery on both sides and the original score, time and rings HUD moved to the left edge](https://raw.githubusercontent.com/marinocg/segarecomp/main/docs/assets/showcase/sonic-1-green-hill-patched-16x9.png)

*Green Hill Zone 1 at 16:9: scenery reconstructed from the game's own level data on both sides, original HUD relocated to the left edge (Enhanced Widescreen, width 100, Raw Extension).* Screenshot from the [segarecomp showcase](https://github.com/marinocg/segarecomp/tree/main/docs/assets/showcase).

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Revision | REV00 (USA/Europe) |
| Package schema | 2: BPS + trusted native C11 source (executable, not sandboxed) |
| Native SDK ABI | 1 (capabilities: frame.work_ram, frame.vdp, scenery.words, overlay.rgba) |
| Required segarecomp | A build that includes the patch installer and native patch SDK (not part of v0.7.0; first shipped in the next release) |
| Supported target | 16:9 (Widescreen Width 100) |
| Package version | 1.0.0 (collection release `v0.1.0`) |
| Evidence tier | maintainer-attested |

## Original image

The patch only applies to the exact image below; anything else is refused by digest, never by title or region.

| Package | Revision | Original image SHA-256 | Package SHA-256 |
|---|---|---|---|
| [`sonic1-native-widescreen.segapatch`](https://github.com/marinocg/segarecomp-patches/releases/download/v0.1.0/sonic1-native-widescreen.segapatch) | REV00 | `46160baa06362c711c9f1a5017cb7371026444936c8af5e93a78996cf32ff2a6` | `a62de6fdd90ded70435d6111bdaa20c9938f5d9834e849fa32dc7c47ef0c1a97` |

You must supply the original image yourself. No game data is included in this repository or in the packages.

## What the patch changes

* Reconstructs both scenery planes beyond the original picture in the running levels of Green Hill, Labyrinth, Marble, Star Light, Spring Yard and Scrap Brain, and in the Final Zone.
* Moves the original score/time/rings HUD to the left edge of the widened picture in every running level (a few-byte BPS change hides the original HUD sprites; the provider redraws the same pieces).
* Draws the special-stage background from the VDP's own wrapped planes when the verified configuration is present.

## What it intentionally does not change

* No extended object activation: enemies and items are created and removed exactly as in the original. (An experimental variant that changes this exists privately and is **not** part of this release.)
* Does not alter game logic, physics, audio or level data.
* Does not cover other revisions (REV01 or regional dumps are different images).

## Gameplay

Unchanged apart from the relocated HUD.

## Installation

See [docs/installation.md](../../../docs/installation.md) for the full steps. In short:

1. Download the package (and `SHA256SUMS`) from the release and check the digest.
2. In the segarecomp launcher open your game's **Details** page, then **Patches / Variants**, **Install patch...**, and choose the `.segapatch` file.
3. Read the approval sheet: this package contains executable C11 source that is compiled into the Patched program and is **not sandboxed**. Approve only if you trust it.
4. Select **Patched**, **Build patched version**, then **Play Patched**. Vanilla stays untouched.

## Known limitations

* Only the exact REV00 image is covered.
* Special-stage background is the VDP's own wrapped plane (no reconstruction).
* No extended object activation: objects are not created or kept alive beyond the original window.

## Verification evidence

Maintainer-attested: generated-native play through the running levels with the provider's per-frame identity checks (frames the provider cannot explain are declined and shown by the generic renderer), and a frame-by-frame comparison against the earlier built-in implementation this provider was derived from. Aggregate evidence only; no recordings, frames or traces are published.

The archive, manifest, source image digest and patched image digest were additionally checked with the shipped `segarecomp patch verify` against the exact local image (maintainer-attested; the image is never published). Public CI cannot repeat this because it needs the commercial image.

## Source and licensing

* [`source/provider.c`](source/provider.c): the provider shipped byte-for-byte in the package (SHA-256 `1693d65d0a248f053cc0d10cb8c32e2389dc099a818d6d7c0fe4742d9dcef4d5`). License declared in the package manifest: **not declared by the package**. This package declares **no** license; the maintainer must decide it before publication and it is not relicensed here.
* Comments inside the provider point to private authoring notes that are not published. The file is kept unchanged so its digest matches the package.
* The BPS payload is a delta against a commercial image. It is distributed only inside the release package and is **not committed to Git**. Its redistribution is subject to the publication review in [docs/releases.md](../../../docs/releases.md).

## Download

* [`sonic1-native-widescreen.segapatch`](https://github.com/marinocg/segarecomp-patches/releases/download/v0.1.0/sonic1-native-widescreen.segapatch): 8011 bytes, SHA-256 `a62de6fdd90ded70435d6111bdaa20c9938f5d9834e849fa32dc7c47ef0c1a97`

The link becomes valid when the `v0.1.0` release is published.

## Credits and trademarks

Patch authoring: segarecomp. Original game by SEGA and its developers. SEGA, Sega Genesis, Mega Drive, Sonic the Hedgehog, Streets of Rage and related names are trademarks of SEGA Corporation. The games and their artwork belong to their owners. segarecomp and this repository are not affiliated with or endorsed by SEGA, and no game data is distributed here.
