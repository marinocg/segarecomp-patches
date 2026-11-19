# Castle of Illusion: debug free-fly (GAMEPLAY-CHANGING while active)

A user-invoked **debug mode in the spirit of Sonic's debug mode**: Mickey floats freely through the level, ignoring floors, walls, ceilings, enemies and pits, so a level can be explored. It is a separate opt-in package (native ABI 2, no ROM edit, no guest code); it does not change the game until the chord is pressed, and the presentation-only package `castle-of-illusion` is untouched.

## Controls (player 1)
* **A + B + C together** toggles the mode (an edge: holding the chord does not toggle again). Entering starts from Mickey's current position; leaving hands him back to the game exactly where he is (the game's own gravity and collision apply again from there).
* While flying: the **d-pad** moves Mickey **3 px per frame**, **A held doubles it** (6 px). The game sees only Start (so pausing still works); it does not walk, jump or throw.
* Mickey stays inside the visible part of the screen: the game's own camera follows him at its own limited speed and he waits at the edge. The camera is never written (the game streams the level column by column as it scrolls, so teleporting it would skip columns).
* Mickey's **power is kept full** while flying (the power word, the five HUD slot words and the HUD-upload flag, as Practice+ does), so nothing can hurt or kill him. A dead Mickey is the game's own sequence and is not touched.

## How it works (facts about the work RAM of this one image)
Mickey is the object slot at `0xDC00`: `+0x10` x and `+0x14` y (pixels, each followed by a fraction word) and the vertical velocity at `+0x1A/+0x1C` (16.16). Per frame the provider moves its tracked position before the game's frame logic (`post-input`), zeroes the velocity, and writes the position again at the frame's end (`frame-end`) so a collision correction of the game cannot move him. The collision box (`0xF330..`) and the camera are the game's own derivations of that position. Declared memory: the Mickey slot, the power/HUD words, and the scroll record `0xFA80..0xFA87` (read only). The mode state (on/off, position) is part of the save state.

## Evidence
* **Real image** (private; viewer, scripted input, dummy video): on the first level Mickey walks into the rock ledge that stops him (control run without the package: x=1303, power 1). With the package, after the chord he flies through the ledge and the rock face behind it, high above the level and across it; the camera follows (camera x 1723 vs 1111 at the same point), power is 5, and at the level's exit the game moves on to the next level (the spider-web scene): flying lets the whole level be crossed. Leaving the mode drops him back under the game's control. The mod never faulted.
* **Tests** (`tests/test_castle_debug_fly.py`, 12, mock ABI 2 host with declared ranges enforced; CI requires them): edge toggle, start position, the game sees no button, 3/6 px steps in all eight directions, fractions and velocity cleared every frame, the frame-end re-assert after a simulated collision correction, screen margins and the signed vertical scroll, the camera never written, power only while flying and alive, no write after leaving, only declared ranges, save/restore, corrupt state, manifest scope. Mutation checks caught: removing the margin, the frame-end re-assert, and the velocity clear.

## Limits
* Flying above the top of a level's map shows blank tiles (the map has nothing there); vertical-scroll levels were not exercised beyond the signed-scroll arithmetic test. Only one level was flown through on the real image.
* The mode is for exploration: entering a boss arena, a cutscene trigger or a level exit while flying does whatever the game does (the first level's exit worked).
* Validated against product `marinocg/segarecomp` main `8d419ab` for the image `Castle of Illusion (USA, Europe)` `2d535ff7...c47c4f` only. Package identity `05a3138a6cca5f9f1a1c20e0e5da4a462e11115a738dc980cc4831785f18613f` (deterministic). Unpublished source project: no `release.json`, no catalog entry. Native code is host code: the user approves the exact package identity.
