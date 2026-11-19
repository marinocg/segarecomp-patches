#!/usr/bin/env python3
"""Turns the viewer's standard-error log of a session recorded with the Castle input recorder package into guest-frame-keyed pad scripts.

  record_to_pad_script.py <viewer-stderr.log> --out <prefix>

The log must be one complete, straight-through recording: `START <f>`, `REC <f> <p1> <p2>` per change, `TICK <f>` heartbeats, one `END <f>` (the recorder's explicit end: player 2 pressed Start). Anything else is REFUSED (no script is written):
no START, no valid initial sample at the START frame, no END (incomplete: the window was closed early), a LOAD line (a state was loaded), a malformed line, more than one START (the guest was reset), frame numbers that repeat or go backwards (quick-load, rewind, or a duplicated log), lines after END, a gap above 600 frames between any two lines (lost log lines), or a script over the runtime's capacity.
Outputs (button masks and frame numbers only: no commercial data):
  <prefix>.headless.txt   `<frame>:<player>:0x<mask>,...` for SEGARECOMP_PAD_SCRIPT of a headless capture program. EXACT: the headless path applies each entry at its guest frame. Player 2's Start (the end marker) is removed; all held buttons are released at END.
  <prefix>.viewer.txt     `<frame> <buttons>` (U D L R A B C S, `-` none) for SEGARECOMP_VIEWER_PAD_SCRIPT. The viewer keys each line by the published frame sequence when one is attached and by host poll otherwise (a build without it can drift): the file is a watching aid; the headless replay is the acceptance path. Player 1 only. Ends with a `Q` line at END.
  <prefix>.summary.json   start, end (= the session's duration in guest frames), entries per script, and the capture window (first/count/stride) whose LAST sample is exactly the END frame, plus the pad-entry count a replay must report."""
import argparse, json, re, sys

BITS = [(0x01, "U"), (0x02, "D"), (0x04, "L"), (0x08, "R"), (0x40, "A"), (0x10, "B"), (0x20, "C"), (0x80, "S")]
P2_START = 0x80
MAX_VIEWER, MAX_HEADLESS, MAX_GAP = 1024, 4096, 600      # viewer pad script lines; product headless pad script entries; heartbeat is every 300 frames
ANY = re.compile(r'"line":"((?:START|REC|TICK|END|LOAD)\b[^"]*)"')
GOOD = re.compile(r"(START|TICK|END|LOAD) (\d+)|REC (\d+) ([0-9a-f]{2}) ([0-9a-f]{2})")


class Refused(Exception): pass


def parse(text):
    out = []
    for m in ANY.finditer(text):
        g = GOOD.fullmatch(m.group(1))
        if g is None: raise Refused("malformed recorder line %r" % m.group(1))
        if g.group(1): out.append((g.group(1), int(g.group(2)), 0, 0))
        else: out.append(("REC", int(g.group(3)), int(g.group(4), 16), int(g.group(5), 16)))
    return out


def validate(ev):
    if not ev or ev[0][0] != "START": raise Refused("no START line first: the recorder package was not installed, or the log is not from power-on")
    if sum(1 for e in ev if e[0] == "START") != 1: raise Refused("more than one START: the guest was reset during the session; record straight through from power-on")
    if any(e[0] == "LOAD" for e in ev): raise Refused("a state was loaded (quick-load, rewind or restore): the recording is invalid; record straight through")
    if len(ev) < 2 or ev[1][0] != "REC" or ev[1][1] != ev[0][1]: raise Refused("no valid initial controller sample at the START frame")
    ends = [e for e in ev if e[0] == "END"]
    if not ends: raise Refused("incomplete recording: no END line (press player 2's Start to end a recording; closing the window early loses the duration)")
    if len(ends) != 1 or ev[-1][0] != "END": raise Refused("lines follow END or END is duplicated")
    prev = None
    for k, f, _, _ in ev:
        if prev is not None:
            if f < prev: raise Refused("frame numbers go backwards (%d after %d): a quick-load, rewind or save state was used; record straight through" % (f, prev))
            if f - prev > MAX_GAP: raise Refused("a gap of %d frames without a line (heartbeat is 300): the log lost lines" % (f - prev))
        prev = f
    seen = set()
    for k, f, _, _ in ev:
        if k == "REC":
            if f in seen: raise Refused("two REC lines for frame %d: duplicated frame numbers" % f)
            seen.add(f)
    return ev[0][1], ends[0][1]


def convert(ev):
    start, end = validate(ev)
    viewer, headless, l1, l2 = [], [], None, None
    for k, f, p1, p2 in ev:
        if k != "REC": continue
        p2 &= ~P2_START
        if p1 != l1: viewer.append("%d %s" % (f, letters(p1))); headless.append((f, 1, p1)); l1 = p1
        if p2 != l2: headless.append((f, 2, p2)); l2 = p2
    for pl, last in ((1, l1), (2, l2)):                  # final held buttons: released at END so a longer replay does not hold them
        if last: headless.append((end, pl, 0))
    if l1: viewer.append("%d -" % end)
    viewer.append("%d Q" % end)
    if len(viewer) > MAX_VIEWER: raise Refused("%d viewer lines exceed the viewer's pad-script capacity (%d): record a shorter route or replay it headless" % (len(viewer), MAX_VIEWER))
    if len(headless) > MAX_HEADLESS: raise Refused("%d entries exceed the headless pad-script capacity (%d): record a shorter route" % (len(headless), MAX_HEADLESS))
    return start, end, viewer, ["%d:%d:0x%02x" % h for h in headless]


def letters(mask): return "".join(c for b, c in BITS if mask & b) or "-"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("log"); ap.add_argument("--out", required=True); a = ap.parse_args()
    try: start, end, viewer, headless = convert(parse(open(a.log, errors="replace").read()))
    except Refused as e: sys.exit("REFUSED: %s" % e)
    open(a.out + ".viewer.txt", "w").write("\n".join(viewer) + "\n")
    open(a.out + ".headless.txt", "w").write(",".join(headless))
    count = 64 if end >= 63 else 1; stride = max(1, end // 63); first = max(0, end - stride * (count - 1))      # the last capture sample is exactly the END frame
    json.dump({"start": start, "end": end, "duration_frames": end - start, "headless_entries": len(headless), "viewer_lines": len(viewer),
               "capture_first": first, "capture_count": count, "capture_stride": stride, "capture_last": first + stride * (count - 1), "expected_pad_entries": len(headless)}, open(a.out + ".summary.json", "w"))
    print("complete recording: guest frames %d..%d (%.1f s), %d headless entries, %d viewer lines" % (start, end, (end - start) / 60.0, len(headless), len(viewer)))
