# Castle of Illusion: input recorder (a TEMPORARY developer tool, not a game change)

Temporary stop-gap until the product has a Genesis session recorder (backlog task **SEG-146-T006**, "Generic guest-frame session recording and replay in the shared viewer"; delete this package when it lands). The product's Sega CD viewer records (`--record`/`--replay`); Genesis only replays: headless `SEGARECOMP_PAD_SCRIPT` (**guest-frame-keyed, exact**, 4,096 entries) and the viewer's `SEGARECOMP_VIEWER_PAD_SCRIPT` (**keyed by host poll, approximate**, 1,024 lines). This package lets a human produce the exact kind with existing facilities only.

## What it does
A native ABI 2 mod with `input.read` + `host.log` only (writes nothing, intercepts nothing: the guest plays exactly as without it). On the viewer's standard error it logs, per **guest frame**: `START <f>`, `REC <f> <pad1> <pad2>` on every change of either port, `TICK <f>` every 300 frames, and `END <f>` when **player 2 presses Start** (keyboard: **Right Shift**), after which it logs nothing. `END` is the explicit endpoint, so the recording keeps its full duration including unchanged input after the last button change; `TICK` makes a lost log detectable.
`tools/record_to_pad_script.py` converts the log and **refuses** (writes nothing) a recording that is incomplete (no END), has several STARTs (guest reset), repeats or reverses frame numbers (quick-load, rewind, duplicate log), has lines after END or a gap over 600 frames, or exceeds the replay capacity (viewer 1,024 lines, headless 4,096 entries). Player 2's Start is stripped from the scripts; held buttons are released at END.

| output | use | exactness |
|---|---|---|
| `<prefix>.headless.txt` | `SEGARECOMP_PAD_SCRIPT` of a headless capture program, both ports | **exact** guest-frame replay |
| `<prefix>.viewer.txt` | `SEGARECOMP_VIEWER_PAD_SCRIPT` (player 1 only, ends with `Q`) | **approximate** (host-poll keyed): to watch a route, never to prove one |
| `<prefix>.summary.json` | start, end, duration in guest frames | - |

Tests: `tests/test_input_recorder.py` (provider on the mock host: START/changes/TICK/END, both ports, nothing after END, no writes; converter: complete, duration beyond the last change, final held buttons, each refusal, both capacity limits, command line). On the real image (private): START/REC/TICK lines appear at guest frames and a session without END is refused; an END from the real keyboard is covered by the mock tests only (not exercised on the real viewer).

## 1. Build the recorder viewer (once)
```
PRODUCT=/path/to/segarecomp   SDL3=/path/to/sdl3-prefix   # PRODUCT: built checkout of marinocg/segarecomp main (cmake --build build)
CLI=$PRODUCT/build/apps/segarecomp/segarecomp
ROM="/path/to/Castle of Illusion Starring Mickey Mouse (USA, Europe).md"      # your own image; sha256 2d535ff7eda650a64a9093ba6fabf8d5ac87801b898a76b591db41a1c8e47c4f; it never leaves your machine
$CLI mod build patches/genesis/castle-of-illusion-input-recorder --out recorder.segapatch --cc cc --sdk-dir $PRODUCT/platforms
ID=$($CLI mod inspect --json recorder.segapatch | python3 -c 'import sys,json;print(json.load(sys.stdin)["package_identity"])')   # must print the identity at the end of this file
$CLI build --rom "$ROM" --output build-recorder --cc cc --runtime-dir $PRODUCT/platforms/genesis \
  --sdl3-include $SDL3/include --sdl3-lib $SDL3/lib --native-package recorder.segapatch --native-identity $ID
```

