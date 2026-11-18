# Castle of Illusion: early object activation for 16:9 (GAMEPLAY-CHANGING)

An opt-in variant, separate from the presentation-only package [`castle-of-illusion`](../castle-of-illusion/README.md), sharing its provider byte for byte. **Two typed ROM edits** and no guest code: the right column lookahead 0x180 -> 0x200 (`0x6d5cc`) and the initial-fill bound 0x280 -> 0x300 (`0x6d788`). **The static edits stay active whatever the presentation settings, including Original mode and narrower aspects.** The manifest claims `aspect_max = "16:9"`; the provider's wider presentation coverage is not advertised for this variant.

## Why exactly these two (ablation, 25 stages, identity-based)
* lookahead alone: sections between the initial fill's reach and the new lookahead are never loaded (20 of 122 sampled objects missing);
* lookahead + the initial-fill bound: **0 of 234** original layout objects missing, no pool-full event (the original has none either), occupancy unchanged (max 28 vs 31 in the 48-slot object region), +0.00% guest cost;
* the row-loader span (`0x6d59d`) and the right deletion limit (`0x1b14`) are not needed at this window. The deletion limit would reduce allocated-then-deleted objects (never-visible allocations 22% -> 45% with only the two edits; initializations per entry 1.44 -> 1.35, i.e. not more); it is not required for correctness and is left out on purpose.
* The retry of the 21:9 project is not needed at this window: no allocation failure in 25 stages with repeated direction changes. Whether it would ever be needed beyond those stages is not known.

Objects created by the column loader already inside the visible 16:9 picture: right scroll 20% -> 14% (the original is already close at 16:9, so the gain is modest); left scroll unchanged (47%).

## Identity and validation revisions
Package identity (deterministic): `60c57a1b53d2778b858556fee524651721747eb1787bfb0b0e32dd73a8c3d238`; effective image SHA-256 `1a16046a81bcc31cc70e39b60459dd3372bcc9feb49e46b221df40f80fb292ba` over `Castle of Illusion (USA, Europe)` (`2d535ff7eda650a64a9093ba6fabf8d5ac87801b898a76b591db41a1c8e47c4f`); validated against product main `8d419ab`.

## Limits
Same stage set and movement as the 21:9 README; left lookahead unchanged; item, damage, collision and RNG behavior not compared beyond object identity; audio clean (0 faults, 0 clipping). Only the listed 25 stages were run.
