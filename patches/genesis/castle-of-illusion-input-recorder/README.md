# Castle of Illusion: input recorder and replay instructions (a developer tool, not a game change)

The product has **no Genesis "record this session" feature** (the Sega CD viewer has one; see `docs/product/sega-cd-play.md` in the product). For Genesis it has two replay inputs: the headless capture program's `SEGARECOMP_PAD_SCRIPT` (frame-keyed, `<frame>:<player>:<mask>`) and the viewer's `SEGARECOMP_VIEWER_PAD_SCRIPT` (`<frame> <buttons>`). What was missing is a way for a **human** to produce such a script. This package fills that gap **with existing facilities only**: a native ABI 2 mod with just `input.read` + `host.log` logs a line `REC <guest frame> <pad1> <pad2>` whenever a controller changes (it writes nothing, intercepts nothing: the guest plays exactly as without it), the viewer prints it on standard error, and `tools/record_to_pad_script.py` turns it into both script formats. A focused product task (a Genesis "Record this session" like Sega CD's) would remove the mod and the converter; until then this is the minimal route.

## Verified (private image, aggregates only)
A scripted session recorded with this package and replayed (1) in the real viewer with the converted viewer script and (2) through the headless frame-keyed path reproduced the recorded end state exactly (Mickey x=1032, y=176, camera 904, frame counter equal; the whole-RAM hash differs only in 14 stack/transient bytes because the two binaries stop at different instruction points). **The recorded frame numbers are directly the replay keys (no offset)**: shifting them by 1, 2 or 3 frames changed the result. Replaying the same recording headless against the original and the 16:9, 21:9 and 32:9 activation variants gave the identical state over that early stretch (the activation variants differ only when their extra objects matter). Tests: `tests/test_input_recorder.py` (provider on the mock host, converter, summarizer, refusal of a rewound session).

## 1. Build the recorder viewer (once)
```
PRODUCT=/path/to/segarecomp            # a built checkout (cmake --build ... --target segarecomp); SDL3=/path/to/sdl3-prefix
CLI=$PRODUCT/build/apps/segarecomp/segarecomp
ROM="/path/to/Castle of Illusion Starring Mickey Mouse (USA, Europe).md"      # your own legally held image; it never leaves your machine
$CLI mod build patches/genesis/castle-of-illusion-input-recorder --out recorder.segapatch --cc cc --sdk-dir $PRODUCT/platforms
ID=$($CLI mod inspect --json recorder.segapatch | python3 -c 'import sys,json;print(json.load(sys.stdin)["package_identity"])')
$CLI build --rom "$ROM" --output build-recorder --cc cc --runtime-dir $PRODUCT/platforms/genesis \
  --sdl3-include $SDL3/include --sdl3-lib $SDL3/lib --native-package recorder.segapatch --native-identity $ID
```
(The launcher's install-and-approve flow accepts the same package; where the launcher stores a run's standard error was not verified, so the command line is the documented route.)

## 2. Record (you play)
```
SEGARECOMP_REWIND=0 LD_LIBRARY_PATH=$SDL3/lib ./build-recorder/game --instruction-budget 4000000000 2> session.log
```
Keys (the viewer's fixed map): arrows = D-pad, **Z = A, X = B, C = C, Return = Start**; Esc quits. Rules: **play straight through from power-on** (the recording starts at guest frame 0 and replays from boot); **do not use quick save/load or rewind** (F5/F8/rewind repeat frame numbers; the converter refuses such a session); do not close the window until the scenario is done. The first title/intro screens take about 1,800 frames: press Start as you normally would.
```
python3 tools/record_to_pad_script.py session.log --out routes/items-01        # -> .viewer.txt  .headless.txt  .summary.json (button masks and frame numbers only: no commercial data)
```
Limits: the viewer script holds 1,024 lines and the headless script 4,096 entries (the converter warns); a headless capture takes at most 64 sampled frames per run.

## 3. What to record (one recording per scenario; keep each short and note the intent in the file name)
1. **items-01 - item collection**: in the first level collect several apples/gems and at least one power-up; end by standing still for 2 s.
2. **damage-01 - damage to Mickey and to an enemy**: let one enemy hit Mickey (power drops), hit another enemy by jumping on it or throwing an apple (score rises).
3. **platforms-01 - collisions and moving platforms**: climb ledges, ride a moving platform, push against a wall, fall into and out of a pit if the level has one (a death/restart is a valid part of the route).
4. **boss-01 - a boss fight to completion**: the first world's boss (or any boss you can beat); finish the fight and stay for the end-of-boss sequence.
5. **progress-01 - natural stage progression**: play a whole stage to its exit, through the transition into the next stage, and 10 s further.
Do **not** use the debug free-fly package for any of these: traversal with it is not evidence of normal gameplay.

## 4. Replay and compare
Viewer (you watch it; against the original and any activation variant, built as in the activation READMEs with `--native-package`):
```
SEGARECOMP_REWIND=0 SEGARECOMP_VIEWER_PAD_SCRIPT=routes/items-01.viewer.txt LD_LIBRARY_PATH=$SDL3/lib ./build-X/game --instruction-budget 4000000000
```
Headless observables (a standard headless program: the same `build` without the SDL flags; for an activation variant first `mod apply` it to a ROM and build that ROM, which is what the activation tests do):
```
$CLI build --rom "$ROM" --output build-headless --cc cc --runtime-dir $PRODUCT/platforms/genesis
SEGARECOMP_CAPTURE_DIR=out SEGARECOMP_CAPTURE_FIRST=<first frame> SEGARECOMP_CAPTURE_COUNT=64 SEGARECOMP_CAPTURE_STRIDE=<every n-th frame> SEGARECOMP_CAPTURE_SLICE=500 \
SEGARECOMP_CAPTURE_RAM="62508:4,62020:10,65348:4,56336:2,56340:2,64132:2" SEGARECOMP_PAD_SCRIPT="$(cat routes/items-01.headless.txt)" \
  ./build-headless/game --instruction-budget 4000000000 2> cap.txt
python3 tools/summarize_capture.py cap.txt
```
The summary lists score, power (filled HUD slots), level/stage, Mickey's x/y and the camera at each sampled frame and the events between them (score change = item/enemy, power drop = damage, level change = natural progression). Compare the original, the presentation-only package (its guest is the original: same result by construction) and each activation variant: **differences are expected where activation changes which objects exist; a route that stops progressing, a missing essential object, or a reward counted twice is a failure.** The route and the summary are the evidence to attach; the session log, the image and any screenshot stay private.

## Limits
The HUD item counter's RAM address is not identified (items show in the HUD frames; use viewer captures or the score), so "item collected" is judged by the score/HUD; a boss completion is judged by the end-of-boss level/score events. Replay keys are guest frames: they stay valid only for the same image and the same boot (recordings are not portable across revisions).

Package identity `d60da971eef70a4cf562b5219976738225a4b3dd80071c07aad2dd2206ab5dfb` (deterministic; `mod inspect` prints it). Unpublished source project; native code is host code: approve the exact identity.
