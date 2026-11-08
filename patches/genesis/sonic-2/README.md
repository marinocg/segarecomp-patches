# Sonic the Hedgehog 2

> Native 16:9 for Sonic the Hedgehog 2 (Genesis) with reconstructed scenery, a relocated HUD and widened actor coverage, for two independently packaged revisions.

![Sonic the Hedgehog 2, Emerald Hill Zone 1, in 16:9 with extended scenery, the relocated HUD and a Buzzer enemy drawn in the extended right margin](https://raw.githubusercontent.com/marinocg/segarecomp/main/docs/assets/showcase/sonic-2-emerald-hill-patched-16x9.png)

*Emerald Hill Zone 1 at 16:9 (World REV00): reconstructed scenery, relocated HUD, and a Buzzer badnik drawn in the extended right margin. A partial actor at the far left edge is expected.* Screenshot from the [segarecomp showcase](https://github.com/marinocg/segarecomp/tree/main/docs/assets/showcase).

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Revision | World REV00 and JUE REV01 (two packages, one shared `provider.c`) |
| Package schema | 2: BPS + trusted native C11 source (executable, not sandboxed) |
| Native SDK ABI | 1 (capabilities: frame.work_ram, frame.vdp, scenery.words, overlay.rgba) |
| Required segarecomp | A build that includes the patch installer and native patch SDK (not part of v0.7.0; first shipped in the next release) |
| Supported target | 16:9 (Widescreen Width 100) |
| Suggested starting presentation | Enhanced Widescreen · 16:9 · Raw Extension (a starting point, not a forced setting; your own choice is kept per installed variant) |
| Package version | 3.0.1 (collection release `v0.1.0`) |
| Evidence tier | maintainer-attested |

## Original image

The patch only applies to the exact image below; anything else is refused by digest, never by title or region.

| Package | Revision | Original image SHA-256 | Package SHA-256 |
|---|---|---|---|
| `sonic2-native-widescreen.segapatch` | World REV00 | `07329f4561044a504923eb0742894485c61fc42ebb0891eebff247ca2e086d61` | `9763ffe11a2753a6bba49589de40faa4d6b5ee0b8ed9a912026b0fb79fa5bcca` |
| `sonic2-native-widescreen-rev01.segapatch` | JUE REV01 | `193bc4064ce0daf27ea9e908ed246d87ec576cc294833badebb590b6ad8e8f6b` | `3466a9482740901b06768c0e448bf11dce04217ab2295d72b8d34154a052a90d` |

You must supply the original image yourself. No game data is included in this repository or in the packages.

## What the patch changes

* Reconstructs both scenery planes beyond the original picture from the game's own level layout in the single-player zones.
* Relocates the original HUD to the left edge of the widened picture.
* Widens the sprite builder and the ring window by 64 pixels per side so actors and rings appear in the margins.

## What it intentionally does not change

* Does not reconstruct the lower lava background band of Hill Top, Wing Fortress beyond its first sections, the ending or the special-stage presentation: those frames use the generic widescreen renderer.
* Does not cover two-player mode or 240-line PAL frames.
* Does not cover revisions other than the two exact images listed below.

## Gameplay

Changes slightly: because actors are submitted in the widened margins they are flagged on screen, so some enemies become active earlier, rings in the margins can be collected, and the 80-sprite / per-line limits are reached sooner in busy scenes.

## Installation

See [docs/installation.md](../../../docs/installation.md) for the full steps. In short:

1. Download the package (and `SHA256SUMS`) from the release and check the digest.
2. In the segarecomp launcher open your game's **Details** page, then **Patches / Variants**, **Install patch...**, and choose the `.segapatch` file.
3. Read the approval sheet: this package contains executable C11 source that is compiled into the Patched program and is **not sandboxed**. Approve only if you trust it.
4. Select **Patched**, **Build patched version**, then **Play Patched**. Vanilla stays untouched.

## Known limitations

* Each package covers only its own exact image: World REV00 or JUE REV01.
* Gameplay can differ slightly: additional actors become active or visible in the widened margins.
* Hill Top's lower lava background band, Wing Fortress beyond its first sections, the ending and special-stage presentation fall back to the generic renderer.
* Two-player mode and 240-line PAL frames are not covered.

## Verification evidence

Maintainer-attested: generated-native debug-mode sweeps of the zones, natural-play and act-end runs on both images, with per-frame identity checks against the VDP. REV01 was verified separately for the same scope as REV00 (own BPS bytes and package identity, same provider). Aggregate evidence only.

The archive, manifest, source image digest and patched image digest were additionally checked with the shipped `segarecomp patch verify` against the exact local image (maintainer-attested; the image is never published). Public CI cannot repeat this because it needs the commercial image.

## Source and licensing

* [`source/provider.c`](source/provider.c): the provider shipped byte-for-byte in the package (SHA-256 `b5551f6c9d923a746c45aa7095d1f999da55011638c9f1fd3434acc8e0900ed0`). License: **MIT**.
* Comments inside the provider point to private authoring notes that are not published. The file is kept unchanged so its digest matches the package.
* The BPS deltas are in `source/` ([`sonic2-native-widescreen.bps`](source/sonic2-native-widescreen.bps), [`sonic2-native-widescreen-rev01.bps`](source/sonic2-native-widescreen-rev01.bps)); each file is byte-identical to the `game.bps` inside its package (SHA-256 in `release.json`).

## Download

* `sonic2-native-widescreen.segapatch`: 9096 bytes, SHA-256 `9763ffe11a2753a6bba49589de40faa4d6b5ee0b8ed9a912026b0fb79fa5bcca`
* `sonic2-native-widescreen-rev01.segapatch`: 9099 bytes, SHA-256 `3466a9482740901b06768c0e448bf11dce04217ab2295d72b8d34154a052a90d`

Download it from the [Releases page](https://github.com/marinocg/segarecomp-patches/releases) (collection `v0.1.0`) and check it against `SHA256SUMS`.

## Credits and trademarks

Patch authoring: segarecomp. Original game by SEGA and its developers. SEGA, Sega Genesis, Mega Drive, Sonic the Hedgehog, Streets of Rage and related names are trademarks of SEGA Corporation. The games and their artwork belong to their owners. segarecomp and this repository are not affiliated with or endorsed by SEGA, and no game data is distributed here.
