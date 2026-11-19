#!/usr/bin/env python3
"""Turns the viewer's standard-error log of a session recorded with the Castle input recorder package into guest-frame-keyed pad scripts.

  record_to_pad_script.py <viewer-stderr.log> --out <prefix>

writes  <prefix>.viewer.txt   one `<frame> <buttons>` line per change (buttons: U D L R A B C S, `-` for none): SEGARECOMP_VIEWER_PAD_SCRIPT=<file> for the real viewer
        <prefix>.headless.txt `<frame>:1:0x<mask>,...`: SEGARECOMP_PAD_SCRIPT for a headless capture program (player 2 entries use player 2)
        <prefix>.summary.json frames, entries, length: no commercial data is contained in any of these files (button masks and frame numbers only)."""
import argparse, json, re, sys

BITS = [(0x01, "U"), (0x02, "D"), (0x04, "L"), (0x08, "R"), (0x40, "A"), (0x10, "B"), (0x20, "C"), (0x80, "S")]


def parse(text):
    out = []
    for m in re.finditer(r'"line":"REC (\d+) ([0-9a-f]{2}) ([0-9a-f]{2})"', text):
        out.append((int(m.group(1)), int(m.group(2), 16), int(m.group(3), 16)))
    return out


def letters(mask): return "".join(c for b, c in BITS if mask & b) or "-"


def convert(entries):
    viewer, headless = [], []
    last1 = last2 = None
    prev = -1
    for frame, p1, p2 in entries:
        if frame < prev: raise SystemExit("the frame numbers go backwards (%d after %d): a save state was loaded or the game was rewound during the recording; a recorded route must be played straight through" % (frame, prev))
        prev = frame
        if p1 != last1: viewer.append("%d %s" % (frame, letters(p1))); headless.append("%d:1:0x%02x" % (frame, p1)); last1 = p1
        if p2 != last2: headless.append("%d:2:0x%02x" % (frame, p2)); last2 = p2
    return viewer, headless


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("log"); ap.add_argument("--out", required=True); ap.add_argument("--quit-after", type=int, default=120, help="frames after the last recorded change at which the viewer script quits (a `Q` line); 0 = none"); a = ap.parse_args()
    entries = parse(open(a.log, errors="replace").read())
    if not entries: sys.exit("no REC lines found: was the recorder package installed and the viewer's standard error saved?")
    viewer, headless = convert(entries)
    if a.quit_after > 0: viewer.append("%d Q" % (entries[-1][0] + a.quit_after))
    open(a.out + ".viewer.txt", "w").write("\n".join(viewer) + "\n")
    open(a.out + ".headless.txt", "w").write(",".join(sorted(headless, key=lambda s: int(s.split(":")[0] if ":" in s else s.split()[0]))))
    json.dump({"entries": len(entries), "first_frame": entries[0][0], "last_frame": entries[-1][0]}, open(a.out + ".summary.json", "w"))
    print("recorded %d changes, frames %d..%d" % (len(entries), entries[0][0], entries[-1][0]))
    if len(viewer) > 1024: print("WARNING: %d viewer entries: the viewer's pad-script holds at most 1024 lines; split the session or replay it headless (limit 4096 entries)" % len(viewer), file=sys.stderr)
    if len(headless) > 4096: print("WARNING: %d headless entries: the product's pad script holds at most 4096" % len(headless), file=sys.stderr)
