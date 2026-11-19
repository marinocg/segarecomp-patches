# Castle of Illusion: object activation with deferral for 32:9 (GAMEPLAY-CHANGING)

An opt-in variant, separate from the presentation-only package [`castle-of-illusion`](../castle-of-illusion/README.md), which stays available as the unmodified-gameplay alternative and is never modified by this one. It shares that package's provider byte for byte (checked by `tests/test_castle_activation.py`) and adds, to the 21:9 variant's early activation ([`castle-of-illusion-activation-21x9`](../castle-of-illusion-activation-21x9/README.md), whose trace and window analysis apply unchanged), the deferral of speculative sections that this README describes. It **changes which layout objects exist and when** (more enemies and items alive earlier and farther away, on both sides): explicitly **gameplay-changing**. Use the presentation-only package or the 16:9 variant if the game must behave as the original.

## What it changes
* **Nine typed ROM edits** (`edits/activation.edits`, every site asserts its original value): right lookahead 0x180 -> 0x2c0, left lookahead 0x71 -> 0x180, initial-fill bound 0x280 -> 0x4c0, row-loader span 4 -> 6, and five six-byte hooks.
* **A guest-asm routine** (`src/retry.asm`), the 21:9 routine with a 16-slot retry ring and, in the **entry hook of the section loader, a deterministic deferral**: when the layout pool (`0xD400..0xDBFF`, 32 slots; the pool the failures occur in) holds **at least 20 objects** and the section's column lies **beyond the original game's own window** (right of `(camera + 0x180) >> 7`, left of `(camera - 0xF1) >> 7`), the section is queued and the hook returns exactly as the original loader would have after loading nothing. The decision reads only guest state (the camera word and the pool), never host presentation. A deferred section is revisited by the retry ring once per streamer invocation; **a section deferred again keeps its age** (it is waiting, not failing); it is dropped when it leaves the retry window (the original game would not have loaded it either, and its own streamer asks again on re-entry). In-window sections are never deferred. Real allocation failures still queue, age (24 invocations) and are counted when they expire. The pools are not enlarged and no object is suppressed or freed.
* What the deferral cannot know is whether a speculative section holds a layout object, a non-visual trigger or a spawner; it treats the whole section alike and relies on revisiting, not on discarding. Safe removal through the original free path (`0x1c94`) was **not** implemented: no object class with an established lifecycle and reactivation semantics was identified, and deferral alone proved sufficient on the measured routes (below).

