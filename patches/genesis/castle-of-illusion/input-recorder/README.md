# Castle of Illusion: input recorder (a TEMPORARY developer tool, not a game change)

Temporary stop-gap until the product has a Genesis session recorder (backlog task **SEG-146-T006**, "Generic guest-frame session recording and replay in the shared viewer"; delete this package when it lands). The product's Sega CD viewer records (`--record`/`--replay`); Genesis only replays: headless `SEGARECOMP_PAD_SCRIPT` (**guest-frame-keyed**, 4,096 entries) and the viewer's `SEGARECOMP_VIEWER_PAD_SCRIPT` (1,024 lines, player 1 only; each line is keyed by the **published frame sequence when the viewer has one attached and by host poll otherwise**, so a build without the sequence can drift). This package lets a human produce the exact kind with existing facilities only.

## What it does
A native ABI 2 mod with `input.read` + `host.log` only (writes nothing, intercepts nothing: the guest plays exactly as without it). On the viewer's standard error it logs, per **guest frame**: `START <f>`, `REC <f> <pad1> <pad2>` on every change of either port, `TICK <f>` every 300 frames, and `END <f>` when **player 2 presses Start** (keyboard: **Right Shift**), after which it logs nothing. If the host **loads a state** (quick-load, rewind, restore) the provider's load callback logs `LOAD <f>` and stops: the recording is explicitly invalid (timestamps and heartbeats alone cannot detect every restore). `END` is the explicit endpoint, so the recording keeps its full duration including unchanged input after the last button change; `TICK` makes a lost log detectable.
`tools/record_to_pad_script.py` converts the log and **refuses** (writes nothing) a recording that has no valid initial controller sample at the START frame (the first REC must be at START's frame), a malformed line, a LOAD line, is incomplete (no END), has several STARTs (guest reset), repeats or reverses frame numbers (quick-load, rewind, duplicate log), has lines after END or a gap over 600 frames, or exceeds the replay capacity (viewer 1,024 lines, headless 4,096 entries). Player 2's Start is stripped from the scripts. **No entry is keyed at END** (the headless run stops there; a release keyed at END may or may not be applied before the capture returns, so the acceptance count must not depend on it), and `capture_first` is never 0 (the product rejects it).

| output | use | exactness |
|---|---|---|
| `<prefix>.headless.txt` | `SEGARECOMP_PAD_SCRIPT` of a headless capture program, both ports | the acceptance path: guest-frame replay validated by `summarize_capture.py --recording` |
| `<prefix>.viewer.txt` | `SEGARECOMP_VIEWER_PAD_SCRIPT` (player 1 only, ends with `Q`) | a watching aid (frame sequence when attached, host polls otherwise); no acceptance claim |
| `<prefix>.summary.json` | start, end, duration, the capture window (first/count/stride; its **last sample is exactly the END frame**) and the expected pad-entry count | - |

Tests: `tests/test_input_recorder.py` (provider on the mock host: START/changes/TICK/END, both ports, nothing after END, no writes; converter: complete, duration beyond the last change, final held buttons, each refusal, both capacity limits, command line). On the real image (private, real SDL viewer under a virtual X display, synthetic X key events): START/REC/TICK lines appear at guest frames, **Right Shift produced `END 1584`** and the converter accepted that log; a session without END is refused. A real quick-load was **not** reproduced (no save location is configured in that setup, so F5/F8 did nothing there); the LOAD path is covered by the mock tests (`load_state` callback) only.

## 1. Build the recorder viewer (once)
```
PRODUCT=/path/to/segarecomp   SDL3=/path/to/sdl3-prefix   # PRODUCT: built checkout of marinocg/segarecomp main (cmake --build build)
CLI=$PRODUCT/build/apps/segarecomp/segarecomp
ROM="/path/to/Castle of Illusion Starring Mickey Mouse (USA, Europe).md"      # your own image; sha256 2d535ff7eda650a64a9093ba6fabf8d5ac87801b898a76b591db41a1c8e47c4f; it never leaves your machine
$CLI mod build patches/genesis/castle-of-illusion/input-recorder --out recorder.segapatch --cc cc --sdk-dir $PRODUCT/platforms
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
  $CLI mod apply patches/genesis/castle-of-illusion/activation-$v --rom "$ROM" --out eff-$v.md      # effective images: 16x9 10a2c1ad..., 21x9 32a03d32..., 32x9 9d8a6098...
  $CLI build --rom eff-$v.md --output build-$v --cc cc --runtime-dir $PRODUCT/platforms/genesis
done
read FIRST COUNT STRIDE < <(python3 -c 'import json;d=json.load(open("routes/first-level-01.summary.json"));print(d["capture_first"],d["capture_count"],d["capture_stride"])')   # the last sample is exactly the END frame
for b in orig 16x9 21x9 32x9; do
  mkdir -p out-$b
  SEGARECOMP_CAPTURE_DIR=out-$b SEGARECOMP_CAPTURE_FIRST=$FIRST SEGARECOMP_CAPTURE_COUNT=$COUNT SEGARECOMP_CAPTURE_STRIDE=$STRIDE SEGARECOMP_CAPTURE_SLICE=500 \
  SEGARECOMP_CAPTURE_RAM="62508:4,62020:10,65348:4,56336:2,56340:2,64132:2" SEGARECOMP_PAD_SCRIPT="$(cat routes/first-level-01.headless.txt)" \
    timeout 1800 ./build-$b/game --instruction-budget 4000000000 2> cap-$b.txt
  python3 tools/summarize_capture.py cap-$b.txt --recording routes/first-level-01.summary.json > summary-$b.txt || echo "ACCEPTANCE FAILED for $b: see summary-$b.txt"
done
```
Each run is **accepted only if** `summarize_capture.py --recording` exits 0: the capture window completed (`window_complete`, all frames captured), every pad entry was applied (a truncated or unreached script fails), and the **last sample is exactly the recording's END frame**. A failed acceptance means the replay itself is invalid (not a game finding).

**What acceptance does not prove.** The product's headless script applies each entry **between dispatch slices** (`SEGARECOMP_CAPTURE_SLICE` dispatches, the first slice start whose virtual frame has reached the entry's frame), not at an exact frame boundary, so an entry can take effect up to one slice late. An applied-entry count only shows the script was consumed; it does **not** establish exact frame-boundary determinism. A smaller `SEGARECOMP_CAPTURE_SLICE` narrows the jitter; exact boundary replay is deferred to SEG-146-T006 (the capture runtime is not changed in W04). Capture ordinals are publication counts, taken as equal to the recorder's guest frame numbers (consistent with every scripted comparison made here, not proven independently).
`summary-*.txt` lists, per sampled frame, score, power, level/stage, Mickey x/y and camera, and the events (score change, damage, level change). **Differences between the original and a variant are expected only where activation changes which objects exist; a route that stops progressing, a missing essential object, or a reward counted twice is a failure.** Checked with a scripted 3,700-frame route: original and 16:9 gave identical sampled observables (the whole-RAM hash differs, as the activation state lives in RAM). The recording is replayed against the activation variants as a **fixture, not as proof**: a variant that diverges earlier than the route's last frame needs a look at what differed.
Viewer replay (to watch, any variant; keyed by the published frame sequence when attached, host polls otherwise; not acceptance evidence): `SEGARECOMP_REWIND=0 SEGARECOMP_VIEWER_PAD_SCRIPT=routes/first-level-01.viewer.txt LD_LIBRARY_PATH=$SDL3/lib ./build-X/game --instruction-budget 4000000000` with a viewer build of that image (`--sdl3-include/--sdl3-lib`); 

## Limits
The HUD item counter's RAM address is not identified (judged from score/HUD). Replay keys are guest frames and valid only for the same image and boot. A recording for another variant's frame timing may diverge: that is the information being collected. The capture facility samples at most 64 frames per run. The launcher GUI route is not covered.

Recorder package identity `0cc17b89e8a2522236361915c963c006dc840fb34ba21c74c1b78a57601ca5df` (deterministic). Unpublished source project, no catalog entry; native code is host code: approve the exact identity.
