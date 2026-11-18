# Castle of Illusion: early object activation for 16:9 (GAMEPLAY-CHANGING)

An opt-in variant, separate from the presentation-only package [`castle-of-illusion`](../castle-of-illusion/README.md). Same provider (`src/provider.c` is a byte-identical copy); four typed ROM edits move the original streamer's activation window from 0x180 to 0x200 pixels (column lookahead, section-list limit, row-loader span, object deletion limit). No guest code, no retry: in the measured stages this window never filled an object pool.

Evidence (19 scrolling stages, original as oracle, controlled by section/entry identity): 0 of 238 original layout objects lost, 27 created earlier; no pool-full event; objects created by the right-scrolling column loader already inside the visible 16:9 picture: 21% originally, 15% here (the original is already close at 16:9, so the gain is modest); allocated-but-never-visible objects 18% -> 28%. Peak live layout objects 25 (original 23).

Gameplay-changing for the same reason as the 21:9 variant, with the same limits: left-scrolling lookahead unchanged; item, damage, collision, RNG and audio behaviour not measured; only the listed stages were run. Whether the retry would ever be needed at this window beyond those stages is not known; the 21:9 project carries it.

Build: `segarecomp mod build patches/genesis/castle-of-illusion-activation-16x9 --out castle-16x9.segapatch`.