## Measured (private, scripted routes; aggregates only)
Method: a private diagnostic harness (not committed) runs the generated program headless from a chosen stage (the level pair is poked into the game's stage variables during the menu), a fixed pad script (right, then alternating right/left runs with jumps, 5,000 frames; deaths restart the level), and reads the pools and the code's own counters every frame. Stage inventory: the 29 pairs of the 21:9 README; **all 29 were run (3,000 frames, rightward route)** for the original, the 21:9 code, the 32:9 lookaheads without deferral and with it.

| 29 stages, rightward route | original | 21:9 code | 32:9 no deferral | 32:9 + deferral (threshold 24) |
|---|---|---|---|---|
| frames with the layout pool full | 0 | 89 (4-0 only) | 150 (4-0 only) | 0 |
| failed loads (queued) / expired (lost) | 0 / 0 | 73 / 1 | 252+148 / 3+3 (4-0, 3-2) | 0 / 0 |
| deferred sections later loaded | - | - | - | 27 (4-0), 10 (3-2), 4-17 elsewhere |

Stages other than 4-0 and 3-2 never exceeded 28 of 32 slots (any variant). Stage 4-0 and 3-2 on **both** routes (the second alternates right/left every 300 frames, so it crosses the same columns repeatedly in both directions), threshold sweep:

| 4-0, right/left route | max pool | frames full | failed (all later retried) | expired | ring-full drops |
|---|---|---|---|---|---|
| original | 26 | 0 | - | - | - |
| 21:9 code | 32 | 214 | 514 | 6 | - |
| 32:9 no deferral | 32 | 219 | 551 | 6 | - |
| deferral threshold 28 | 32 | 169 | 337 | 2 | 0 |
| 24 | 32 | 611 | 862 | 19 | 3 |
| **20 (shipped)** | **32** | **6** | **9** | **0** | **0** |
| 16 | 32 | 6 | 9 | 0 | 0 |
| 12 | 32 | 6 | 9 | 0 | 0 |

Reading: the six full frames that remain at every threshold up to 20 are demand inside the original window (the original itself reaches 26 on this route; allocations by other game code share the pool), the nine failures were all retried successfully, **no original (in-window) entry was lost and none expired**; lowering the threshold below 20 only defers more (38 attempts at 20, 47-65 at 16/12) without changing the outcome. Threshold 24 (the first prototype) is **not** sufficient on the left/right route (611 full frames, 19 expired sections): the shipped value is 20. Level transitions (every death restarts the level) and repeated crossings occur in these runs; no case of a pending retry across a level transition was observed (the state is cleared before every level initialization, tested). Retry-queue occupancy (pending demand) was not recorded separately; the ring never overflowed (counter 0 in every shipped-threshold run).

Gameplay effect: sections beyond the original window are activated only while the layout pool has room (fewer than 20 objects) or once they are inside the original window; essential in-window sections are never held back. The *effect on gameplay* beyond that is not measured: item collection, damage, collisions, progression and boss completion were **not** verified (see Acceptance). Visible actor continuity was not measured at pixel level for this variant.

## Acceptance (what was and was not done)
* Executable tests of the injected code: `tests/test_castle_activation32_exec.py` (15 tests: threshold edges, both speculative sides, camera dependence, return exactness - registers, stack, complete RAM image -, dedup, full ring, retry-mode flag, invalid key, deferred slot keeps its age, drop outside the window, genuine failures still expire, reset); two mutations caught. The shared hooks keep their tests in `test_castle_activation_exec.py`. Provider tests: 44.
* Real viewer (private image, dummy video/audio): **all 29 stages x {16:9 package, 21:9 package, 32:9 package}, plus the presentation-only package at 21:9 and 32:9 on four stages: 95 of 95 runs reached 6,000 frames with no guest stop and no mod fault** (right/left route). The host's "virtual sprites not presented" frames are 0.15% of frames and **identical per stage for every package and aspect** (e.g. 13 in 4-0), i.e. they belong to the run, not to sprite placement. Two pixel samples of 4-0 and 3-2 at 32:9 were inspected (coherent picture, authored margins).
* Determinism: two independent viewer runs of this package gave an identical final work-RAM SHA-256; quick save, quick load and rewind all reported `ok` in one run with the mod never faulting; guest-level snapshot/restore (full container digest, RAM, registers, camera, ticks at every frame boundary) of the exact final image is identical to the uninterrupted run for a boundary and a mid-frame barrier on stage 4-0 (300 frames).
* **Not done:** pixel-level validation beyond samples; 16:9 / dense / red-water / boss stages identified by name (the stage pairs were not mapped to those descriptions); item collection, damage, collision, progression and boss-completion verification; any boss defeated. The conclusion is therefore limited to: the pool failures at 32:9 are removed on the measured routes without losing in-window entries, and the package runs the whole stage list without faulting. It is not a claim of full gameplay correctness.

## Scope, identity, validation
Validated for **32:9** only (`aspect_max = "32:9"`; the provider presents up to that width). Native code is host code: the user approves this exact package identity `341c7c93d154d4d2db8faf6581460d3d4555dd81552733dabcff9928e9383ef7` (deterministic: two builds are byte-identical); effective image SHA-256 `181aa803eb86a2aa020ec79857c77fc65da45dddb6960fa50e36eaf4bd14bb47`. Product `marinocg/segarecomp` main `8d419ab`. Unpublished source project: no `release.json`, no catalog entry.
