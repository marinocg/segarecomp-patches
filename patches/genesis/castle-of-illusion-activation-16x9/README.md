# Castle of Illusion: early object activation for 16:9 (GAMEPLAY-CHANGING)

An opt-in variant, separate from the presentation-only package [`castle-of-illusion`](../castle-of-illusion/README.md), sharing its provider byte for byte. **Two typed ROM edits** and no guest code: the right column lookahead 0x180 -> 0x200 (`0x6d5cc`) and the initial-fill bound 0x280 -> 0x300 (`0x6d788`). **The static edits stay active whatever the presentation settings, including Original mode and narrower aspects.** The manifest claims `aspect_max = "16:9"`; the provider's wider presentation coverage is not advertised for this variant. There is no left change: the original object window test deletes every object left of the camera (see the 21:9 README), and the 16:9 picture adds only a 39 px margin.

## Why exactly these two (ablation, identity-based)
* lookahead alone: sections between the initial fill's reach and the new lookahead are never loaded (20 of 122 sampled objects missing);
* lookahead + the initial-fill bound: **0 of 250** original layout objects missing across all 29 stages, **no pool-full event** (the original has none either), +0.00% guest cost;
* the row-loader span (`0x6d59d`) and the right deletion limit are not needed at this window and are left out on purpose.
* The retry of the 21:9 project is not needed at this window: no allocation failure in 29 stages with repeated direction changes. Whether it would ever be needed beyond those stages is not known.

Objects created by the column loader already inside the visible 16:9 picture: right scroll 18-19% -> 13%; left scroll unchanged (37-47%); level-start initial fill 63-66% -> 46-48%. Allocated objects that never get a visible pixel: 21% -> 46% (the 0x80 px of extra window mostly lie beyond a 16:9 view).

## Identity and validation revisions
Package identity (deterministic): `60c57a1b53d2778b858556fee524651721747eb1787bfb0b0e32dd73a8c3d238`; effective image SHA-256 `1a16046a81bcc31cc70e39b60459dd3372bcc9feb49e46b221df40f80fb292ba` over `Castle of Illusion (USA, Europe)` (`2d535ff7eda650a64a9093ba6fabf8d5ac87801b898a76b591db41a1c8e47c4f`); validated against product main `8d419ab`; this package's sources did not change in this revision.

## Stage inventory
All 29 stages the in-game stage select accepts were run with the passive script (see the 21:9 README for the list and the scrolling/arena split); an active script (jumps, throws, left excursions) ran in 0-1, 0-2, 1-3, 4-0, 4-2. No guest stop, no missing original object. Pixel-level continuity was **not** measured for this package.

## Determinism, save states, launcher
Two straight runs (stage 4-0) give identical event streams; a quick-save restore taken 88 frames earlier replays the 103-event window identically (no guest code is injected, unlike the 21:9 package). The product's launcher flow (verify against the exact image, approval of the native code, install, build, select, saves isolated from Vanilla) ran green on the real image through `launcher_schema3_flow_test` for both this package and the 21:9 package.

## Limits
Left lookahead unchanged; item, damage, collision and RNG behavior not compared beyond object identity and kill/collect events; no boss defeated; audio clean (0 faults, 0 clipping). The provider's 48-piece-per-frame collection limit (see the 21:9 README) was measured only for the 21:9 variant (the original's maximum was 19 dropped pieces per frame there); it was not measured for this package.
