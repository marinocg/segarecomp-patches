# Streets of Rage 2

> Widescreen sprite coverage for Streets of Rage 2 (Genesis, USA): a tiny data-only patch that widens the game's sprite-piece submission window so additional enemies are drawn in the horizontal margins.

![Streets of Rage 2, stage 1, in 16:9 with enemies drawn beside the native picture](https://raw.githubusercontent.com/marinocg/segarecomp/main/docs/assets/showcase/streets-of-rage-2-stage-1-patched-16x9.png)

*Stage 1 at 16:9: additional enemies are drawn beside the native picture. The scenery on the right edge is the generic renderer's wrapped scenery, not an authored reconstruction; the HUD stays in its original place.* Screenshot from the [segarecomp showcase](https://github.com/marinocg/segarecomp/tree/main/docs/assets/showcase).

| | |
|---|---|
| Platform | Sega Genesis / Mega Drive |
| Revision | USA |
| Package schema | 1: data-only BPS (no executable code) |
| Required segarecomp | A build that includes the patch installer |
| Supported target | 16:9 (Widescreen Width 100) |
| Suggested starting presentation | Enhanced Widescreen · 16:9 · Raw Extension (a starting point, not a forced setting; your own choice is kept per installed variant) |
| Package version | 1.0.0 (collection release `v0.1.0`) |
| Evidence tier | maintainer-attested |

## Original image

The patch only applies to the exact image below; anything else is refused by digest, never by title or region.

| Package | Revision | Original image SHA-256 | Package SHA-256 |
|---|---|---|---|
| `sor2-widescreen.segapatch` | USA | `4a314edbfee92282850fe95c4c764921916efd9d3c2277fdec2581279b1369b1` | `fb0f99422fa8c8b5cbf5f9c3c622fe22e786ed3387200dfdf159bb48c47c1eec` |

You must supply the original image yourself. No game data is included in this repository or in the packages.

## BPS-only versus native packages

Sonic 1, 2 and 3 & Knuckles use a trusted native provider to reconstruct scenery and the HUD. Streets of Rage 2 does not: the only game-specific change is the BPS delta, and everything on the sides other than the extra sprites comes from the generic widescreen presentation segarecomp applies to every game.

## What the patch changes

* Widens the sprite-piece submission window (a BPS delta of a few bytes), so enemies and objects beside the original picture are submitted and drawn.
* Verified behaviour: additional enemies are drawn in the horizontal margins.

## What it intentionally does not change

* **No native reconstruction provider.** This is a schema 1, BPS-only package: it contains no C11 source and no executable code.
* No custom background reconstruction and no HUD relocation. The side scenery is the generic renderer's wrapped scenery (segarecomp's Level 2/3 extension) and the HUD stays where the original game draws it.
* Does not cover other revisions.

## Gameplay

None intended.

## Installation

See [docs/installation.md](../../../docs/installation.md) for the full steps. In short:

1. Download the package (and `SHA256SUMS`) from the release and check the digest.
2. In the segarecomp launcher open your game's **Details** page, then **Patches / Variants**, **Install patch...**, and choose the `.segapatch` file.
3. The package is data-only BPS: the launcher verifies it against your exact image and never executes anything from it.
4. Select **Patched**, **Build patched version**, then **Play Patched**. Vanilla stays untouched.

## Known limitations

* Only the exact USA image is covered.
* No custom background reconstruction and no HUD relocation: the HUD stays in its original place and the side scenery is generic wrapped scenery.
* Other revisions are not covered.

## Verification evidence

Maintainer-attested: generated-native play with the patch, additional enemies observed in the margins. Aggregate evidence only.

The archive, manifest, source image digest and patched image digest were additionally checked with the shipped `segarecomp patch verify` against the exact local image (maintainer-attested; the image is never published). Public CI cannot repeat this because it needs the commercial image.

## Source and licensing

* There is no C11 source: the package is a BPS delta only and no provider exists.
* The BPS delta is in `source/` ([`sor2-widescreen.bps`](source/sor2-widescreen.bps)); each file is byte-identical to the `game.bps` inside its package (SHA-256 in `release.json`).

## Download

* `sor2-widescreen.segapatch`: 656 bytes, SHA-256 `fb0f99422fa8c8b5cbf5f9c3c622fe22e786ed3387200dfdf159bb48c47c1eec`

Download it from the [Releases page](https://github.com/marinocg/segarecomp-patches/releases) (collection `v0.1.0`) and check it against `SHA256SUMS`.

## Credits and trademarks

Patch authoring: segarecomp. Original game by SEGA and its developers. SEGA, Sega Genesis, Mega Drive, Sonic the Hedgehog, Streets of Rage and related names are trademarks of SEGA Corporation. The games and their artwork belong to their owners. segarecomp and this repository are not affiliated with or endorsed by SEGA, and no game data is distributed here.
