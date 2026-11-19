#!/usr/bin/env python3
"""Summarizes a headless replay of a recorded route: the work-RAM observables the product's capture facility samples (SEGARECOMP_CAPTURE_RAM) into a time series and an event list. Reads the program's standard error (the `CAPTURE_SUMMARY {...}` line).

The regions MUST be requested exactly as REGIONS below (the replay instructions in the recorder README do):
  score (u32 at 0xF22C), the five HUD power slot words (0xF244..0xF24D; a filled slot is 0x807C), the level and stage words (0xFF44, 0xFF46), Mickey's x and y (0xDC10, 0xDC14) and the camera x (0xFA84).
Everything printed is a game-state number (no ROM bytes, no pixels)."""
import json, re, sys

REGIONS = "62508:4,62020:10,65348:4,56336:2,56340:2,64132:2"     # = 0xF22C:4, 0xF244:10, 0xFF44:4, 0xDC10:2, 0xDC14:2, 0xFA84:2 (decimal offsets, as the product's option wants)


def decode(sample_hex):
    b = bytes.fromhex(sample_hex)
    score = int.from_bytes(b[0:4], "big")
    power = sum(1 for i in range(5) if int.from_bytes(b[4 + 2 * i:6 + 2 * i], "big") == 0x807C)
    level = (int.from_bytes(b[14:16], "big"), int.from_bytes(b[16:18], "big"))
    x, y, cam = (int.from_bytes(b[18:20], "big"), int.from_bytes(b[20:22], "big"), int.from_bytes(b[22:24], "big"))
    return dict(score=score, power=power, level=level, x=x, y=y, cam=cam)


def summarize(text):
    m = re.search(r"CAPTURE_SUMMARY (\{.*\})", text)
    if not m: raise SystemExit("no CAPTURE_SUMMARY line found")
    j = json.loads(m.group(1))
    regions = ",".join("%d:%d" % (r["offset"], r["length"]) for r in j.get("ram_regions", []))
    if regions != REGIONS: raise SystemExit("the capture was not made with SEGARECOMP_CAPTURE_RAM=%s (got %s)" % (REGIONS, regions))
    first, stride = j["first_frame"], j["frame_stride"]
    rows = []
    for i, s in enumerate(j["ram_frames"]):
        d = decode(s); d["ordinal"] = first + i * stride; rows.append(d)
    events = []
    for a, b in zip(rows, rows[1:]):
        if b["score"] != a["score"]: events.append((b["ordinal"], "score %d -> %d" % (a["score"], b["score"])))
        if b["power"] < a["power"]: events.append((b["ordinal"], "damage: power %d -> %d" % (a["power"], b["power"])))
        if b["power"] > a["power"]: events.append((b["ordinal"], "power %d -> %d" % (a["power"], b["power"])))
        if b["level"] != a["level"]: events.append((b["ordinal"], "level %02x%02x -> %02x%02x" % (a["level"] + b["level"])))
    return j, rows, events


def accept(j, summary):
    """The headless acceptance checks against the recording's summary.json: the run completed its capture window, every pad entry was applied, and the last sample is exactly the END frame. Returns a list of failures."""
    bad = []
    if j.get("outcome") != "window_complete": bad.append("outcome is %r, not window_complete" % j.get("outcome"))
    if j.get("frames_captured") != summary["capture_count"]: bad.append("captured %s frames, expected %d" % (j.get("frames_captured"), summary["capture_count"]))
    if (j.get("first_frame"), j.get("frame_stride"), j.get("frame_count")) != (summary["capture_first"], summary["capture_stride"], summary["capture_count"]): bad.append("the capture window is not the recording's (first/stride/count)")
    last = j.get("first_frame", 0) + j.get("frame_stride", 0) * (j.get("frames_captured", 0) - 1)
    if last != summary["end"]: bad.append("the last sample is frame %s, not the recording's END frame %d" % (last, summary["end"]))
    if j.get("pad_entries_applied") != summary["expected_pad_entries"]: bad.append("%s pad entries applied, expected %d (the script was truncated or not fully reached)" % (j.get("pad_entries_applied"), summary["expected_pad_entries"]))
    return bad


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("capture"); ap.add_argument("--recording", help="the recording's .summary.json: enables the acceptance checks (exit status 1 on any failure)")
    a = ap.parse_args()
    text = open(a.capture, errors="replace").read()
    j, rows, events = summarize(text)
    print("outcome %s, %d samples, final work-RAM SHA-256 %s" % (j["outcome"], len(rows), j.get("final_work_ram_sha256", "")))
    print("sample   score power level  x     y     camera")
    for r in rows: print("%-8d %-6d %-5d %02x%02x  %-5d %-5d %d" % ((r["ordinal"], r["score"], r["power"]) + r["level"] + (r["x"], r["y"], r["cam"])))
    print("events:", events if events else "none")
    if a.recording:
        bad = accept(j, json.load(open(a.recording)))
        for b in bad: print("ACCEPTANCE FAILED:", b)
        if not bad: print("acceptance: the run completed, applied all %d pad entries and its last sample is the END frame" % j["pad_entries_applied"])
        sys.exit(1 if bad else 0)