## 2. Record the shortest useful scenario (about 2-3 minutes of play)
```
SEGARECOMP_REWIND=0 LD_LIBRARY_PATH=$SDL3/lib ./build-recorder/game --instruction-budget 4000000000 2> session.log
```
Keys: arrows, **Z = A (jump), X = B, C = C, Return = Start**; **Right Shift = player 2 Start = END**; Esc quits. Play **straight from power-on**: no F5/F8 quick save/load, no rewind (the converter refuses such a session), no reset. Play Start through the title screens as usual (about 30 s), then **in the first level**: walk right; **collect an apple or gem** (score changes); **jump on or hit an enemy** (score); **take one hit** (power drops); cross a ledge or a moving platform; keep going about 30 s. **Press Right Shift** (hold it for a moment) at the point you want the recording to stop, then close with Esc. Record a second, longer one for the boss and stage transition only after this one replays correctly.
```
python3 tools/record_to_pad_script.py session.log --out routes/first-level-01      # prints the complete duration, or REFUSED: <reason>
```
Keep `routes/*` and `session.log` private if you prefer; they contain button masks and frame numbers only (no commercial data).

## 3. Replay (exact, headless) against the original, the presentation-only package and each activation variant
Build one headless program per image once. A **headless program is built from an image**: the original from `$ROM`; an activation variant from the ROM the package produces (`mod apply`); the presentation-only package changes no guest bytes (its image equals the original), so it replays on the original build (its output is the original's by construction; to also confirm the package builds, run `$CLI mod apply` and compare the effective hash with the original's).
```
$CLI build --rom "$ROM" --output build-orig --cc cc --runtime-dir $PRODUCT/platforms/genesis
for v in 16x9 21x9 32x9; do
  $CLI mod apply patches/genesis/castle-of-illusion-activation-$v --rom "$ROM" --out eff-$v.md      # effective images: 16x9 10a2c1ad..., 21x9 32a03d32..., 32x9 9d8a6098...
  $CLI build --rom eff-$v.md --output build-$v --cc cc --runtime-dir $PRODUCT/platforms/genesis
done
END=$(python3 -c 'import json;print(json.load(open("routes/first-level-01.summary.json"))["end"])')
for b in orig 16x9 21x9 32x9; do
  mkdir -p out-$b
  SEGARECOMP_CAPTURE_DIR=out-$b SEGARECOMP_CAPTURE_FIRST=60 SEGARECOMP_CAPTURE_COUNT=64 SEGARECOMP_CAPTURE_STRIDE=$(( END / 64 + 1 )) SEGARECOMP_CAPTURE_SLICE=500 \
  SEGARECOMP_CAPTURE_RAM="62508:4,62020:10,65348:4,56336:2,56340:2,64132:2" SEGARECOMP_PAD_SCRIPT="$(cat routes/first-level-01.headless.txt)" \
    timeout 1800 ./build-$b/game --instruction-budget 4000000000 2> cap-$b.txt
  python3 tools/summarize_capture.py cap-$b.txt > summary-$b.txt
done
```
`summary-*.txt` lists, per sampled frame, score, power, level/stage, Mickey x/y and camera, and the events (score change, damage, level change). **Differences between the original and a variant are expected only where activation changes which objects exist; a route that stops progressing, a missing essential object, or a reward counted twice is a failure.** Checked with a scripted 3,700-frame route: original and 16:9 gave identical sampled observables (the whole-RAM hash differs, as the activation state lives in RAM). The recording is replayed against the activation variants as a **fixture, not as proof**: a variant that diverges earlier than the route's last frame needs a look at what differed.
Viewer replay (to watch, any variant): `SEGARECOMP_REWIND=0 SEGARECOMP_VIEWER_PAD_SCRIPT=routes/first-level-01.viewer.txt LD_LIBRARY_PATH=$SDL3/lib ./build-X/game --instruction-budget 4000000000` with a viewer build of that image (`--sdl3-include/--sdl3-lib`); it can drift by a few frames and is not evidence.

## Limits
The HUD item counter's RAM address is not identified (judged from score/HUD). Replay keys are guest frames and valid only for the same image and boot. A recording for another variant's frame timing may diverge: that is the information being collected. The capture facility samples at most 64 frames per run. The launcher GUI route is not covered.

Recorder package identity `f58a9653d6b553aded49b23d8c231f203e4e717b8a4d06a13cfd2e6830d34def` (deterministic). Unpublished source project, no catalog entry; native code is host code: approve the exact identity.
