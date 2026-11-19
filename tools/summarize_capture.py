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


if __name__ == "__main__":
    text = open(sys.argv[1], errors="replace").read() if len(sys.argv) > 1 else sys.stdin.read()
    j, rows, events = summarize(text)
    print("outcome %s, %d samples, final work-RAM SHA-256 %s" % (j["outcome"], len(rows), j.get("final_work_ram_sha256", "")))
    print("sample   score power level  x     y     camera")
    for r in rows: print("%-8d %-6d %-5d %02x%02x  %-5d %-5d %d" % ((r["ordinal"], r["score"], r["power"]) + r["level"] + (r["x"], r["y"], r["cam"])))
    print("events:", events if events else "none")
