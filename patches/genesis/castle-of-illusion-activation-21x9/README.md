# Castle of Illusion: early object activation for 21:9 (GAMEPLAY-CHANGING)

An opt-in variant, separate from the presentation-only package [`castle-of-illusion`](../castle-of-illusion/README.md) (which it does not replace and never modifies). It uses the same provider (`src/provider.c` is a byte-identical copy, checked by `tests/test_castle_activation.py`), plus:

* four typed ROM edits that move the original streamer's activation window from 0x180 to 0x280 pixels: the column lookahead, the section-list limit, the row-loader span and the object off-screen deletion limit (`edits/activation.edits`; every site asserts its original value);
* a bounded guest-asm retry (`src/retry.asm`, 454 bytes, three hooks that each jump into it and back to the original continuation). When the original loader finds its object pool full the entry is lost until its section is loaded again; the retry remembers the (column, row) of such a section in a four-slot queue and re-runs the ORIGINAL loader for it once per streamer invocation, for at most 24 invocations, only while the section is still near the camera. A retried section skips entries whose loaded flag is set, exactly as an original re-entry would, so nothing is duplicated and the original's rules for retired entries apply unchanged. The list pointer is not queued: it depends only on the level layout and is rebuilt as the original does. State lives in 48 bytes at `0xFFFC00..0xFFFC2F`, which the original never writes.

It changes which layout objects exist and when (more enemies and items are alive earlier and farther ahead; peak live layout objects rose from 23 to 32 in the measured stages), so it is **gameplay-changing**: build it only knowingly. Use the 16:9 variant for 16:9. 32:9 is not provided (see Limits).

## Evidence (aggregate counts; 19 scrolling stages, original window as the oracle, controlled by section/entry identity)

* Layout objects of the original that this variant never creates: **0 of 238**; extra objects (created earlier / farther): 77. Hooks alone (original window): object event sequence identical to the original in 18 of 19 stages (one stage differs by a one-frame timing shift).
* Allocation failures: 10 in one stage (4,0); the queue took 2 sections; both recovered within 2 invocations; no entry was dropped, expired or invalidated. At 0x380 the same queue is NOT sufficient (see Limits).
* Per-frame viewport geometry (right edge = 320 + 2 x margin - left): objects created by the right-scrolling column loader that were already inside the visible 21:9 picture at creation: 66% originally, 15% with this variant (sprite half-extent 16 px; 49% -> 15% for the object origin alone). Allocated-but-never-visible objects rose from 7% to 34% of creations (the cost of the wider window).
* Guest cost: +0.07% instructions per frame (median over whole runs), +0.29% at most; peak live layout objects 32 (original 23).
* Queue behaviour under a deliberate stress build (pools shrunk to 6/3/6 slots): occupancy never above 4; queue-full drops, dedup and expiry all exercised; every expiry after exactly 24 streamer invocations; no write outside the 48 bytes; quick-save and rewind taken while four retries were pending replay identically.
* Work RAM `0xFFFC00..0xFFFC3F` was never written by the original game across 19 stages and a 60,000-frame run from boot (logos, title, attract demos, levels); lowest stack pointer 0xFFFEA0, about 620 bytes above the extent, and the same in the original and in the hook builds (the hooks never reach the game's own deepest point).

## Limits

* Not measured: item collection, damage, collision, RNG and audio behaviour beyond event identity; guest timing differs slightly (extra work per frame), so frame-by-frame input replays of the original do not stay bit-identical.
* Left-scrolling lookahead is unchanged: objects entering from the left edge still appear inside the picture (85% at 21:9; the left constant is a separate edit not made here).
* 32:9: at 0x380 the four-slot queue overflowed (4 queue-full drops, 2 expiries in 11 queued sections over the same stages) and the left lookahead is insufficient, so no 32:9 variant is offered.
* Only the 19 stages listed by the measurement (of about 25 scrolling stages) were run; boss arenas and unlisted substages were not.

Build: `segarecomp mod build patches/genesis/castle-of-illusion-activation-21x9 --out castle-21x9.segapatch` (the build is byte-reproducible); apply with your own `Castle of Illusion (USA, Europe)` image.
