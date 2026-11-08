# Sonic the Hedgehog

> Native 16:9 for Sonic the Hedgehog (Genesis, REV00): the level scenery is reconstructed beyond the original 320-pixel picture from the game's own level data, and the original HUD is moved to the left edge of the wider picture. The same package also extends actor initialisation so objects do not pop in at the edge of the wide picture.

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
| Suggested starting presentation | Enhanced Widescreen · 16:9 · Raw Extension (a starting point, not a forced setting; your own choice is kept per installed variant) |
| Package version | 2.0.1 (collection release `v0.1.0`) |
| Evidence tier | maintainer-attested |

## Original image

The patch only applies to the exact image below; anything else is refused by digest, never by title or region.

| Package | Revision | Original image SHA-256 | Package SHA-256 |
|---|---|---|---|
| `sonic1-native-widescreen.segapatch` | REV00 | `46160baa06362c711c9f1a5017cb7371026444936c8af5e93a78996cf32ff2a6` | `636342c8a44516cc86bed4325c7f75d5721f0b38de8e852e2964a015566a5921` |

You must supply the original image yourself. No game data is included in this repository or in the packages.

## What the patch changes

* Reconstructs both scenery planes beyond the original picture in the running levels of Green Hill, Labyrinth, Marble, Star Light, Spring Yard and Scrap Brain, and in the Final Zone.
* Moves the original score/time/rings HUD to the left edge of the widened picture in every running level (a few-byte BPS change hides the original HUD sprites; the provider redraws the same pieces).
* Draws the special-stage background from the VDP's own wrapped planes when the verified configuration is present.
* **Extends actor initialisation:** the game's sprite builder only submits an object whose horizontal extent intersects the 320-pixel screen, so nothing beside a 16:9 picture is ever drawn and objects appear abruptly at the edge. This package widens that test by 64 pixels per side (a 12-byte routine in unused ROM padding plus a jump), so objects reach the sprite table, and get the on-screen flag, before they enter the side strips.

## What it intentionally does not change

* Does not change the object manager's own load and despawn windows (about -128 to +512 pixels around the camera) or the hardware sprite limits.
* Does not alter game logic, physics, audio or level data.
* Does not cover other revisions (REV01 or regional dumps are different images).

## Gameplay

Changes slightly: objects that wait for the on-screen flag start acting up to 64 pixels earlier than in the original, and a scripted natural-play route through Green Hill 1 did not reproduce identical play.

## Installation

See [docs/installation.md](../../../docs/installation.md) for the full steps. In short:

1. Download the package (and `SHA256SUMS`) from the release and check the digest.
2. In the segarecomp launcher open your game's **Details** page, then **Patches / Variants**, **Install patch...**, and choose the `.segapatch` file.
3. Read the approval sheet: this package contains executable C11 source that is compiled into the Patched program and is **not sandboxed**. Approve only if you trust it.
4. Select **Patched**, **Build patched version**, then **Play Patched**. Vanilla stays untouched.

## Known limitations

* Only the exact REV00 image is covered.
* Gameplay can differ slightly: objects that wait for the on-screen flag start acting up to 64 pixels earlier than in the original, and a scripted natural-play route through Green Hill 1 did not reproduce identical play.
* The object manager's own load and despawn windows are unchanged, the margin is 64 pixels (the 16:9 strips need 39), and the hardware sprite limits still apply.
* Special-stage background is the VDP's own wrapped plane (no reconstruction).

## Verification evidence

Maintainer-attested: generated-native play through the running levels with the provider's per-frame identity checks (frames the provider cannot explain are declined and shown by the generic renderer), and a frame-by-frame comparison against the earlier built-in implementation this provider was derived from. Aggregate evidence only; no recordings, frames or traces are published.

The archive, manifest, source image digest and patched image digest were additionally checked with the shipped `segarecomp patch verify` against the exact local image (maintainer-attested; the image is never published). Public CI cannot repeat this because it needs the commercial image.

## Source and licensing

* [`source/provider.c`](source/provider.c): the provider shipped byte-for-byte in the package (SHA-256 `1693d65d0a248f053cc0d10cb8c32e2389dc099a818d6d7c0fe4742d9dcef4d5`). License: **MPL-2.0** (the repository's [`LICENSE`](../../../LICENSE); the package manifest has no license field and the package bytes are unchanged).
* Comments inside the provider point to private authoring notes that are not published. The file is kept unchanged so its digest matches the package.
* The BPS delta is in `source/` ([`sonic1-native-widescreen.bps`](source/sonic1-native-widescreen.bps)); each file is byte-identical to the `game.bps` inside its package (SHA-256 in `release.json`).

## Download

* `sonic1-native-widescreen.segapatch`: 8037 bytes, SHA-256 `636342c8a44516cc86bed4325c7f75d5721f0b38de8e852e2964a015566a5921`

Download it from the [Releases page](https://github.com/marinocg/segarecomp-patches/releases) (collection `v0.1.0`) and check it against `SHA256SUMS`.

## Credits and trademarks

Patch authoring: segarecomp. Original game by SEGA and its developers. SEGA, Sega Genesis, Mega Drive, Sonic the Hedgehog, Streets of Rage and related names are trademarks of SEGA Corporation. The games and their artwork belong to their owners. segarecomp and this repository are not affiliated with or endorsed by SEGA, and no game data is distributed here.
