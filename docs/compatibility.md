# Compatibility

A patch applies to exact images only. Support is described per package; "maintainer-attested" evidence means the maintainer ran generated-native builds against the exact image and recorded aggregate outcomes. No recordings, frames or traces are published.

| Game | Package | Version | Exact original image SHA-256 | Schema | Scope | Gameplay |
|---|---|---|---|---|---|---|
| Sonic the Hedgehog (REV00) | `sonic1-native-widescreen` | 2.0.0 | `46160baa06362c711c9f1a5017cb7371026444936c8af5e93a78996cf32ff2a6` | 2 | Running levels, HUD, actors | Changes slightly |
| Sonic the Hedgehog 2 (World REV00) | `sonic2-native-widescreen` | 3.0.0 | `07329f4561044a504923eb0742894485c61fc42ebb0891eebff247ca2e086d61` | 2 | Single-player zones, HUD, actors | Changes slightly |
| Sonic the Hedgehog 2 (JUE REV01) | `sonic2-native-widescreen-rev01` | 3.0.0 | `193bc4064ce0daf27ea9e908ed246d87ec576cc294833badebb590b6ad8e8f6b` | 2 | Same as REV00 | Changes slightly |
| Sonic 3 & Knuckles (lock-on composite) | `sonic3k-native-widescreen` | 1.0.0 | `fba0677fde9f76df93f3e98d6310d8af68b9847bde16e253d73cd4dd8134ed23` | 2 | Single-player Sonic route, HUD, actors | Changes slightly |
| Streets of Rage 2 (USA) | `sor2-widescreen` | 1.0.0 | `4a314edbfee92282850fe95c4c764921916efd9d3c2277fdec2581279b1369b1` | 1 | Extra enemies in the margins | None intended |

## Common limits

* **16:9 only.** The packages were validated at Widescreen Width 100.
* **Wrapped scenery.** Where a provider cannot reconstruct a background, the generic renderer shows the VDP's own wrapped plane. That is a visual glitch, not a crash.
* **Sprite limits.** Widening the actor window submits more sprites; busy scenes can reach the hardware's per-line limits sooner.
* **Excluded modes.** Two-player modes and 240-line PAL frames are not covered by the Sonic 2 package.
* **No guarantee of full-campaign coverage.** Bosses, transitions, endings and alternative character routes of Sonic 3 & Knuckles have not been individually verified.
* **Other revisions are different images.** Sonic 1 REV01, regional Sonic 2 or Sonic 3 dumps, and standalone Sonic 3 / Sonic & Knuckles are not covered.

The authoritative compatibility ledger for the engine itself is in the [product repository](https://github.com/marinocg/segarecomp/blob/main/docs/product/compatibility-ledger.md).
