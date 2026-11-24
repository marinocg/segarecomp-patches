#!/usr/bin/env python3
"""LOCAL visual diagnosis of the Sonic 1 ABI 2 scenery conflict (SEG-152-T009). Needs a product checkout, the legally held Sonic 1 image and a compiler; never run by public CI.

  sonic1_conflict_diagnosis.py --product-root DIR --cli BIN --sdl DIR --cc CC --rom IMAGE --work DIR --diag DIR_OUTSIDE_THE_REPOSITORY

It builds the ABI 1 package, the internal ABI 2 port and an INSTRUMENTED copy of that port (a text edit of the same source that only adds log lines: it changes no answer), plays the same scripted Green Hill run in all of
them and selects a bounded set of guest frames: a control (ABI 2 serves the scenery), refused frames, and frames whose conflict touches the left and the right margin or several cell rows. For each it writes, into --diag
(a LOCAL directory outside the repository; real-game pictures are never committed or uploaded): the ABI 1 and ABI 2 captures, a pixel-difference picture (strong magenta, ABI 1 dimmed), a root-cause conflict overlay and a
metadata record. An independent Python model of the ABI 1 scenery (re-implemented here from the game's work RAM, not from the C port) recomputes the conflicting cells and words and is compared with the instrumented log.
stdout is aggregate only."""
import argparse, json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import abi_parity_compare as apc

PROBE_GLOBALS = '''
static const SegaModHost *g_host;
static unsigned g_nconf, g_rows_hit, g_ntup;
static uint64_t g_hsum, g_hxor;
static int g_tup[6][4];
static struct ConfRow { unsigned n, n_l_l, n_r_r, n_l_r; int la0, la1, lb0, lb1, ka, kb, hsa, hsb, c0, c1, xa0, xa1, xb0, xb1; } g_cr[MAX_WIN_ROWS];
static int16_t g_ol[MAX_WIN_ROWS][SPAN_MAX];
static void put(char *b, int *n, int v) { char t[12]; int m = 0; unsigned u; if (v < 0) { b[(*n)++] = '-'; u = (unsigned)(-v); } else u = (unsigned)v; do { t[m++] = (char)('0' + u % 10U); u /= 10U; } while (u); while (m) b[(*n)++] = t[--m]; }
static uint64_t fnv4(int a, int b, int c, int d) { uint64_t h = 1469598103934665603ULL; const int v[4] = {a, b, c, d}; for (int i = 0; i < 4; ++i) for (int k = 0; k < 4; ++k) { h ^= (uint64_t)(((uint32_t)v[i] >> (8 * k)) & 0xFFU); h *= 1099511628211ULL; } return h; }
static void put_hex(char *b, int *n, uint64_t v) { for (int i = 15; i >= 0; --i) b[(*n)++] = "0123456789abcdef"[(v >> (4 * i)) & 15U]; }
static void puts_(char *b, int *n, const char *s) { while (*s) b[(*n)++] = *s++; }
'''


def probe_edit(text):
    """The instrumented copy: the same window builder, but conflicts are recorded and logged (never answered differently). Pure additions around the unchanged logic."""
    text = text.replace("static uint8_t g_hud_rgba[104U * 224U * 4U];\n", "static uint8_t g_hud_rgba[104U * 224U * 4U];\n" + PROBE_GLOBALS, 1)
    text = text.replace("  for (rr = 0; rr < rows; ++rr)\n    for (c = 0; c < span; ++c) g_cell[rr][c] = -1;\n",
                        "  for (rr = 0; rr < rows; ++rr)\n    for (c = 0; c < span; ++c) { g_cell[rr][c] = -1; g_ol[rr][c] = -1; }\n  g_nconf = 0U; g_rows_hit = 0U; g_ntup = 0U; g_hsum = 0U; g_hxor = 0U;\n  for (rr = 0; rr < (int)MAX_WIN_ROWS; ++rr) { struct ConfRow z = {0}; g_cr[rr] = z; }\n", 1)
    old = "        if (*o < 0) *o = word;\n        else if (*o != word) return 2;   /* one plane cell asked by two lines that need different words (per-line origins that differ by a multiple of 512) */\n"
    assert old in text
    new = '''        if (*o < 0) { *o = word; g_ol[row][c - cmin] = (int16_t)l; }
        else if (*o != word) {
          struct ConfRow *q = &g_cr[row];
          const unsigned la = (unsigned)g_ol[row][c - cmin];
          const int xa = 8 * c + f->hs[plane][la], xb = 8 * c + f->hs[plane][l];
          int ka = 0;
          { /* the owner's shift: recomputed from its line */ ka = (f->hs[plane][la] + off[la]) / 8; }
          if (q->n == 0U) { q->la0 = q->la1 = (int)la; q->lb0 = q->lb1 = (int)l; q->ka = ka; q->kb = k_[l]; q->hsa = f->hs[plane][la]; q->hsb = f->hs[plane][l]; q->c0 = q->c1 = c; q->xa0 = q->xa1 = xa; q->xb0 = q->xb1 = xb; ++g_rows_hit; }
          if ((int)la < q->la0) { q->la0 = (int)la; }
          if ((int)la > q->la1) { q->la1 = (int)la; }
          if ((int)l < q->lb0) { q->lb0 = (int)l; }
          if ((int)l > q->lb1) { q->lb1 = (int)l; }
          if (c < q->c0) { q->c0 = c; }
          if (c > q->c1) { q->c1 = c; }
          if (xa < q->xa0) { q->xa0 = xa; }
          if (xa > q->xa1) { q->xa1 = xa; }
          if (xb < q->xb0) { q->xb0 = xb; }
          if (xb > q->xb1) { q->xb1 = xb; }
          { const int la_left = xa + 8 <= 0, lb_left = xb + 8 <= 0; if (la_left && lb_left) { ++q->n_l_l; } else if (!la_left && !lb_left) { ++q->n_r_r; } else { ++q->n_l_r; } }
          { const int rho = rmin + row; const uint64_t hh = fnv4(rho, c, (int)*o, word); g_hsum += hh; g_hxor ^= hh; if (g_ntup < 6U) { g_tup[g_ntup][0] = rho; g_tup[g_ntup][1] = c; g_tup[g_ntup][2] = (int)*o; g_tup[g_ntup][3] = word; ++g_ntup; } }
          ++q->n; ++g_nconf;
        }
'''
    text = text.replace(old, new, 1)
    old_tail = "  windows = span > (int)MAX_COLS ? 2U : 1U;\n"
    log = '''  if (g_nconf != 0U && g_host != NULL && g_host->log != NULL) {
    char b[240]; int n = 0, shown = 0;
    puts_(b, &n, "S f="); put(b, &n, (int)g_host->frame); puts_(b, &n, " side="); put(b, &n, (int)margin_cells_probe); puts_(b, &n, " plane="); put(b, &n, (int)plane); puts_(b, &n, " n="); put(b, &n, (int)g_nconf);
    puts_(b, &n, " rows="); put(b, &n, (int)g_rows_hit); puts_(b, &n, " rmin="); put(b, &n, rmin); puts_(b, &n, " h="); put_hex(b, &n, g_hsum); puts_(b, &n, " x="); put_hex(b, &n, g_hxor); g_host->log(b, (uint32_t)n);
    n = 0; puts_(b, &n, "T f="); put(b, &n, (int)g_host->frame); puts_(b, &n, " t=");
    for (unsigned i = 0U; i < g_ntup; ++i) { if (i != 0U) b[n++] = ','; put(b, &n, g_tup[i][0]); b[n++] = ':'; put(b, &n, g_tup[i][1]); b[n++] = ':'; put(b, &n, g_tup[i][2]); b[n++] = ':'; put(b, &n, g_tup[i][3]); }
    g_host->log(b, (uint32_t)n);
    for (rr = 0; rr < rows && shown < 10; ++rr) if (g_cr[rr].n != 0U) {
      struct ConfRow *q = &g_cr[rr]; n = 0; ++shown;
      puts_(b, &n, "R f="); put(b, &n, (int)g_host->frame); puts_(b, &n, " p="); put(b, &n, (int)plane); puts_(b, &n, " r="); put(b, &n, rmin + rr); puts_(b, &n, " A="); put(b, &n, q->la0); puts_(b, &n, "-"); put(b, &n, q->la1);
      puts_(b, &n, " B="); put(b, &n, q->lb0); puts_(b, &n, "-"); put(b, &n, q->lb1); puts_(b, &n, " kA="); put(b, &n, q->ka); puts_(b, &n, " kB="); put(b, &n, q->kb); puts_(b, &n, " hA="); put(b, &n, q->hsa); puts_(b, &n, " hB="); put(b, &n, q->hsb);
      puts_(b, &n, " c="); put(b, &n, q->c0); puts_(b, &n, ".."); put(b, &n, q->c1); puts_(b, &n, " n="); put(b, &n, (int)q->n); puts_(b, &n, " xA="); put(b, &n, q->xa0); puts_(b, &n, ".."); put(b, &n, q->xa1);
      puts_(b, &n, " xB="); put(b, &n, q->xb0); puts_(b, &n, ".."); put(b, &n, q->xb1); puts_(b, &n, " LL="); put(b, &n, (int)q->n_l_l); puts_(b, &n, " RR="); put(b, &n, (int)q->n_r_r); puts_(b, &n, " LR="); put(b, &n, (int)q->n_l_r);
      g_host->log(b, (uint32_t)n);
    }
  }
  if (g_nconf != 0U) return 2;
'''
    text = text.replace(old_tail, log + old_tail, 1)
    text = text.replace("static int build_plane_windows(const SegaGenesisRenderApi *r,", "static unsigned margin_cells_probe;\nstatic int build_plane_windows(const SegaGenesisRenderApi *r,", 1)
    text = text.replace("  const unsigned right_px = 2U * margin_px - left_px;\n  const int *off", "  const unsigned right_px = 2U * margin_px - left_px;\n  margin_cells_probe = margin_px;\n  const int *off", 1)
    text = text.replace("  Sonic1Frame *f = &g_frame;\n", "  Sonic1Frame *f = &g_frame;\n  g_host = host;\n", 1)
    return text


def probe_manifest(m):
    return m.replace('required = [', 'required = ["host.log", ', 1) if '"host.log"' not in m else m


# ------------------------------------------------------------------ the independent model (from the game's work RAM only)
def u16(r, a):
    return (r[a & 0xFFFF] << 8) | r[(a + 1) & 0xFFFF]


def s16(r, a):
    v = u16(r, a)
    return v - 0x10000 if v & 0x8000 else v


def s10(v):
    v &= 0x3FF
    return v - 1024 if v & 0x200 else v


def world_cell(r, plane, cx, cy):
    if cx < 0 or cy < 0 or cx >= 0x4000 // 8 or cy >= 8 * 32:
        return 0
    x, y = cx * 8, cy * 8
    chunk = r[0xA400 + plane * 0x40 + (y >> 8) * 0x80 + (x >> 8)] & 0x7F
    if chunk == 0:
        return 0
    bw = u16(r, (chunk - 1) * 0x200 + (((y & 0xFF) >> 4) * 16 + ((x & 0xFF) >> 4)) * 2)
    block, fx, fy = bw & 0x3FF, (bw >> 11) & 1, (bw >> 12) & 1
    col, row = ((x & 15) >> 3) ^ fx, ((y & 15) >> 3) ^ fy
    word = u16(r, 0xB000 + block * 8 + (row * 2 + col) * 2)
    return word ^ (0x0800 if fx else 0) ^ (0x1000 if fy else 0)


def unwrap(v, ref, period):
    d = (v - ref) % period
    if d >= period // 2:
        d -= period
    return ref + d


def fnv4(a, b, c, d):
    """The same 64-bit FNV-1a digest of one (plane row, column, first word, second word) tuple as the instrumented port (each value as 4 little-endian bytes)."""
    h = 1469598103934665603
    for v in (a, b, c, d):
        for k in range(4):
            h ^= ((v & 0xFFFFFFFF) >> (8 * k)) & 0xFF
            h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def model_conflicts(r, side, plane=1):
    """Recomputes, from the RAM only, which plane cells the host asks (off-picture pixels only) with which world word per line, and returns the conflicts of one plane:
    {'rows': {plane_row: {...}}, 'cells': n, 'origin_ok': bool}."""
    camy, bgy, bgx, bg2x, split = u16(r, 0xF704), u16(r, 0xF70C), u16(r, 0xF708), u16(r, 0xF710), u16(r, 0xF7F0)
    owner, rows, cells, origin_ok = {}, {}, 0, True
    tuples, hsum, hxor = set(), 0, 0
    for l in range(224):
        ram = s16(r, 0xCC00 + l * 4 + (0 if plane == 0 else 2))
        hs = s10(ram)
        off = -ram if plane == 0 else unwrap(-ram, bg2x if l + bgy >= split else bgx, 512)
        if (hs + off) % 512:
            origin_ok = False
        k = (hs + off) // 8
        ycam = camy if plane == 0 else bgy
        rho = (l + ycam) // 8
        wrow = (l + ycam) // 8
        asked = list(range(-side, 0)) + list(range(320, 320 + side))
        seen = set()
        for x in asked:
            c = (x - hs) // 8
            if c in seen:
                continue
            seen.add(c)
            word = world_cell(r, plane, c + k, wrow)
            key = (rho, c)
            if key not in owner:
                owner[key] = (word, l, k, hs)
            elif owner[key][0] != word:
                o = owner[key]
                hh = fnv4(rho, c, o[0], word)
                hsum, hxor = (hsum + hh) & 0xFFFFFFFFFFFFFFFF, hxor ^ hh
                tuples.add((rho, c, o[0], word))
                e = rows.setdefault(rho, {"cells": 0, "lines_a": [o[1], o[1]], "lines_b": [l, l], "ka": o[2], "kb": k, "hsa": o[3], "hsb": hs, "cmin": c, "cmax": c, "example": None})
                e["cells"] += 1
                cells += 1
                e["lines_a"] = [min(e["lines_a"][0], o[1]), max(e["lines_a"][1], o[1])]
                e["lines_b"] = [min(e["lines_b"][0], l), max(e["lines_b"][1], l)]
                e["cmin"], e["cmax"] = min(e["cmin"], c), max(e["cmax"], c)
                if e["example"] is None:
                    e["example"] = {"cell": c, "row": rho, "word_a": o[0], "word_b": word, "world_cell_a": c + o[2], "world_cell_b": c + k}
    return {"rows": rows, "cells": cells, "origin_ok": origin_ok, "tuples": tuples, "hsum": "%016x" % hsum, "hxor": "%016x" % hxor}


MAX_LOGGED_ROWS = 10   # row lines the instrumented port prints per frame (see shown < 10 in the probe)


def exact_compare(rec, model):
    """Every conflict datum of the instrumented port against the independent model, for one frame: `rec` = the parsed log of the frame (None when the port logged no conflict), `model` = model_conflicts(...). Returns the list
    of disagreements (empty = exact): the number of conflicting cells, the plane rows, the order-independent digest of EVERY (plane row, column, first word, second word) tuple, and each tuple the port printed verbatim (it must be one
    of the model's, with the same two words)."""
    bad = []
    if rec is None or not rec.get("S"):
        if model["cells"] != 0:
            bad.append(f"the model finds {model['cells']} conflicting cells where the port logged none")
        return bad
    S = rec["S"]
    if model["cells"] != S["n"]:
        bad.append(f"cells: port {S['n']}, model {model['cells']}")
    logged = sorted(int(r["r"]) for r in rec["R"])
    expect = min(S["rows"], MAX_LOGGED_ROWS)   # the port prints at most this many row lines (a callback may log 16 lines)
    if S["rows"] != len(model["rows"]):
        bad.append(f"plane row count: port {S['rows']}, model {len(model['rows'])}")
    if len(logged) != expect or len(set(logged)) != len(logged):
        bad.append(f"row log incomplete or malformed: {len(logged)} distinct row lines logged, {expect} expected")
    if (S["rows"] <= MAX_LOGGED_ROWS and logged != sorted(model["rows"])) or not set(logged) <= set(model["rows"]):
        bad.append(f"plane row identities: port {logged}, model {sorted(model['rows'])}")
    if S.get("h") != model["hsum"] or S.get("x") != model["hxor"]:
        bad.append(f"digest of every conflicting (row, column, word, word) tuple: port {S.get('h')}/{S.get('x')}, model {model['hsum']}/{model['hxor']}")
    missing = [t for t in rec.get("T", []) if tuple(t) not in model["tuples"]]
    if missing or not rec.get("T"):
        bad.append(f"printed tuples not conflicts of the model: {missing[:3]}" if missing else "the port printed no explicit tuples")
    return bad


def model_samples(rams, side, rec):
    """The independent-model samples of one capture, one per available RAM lag (0 = the RAM of the captured frame, 1 = the previous onset, 2 = two earlier), for a conflict frame (`rec` = its log) and for a control frame
    (`rec` None: the model must find no conflict and the port logged none) alike, so the lag-1 requirement of manifest_failures is always satisfiable by a valid capture."""
    out = []
    for k, ram in enumerate(rams):
        m = model_conflicts(ram, side)
        problems = exact_compare(rec, m)
        out.append({"ram_lag": k, "cells": m["cells"], "plane_rows": sorted(m["rows"]), "origin_multiple_of_512": m["origin_ok"], "equals_instrumented_log": not problems, "disagreements": problems,
                    "example": next((v["example"] for v in m["rows"].values() if v["example"]), None)})
    return out


def manifest_failures(manifest):
    """What makes the diagnosis fail (hard): a capture whose two runs did not end on the requested guest frame, and a capture whose independent model disagrees with the instrumented port at the previous-onset RAM (lag 1;
    ADR 0320: the producer sees the work-RAM copy of the previous onset) in ANY datum of exact_compare. Exact 4:3 captures have no model (no margin cell is asked)."""
    failures = [f"{e['name']} ({e['aspect']}): guest frames differ between the runs or from the request" for e in manifest if not e["same_frame_identity"]]
    for e in manifest:
        m = e.get("independent_model")
        if not m:
            continue
        lag1 = next((x for x in m if x["ram_lag"] == 1), None)
        if lag1 is None or not lag1["equals_instrumented_log"]:
            failures.append(f"{e['name']} ({e['aspect']}, frame {e['requested_guest_frame']}): the independent model disagrees with the instrumented port at the previous-onset RAM: {(lag1 or {}).get('disagreements')}")
    return failures


def parse_log(lines):
    """MOD_LOG records of the instrumented port -> {frame: {'S': {...}, 'R': [ {...} ]}} (plane 1 only is ever in conflict)."""
    out = {}
    for m in lines:
        t = m.get("line", "")
        if t[:2] not in ("S ", "R ", "T "):
            continue
        kv = {k: v for k, v in (x.split("=", 1) for x in t[2:].split() if "=" in x)}
        f = int(kv["f"])
        rec = out.setdefault(f, {"S": None, "R": [], "T": []})
        if t[0] == "T":
            rec["T"] = [tuple(int(x) for x in q.split(":")) for q in kv.get("t", "").split(",") if q]
        elif t[0] == "S":
            rec["S"] = {k: (v if k in ("h", "x") else int(v)) for k, v in kv.items()}
        else:
            rec["R"].append({k: v for k, v in kv.items()})
    return out


def band_line_ranges(r, plane=1):
    """The parallax bands of the frame: consecutive lines with the same unwrapped scroll -> [(first, last, hs, off)]."""
    bgy, bgx, bg2x, split = u16(r, 0xF70C), u16(r, 0xF708), u16(r, 0xF710), u16(r, 0xF7F0)
    bands = []
    for l in range(224):
        ram = s16(r, 0xCC00 + l * 4 + 2)
        hs = s10(ram)
        off = unwrap(-ram, bg2x if l + bgy >= split else bgx, 512)
        if bands and bands[-1][2] == hs and bands[-1][3] == off:
            bands[-1][1] = l
        else:
            bands.append([l, l, hs, off])
    return bands


# ------------------------------------------------------------------ pictures
def picture_rect(rows, w, h):
    """The bounding rectangle of the non-black part of a capture (the picture inside the letterboxed window)."""
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        row = rows[y]
        if row.strip(b"\0"):
            xs = [x for x in range(w) if row[x * 3:x * 3 + 3] != b"\0\0\0"]
            x0, x1, y0, y1 = min(x0, xs[0]), max(x1, xs[-1]), min(y0, y), max(y1, y)
    return x0, y0, x1, y1


def overlay(abi1_bmp, rect_info, rows_hit, bands, side):
    """The ABI 1 capture dimmed, with the screen lines of every conflicting plane-cell row in colour: the line range of the first asker (cyan) and of the second asker (orange), and the margin columns of the conflicting cells
    as vertical ticks at the picture's edges (cyan/orange)."""
    w, h, rows = apc.bmp_to_rgb_rows(abi1_bmp)
    out = [bytearray(bytes(v // 2 for v in r)) for r in rows]
    x0, y0, x1, y1 = rect_info
    pw, ph = x1 - x0 + 1, y1 - y0 + 1
    sx, sy = pw / float(320 + 2 * side), ph / 224.0

    def paint(line_a, line_b, xa, xb, color):
        ya, yb = int(y0 + line_a * sy), min(h - 1, int(y0 + (line_b + 1) * sy))
        for y in range(max(0, ya), yb + 1):
            for x in range(xa, xb + 1):
                if 0 <= x < w:
                    px = out[y][x * 3:x * 3 + 3]
                    out[y][x * 3:x * 3 + 3] = bytes(color)   # opaque: the conflicting lines are the strongest thing in the picture
    left_x0, left_x1 = x0, int(x0 + side * sx)
    right_x0, right_x1 = int(x0 + (320 + side) * sx), x1
    for rw in rows_hit:
        (a0, a1), (b0, b1) = rw["A"], rw["B"]
        paint(a0, a1, left_x0, left_x1, (0, 255, 255))
        paint(a0, a1, right_x0, right_x1, (0, 255, 255))
        paint(b0, b1, left_x0, left_x1, (255, 140, 0))
        paint(b0, b1, right_x0, right_x1, (255, 140, 0))
    for b in bands:   # band boundaries: a thin white tick at both outer edges
        y = int(y0 + b[0] * sy)
        for x in list(range(x0, x0 + 6)) + list(range(x1 - 5, x1 + 1)):
            if 0 <= y < h:
                out[y][x * 3:x * 3 + 3] = b"\xff\xff\xff"
    return w, h, [bytes(r) for r in out]


def zoom(abi1_bmp, rect_info, lines, scale=6):
    """The conflicting screen lines (plus a few lines of context) of the ABI 1 picture magnified vertically: the full width of the extended picture, left and right margins included."""
    w, h, rows = apc.bmp_to_rgb_rows(abi1_bmp)
    x0, y0, x1, y1 = rect_info
    sy = (y1 - y0 + 1) / 224.0
    lo, hi = max(0, min(lines) - 8), min(223, max(lines) + 8)
    out = []
    for ly in range(lo, hi + 1):
        y = min(h - 1, int(y0 + (ly + 0.5) * sy))
        row = rows[y][x0 * 3:(x1 + 1) * 3]
        mark = (b"\xff\x00\xff" if ly in lines else b"")
        if mark:
            row = mark * 4 + row[12:-12] + mark * 4   # a magenta tick at both ends of every conflicting line
        out += [row] * scale
    return (x1 - x0 + 1), len(out), out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("--product-root", "--cli", "--sdl", "--cc", "--rom", "--work", "--diag"):
        ap.add_argument(k, required=True)
    ap.add_argument("--abi1", default="patches/genesis/sonic-1/native-widescreen")
    ap.add_argument("--abi2", default="patches/genesis/sonic-1/native-widescreen-abi2")
    ap.add_argument("--abi1-id", default="sonic1-native-widescreen")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    top = pathlib.Path(__file__).resolve().parent.parent
    diag = apc.require_outside_repo(a.diag, "--diag")
    apc.require_outside_repo(a.work, "--work")   # intermediate ROM images, captures, RAM snapshots and recordings of the real game
    diag.mkdir(parents=True, exist_ok=True)
    a.abi1, a.abi2 = str(top / a.abi1), str(top / a.abi2)
    c = apc.Cmp(a)
    c.diag = diag
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fs = [pool.submit(c.abi1_program), pool.submit(c.abi2_program, "abi2"), pool.submit(c.abi2_program, "probe", probe_edit, probe_manifest)]
        for f in fs:
            f.result()
    if c.failures:
        print(json.dumps({"ok": False, "failures": c.failures}))
        return 1
    pad = apc.level_pad([300, 700], 900, 4800) + ["5000 Q"]
    master = c.record("s1master", pad)   # frame-exact input for every run: the same recorded session is replayed in the ABI 1 and the ABI 2 program
    jobs = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for mode in ("wide", "w169"):
            for key in ("abi1", "abi2", "probe"):
                jobs[(key, mode)] = pool.submit(c.play, key, f"diag-{key}-{mode}", mode, pad, replay=master)
        runs = {k: f.result() for k, f in jobs.items()}
    summary, shifts = {}, {}
    for mode in ("wide", "w169"):
        r1, r2, rp = runs[("abi1", mode)], runs[("abi2", mode)], runs[("probe", mode)]
        t1, t2 = r1["trace"], r2["trace"]
        authored = [f for f in sorted(t1) if t1[f]["acc"] & 2]
        refused = [f for f in authored if not (t2[f]["acc"] & 2)]
        control = [f for f in authored if (t2[f]["acc"] & 2)]
        log = parse_log(rp["lines"].get("MOD_LOG", []))
        offs = [d for d in range(-3, 4) if sorted(f + d for f in refused) == sorted(log)]
        shifts[mode] = offs[0] if offs else None
        cells = sorted(int(v["S"]["n"]) for v in log.values() if v["S"])
        rows_hist = {}
        for v in log.values():
            if v["S"]:
                rows_hist[int(v["S"]["rows"])] = rows_hist.get(int(v["S"]["rows"]), 0) + 1
        diffs = sorted({8 * abs(int(r["kA"]) - int(r["kB"])) for v in log.values() for r in v["R"]})
        planes = sorted({int(v["S"]["plane"]) for v in log.values() if v["S"]})
        kinds = {"left_left": 0, "right_right": 0, "left_right": 0}
        for v in log.values():
            for r in v["R"]:
                kinds["left_left"] += 1 if int(r["LL"]) else 0
                kinds["right_right"] += 1 if int(r["RR"]) else 0
                kinds["left_right"] += 1 if int(r["LR"]) else 0
        shifts_stats = {"conflict_cells_per_frame": {"min": cells[0], "median": cells[len(cells) // 2], "max": cells[-1]} if cells else None, "frames_by_conflicting_plane_rows": rows_hist, "origin_differences_px": diffs, "planes_in_conflict": planes,
                        "conflict_rows_touching": kinds}
        summary[mode] = {"frames": len(t1), "abi1_scenery": len(authored), "abi2_scenery": len(control), "abi2_refused": len(refused), "logged_conflict_frames": len(log), "refused_equals_logged_with_frame_offset": offs, **shifts_stats}
    print(json.dumps({"ok": True, "aggregate": summary}, indent=1))
    if any(v is None for v in shifts.values()):
        print(json.dumps({"ok": False, "error": "the logged conflict frames are not the refused frames (no constant frame-number offset maps one onto the other)"}))
        return 1
    # the provider's `host->frame` numbers a produced frame one lower than the viewer trace (a constant offset, verified above): the log is re-keyed by the TRACE frame number
    c.runs, c.log_by_mode = runs, {m: {k - shifts[m]: v for k, v in parse_log(runs[("probe", m)]["lines"].get("MOD_LOG", [])).items()} for m in ("wide", "w169")}
    return select_and_capture(a, c, pad, diag)


def select_and_capture(a, c, pad, diag):
    runs, logs = c.runs, c.log_by_mode
    r1, r2 = runs[("abi1", "wide")], runs[("abi2", "wide")]
    t1, t2 = r1["trace"], r2["trace"]
    log = logs["wide"]
    authored = [f for f in sorted(t1) if t1[f]["acc"] & 2]
    control = [f for f in authored if t2[f]["acc"] & 2 and f not in log]

    def kinds(f):
        rows = log[f]["R"]
        ll = sum(int(r["LL"]) for r in rows); rr = sum(int(r["RR"]) for r in rows); lr = sum(int(r["LR"]) for r in rows)
        return ll, rr, lr
    conflicted = [f for f in authored if f in log and not (t2[f]["acc"] & 2)]
    picks = {}
    if control:
        picks["control-abi2-serves"] = control[len(control) // 2]
    if conflicted:
        picks["refused-first"] = conflicted[0]
        picks["refused-middle"] = conflicted[len(conflicted) // 2]
        lonly = sorted((f for f in conflicted if kinds(f)[0] > 0), key=lambda f: kinds(f)[0])
        ronly = sorted((f for f in conflicted if kinds(f)[1] > 0), key=lambda f: kinds(f)[1])
        lr = [f for f in conflicted if kinds(f)[2] > 0]
        multi = [f for f in conflicted if int(log[f]["S"]["rows"]) >= 2]
        if lonly:
            picks["conflict-left-margin"] = lonly[len(lonly) // 2]
        if ronly:
            picks["conflict-right-margin"] = ronly[len(ronly) // 2]
        if lr:
            picks["conflict-left-vs-right"] = lr[len(lr) // 2]
        if multi:
            picks["conflict-multiple-rows"] = multi[len(multi) // 2]
    # the run is ended by a scripted poll: calibrate the offset between the poll and the last traced guest frame once
    off = c.record("s1cal", apc.merge_pad(pad, [], 3000))[1] - 3000
    only_extra = ("control-abi2-serves", "refused-middle", "conflict-multiple-rows")
    jobs = [(name, frame, mode) for name, frame in picks.items() for mode in ("wide", "w169", "43") if mode == "wide" or name in only_extra]
    import concurrent.futures
    manifest = []

    def one(item):
        name, frame, mode = item
        end = frame - off
        ends = [end, end - 1, end - 2]
        recs = [c.record(f"s1p-{e}", apc.merge_pad(pad, [], e)) for e in ends]
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ends) + 1) as pool:
            fa = [pool.submit(c.play, "abi1", f"diag-{name}-{mode}-a1-{k}", mode, ["0 -"], replay=r) for k, r in enumerate(recs)]
            fb = pool.submit(c.play, "abi2", f"diag-{name}-{mode}-a2", mode, ["0 -"], replay=recs[0])
            ras, rb = [f.result() for f in fa], fb.result()
        return name, frame, mode, ras, rb
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs // 2)) as pool:
        outs = [f.result() for f in [pool.submit(one, j) for j in jobs]]
    for name, frame, mode, ras, rb in outs:
        ra = ras[0]
        entry = {"name": name, "aspect": mode, "requested_guest_frame": frame, "captured_guest_frame_abi1": ra["events"][-1][0], "captured_guest_frame_abi2": rb["events"][-1][0]}
        entry["same_frame_identity"] = entry["captured_guest_frame_abi1"] == entry["captured_guest_frame_abi2"] == frame
        d = apc.bmp_diff(ra["bmp"], rb["bmp"])
        entry.update({"geometry": [d["width"], d["height"]], "differing_pixels": d["differing"], "bbox": d["bbox"], "refused": not bool(rb["trace"].get(frame, {}).get("acc", 0) & 2), "verdict_abi1": list(ra["events"][-1][1:]), "verdict_abi2": list(rb["events"][-1][1:])})
        side = ra["trace"][frame]["side"]
        entry["side_px"] = side
        w, h, rows1 = apc.bmp_to_rgb_rows(ra["bmp"])
        rect = picture_rect(rows1, w, h)
        entry["picture_rectangle"] = list(rect)
        for tag, run in (("abi1", ra), ("abi2", rb)):
            apc.write_png(diag / f"{name}.{mode}.{tag}.png", *apc.bmp_to_rgb_rows(run["bmp"]))
        if d["geometry"]:
            apc.write_png(diag / f"{name}.{mode}.diff.png", *apc.diff_visual(ra["bmp"], rb["bmp"], d))
        lg = logs[("wide" if mode != "w169" else "w169")].get(frame) if mode != "43" else None
        rows_hit = []
        if lg:
            for rr in lg["R"]:
                la0, la1 = (int(x) for x in rr["A"].split("-")); lb0, lb1 = (int(x) for x in rr["B"].split("-"))
                rows_hit.append({"plane_row": int(rr["r"]), "A": (la0, la1), "B": (lb0, lb1), "kA": int(rr["kA"]), "kB": int(rr["kB"]), "hsA": int(rr["hA"]), "hsB": int(rr["hB"]), "cells": int(rr["n"]), "cols": rr["c"], "xA": rr["xA"], "xB": rr["xB"],
                                  "left_left": int(rr["LL"]), "right_right": int(rr["RR"]), "left_right": int(rr["LR"]), "world_origin_difference_px": 8 * abs(int(rr["kB"]) - int(rr["kA"]))})
            entry.update({"conflict_cells": int(lg["S"]["n"]), "conflict_plane_rows": int(lg["S"]["rows"]), "plane": int(lg["S"]["plane"]), "conflict_rows": rows_hit})
            bands = band_line_ranges(ras[0]["ram"])
            entry["parallax_bands"] = [{"lines": [b[0], b[1]], "hscroll": b[2], "world_origin_x": b[3]} for b in bands]
            ov = overlay(ra["bmp"], rect, rows_hit, bands, side)
            apc.write_png(diag / f"{name}.{mode}.conflict-overlay.png", *ov)
            hit_lines = set()
            for rw in rows_hit:
                for lo, hi in (rw["A"], rw["B"]):
                    hit_lines.update(range(lo, hi + 1))
            if hit_lines:
                apc.write_png(diag / f"{name}.{mode}.conflict-zoom-abi1.png", *zoom(ra["bmp"], rect, hit_lines))
                apc.write_png(diag / f"{name}.{mode}.conflict-zoom-abi2.png", *zoom(rb["bmp"], rect, hit_lines))
            # root-cause lines versus the larger fallback difference: how many differing pixels lie in the screen lines of the conflicting rows
            if d["geometry"] and d["differing"]:
                sy = (rect[3] - rect[1] + 1) / 224.0
                lines_hit = set()
                for rw in rows_hit:
                    for lo, hi in (rw["A"], rw["B"]):
                        lines_hit.update(range(lo, hi + 1))
                inside = sum(len(xs) for y, xs in d["mask"] if 0 <= int((y - rect[1]) / sy) < 224 and int((y - rect[1]) / sy) in lines_hit)
                entry["differing_pixels_in_conflicting_lines"] = inside
                entry["differing_pixels_elsewhere_fallback"] = d["differing"] - inside
            # the independent model: the RAM of the end of the guest frame before the view (candidate lags 0, 1, 2 of the captured run)
            matches = model_samples([rk["ram"] for rk in ras], side, lg)
            entry["independent_model"] = matches
        else:
            entry["independent_model"] = model_samples([rk["ram"] for rk in ras], side, None) if mode != "43" else None   # exact 4:3 presents no extension: the host asks no margin cell, there is nothing to model
        manifest.append(entry)
    (diag / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    lines = ["# Sonic 1 ABI 1 / ABI 2 scenery conflict: local diagnostics (real-game pictures: NEVER commit or upload)", "",
             "Files per capture `<name>.<aspect>.`: `abi1.png` (reference), `abi2.png` (current result), `diff.png` (ABI 1 dimmed, every differing pixel magenta, bounding rectangle yellow),",
             "`conflict-overlay.png` (ABI 1 dimmed; the screen lines of the first asker of each conflicting plane-cell row in cyan, of the second asker in orange, over both margins; white ticks at the picture edge mark parallax band boundaries),",
             "`conflict-zoom-abi1.png` / `conflict-zoom-abi2.png` (the conflicting lines +-8, magnified 6x vertically; magenta ticks mark the conflicting lines). `manifest.json` has the full records.", ""]
    for e in manifest:
        lines.append(f"## {e['name']} ({e['aspect']}), guest frame {e['requested_guest_frame']}")
        lines.append(f"* refused (ABI 2 scenery): {e['refused']}; differing pixels: {e['differing_pixels']} (bbox {e['bbox']}); in the conflicting lines: {e.get('differing_pixels_in_conflicting_lines')}, elsewhere (the generic fallback of the refused frame): {e.get('differing_pixels_elsewhere_fallback')}")
        for r in e.get("conflict_rows", []):
            lines.append(f"* plane {e.get('plane')} cell row {r['plane_row']}: lines {r['A'][0]}-{r['A'][1]} (hscroll {r['hsA']}, shift {r['kA']} cells) vs lines {r['B'][0]}-{r['B'][1]} (hscroll {r['hsB']}, shift {r['kB']} cells): world origins {r['world_origin_difference_px']} px apart; {r['cells']} conflicting cells (both askers in the left margin {r['left_left']}, both in the right {r['right_right']}, one in each {r['left_right']})")
        if e.get("independent_model"):
            lines.append("* independent model from the work RAM (RAM lag 0/1/2 frames): " + ", ".join(f"lag {x['ram_lag']}: {x['cells']} cells {'= log' if x['equals_instrumented_log'] else '!= log'}" for x in e["independent_model"]))
        lines.append("")
    (diag / "README.md").write_text("\n".join(lines))
    ok = all(e["same_frame_identity"] for e in manifest)
    failures = manifest_failures(manifest)
    ok = ok and not failures
    agg = {"frames_captured": len(manifest), "all_frame_identities_equal": ok,
           "model_agrees": sum(1 for e in manifest if e.get("independent_model") and any(x["equals_instrumented_log"] for x in e["independent_model"])),
           "model_checked": sum(1 for e in manifest if e.get("independent_model")),
           "matching_ram_lags": sorted({x["ram_lag"] for e in manifest for x in (e.get("independent_model") or []) if x["equals_instrumented_log"] and e.get("conflict_cells")}),
           "refused": sum(1 for e in manifest if e["refused"])}
    agg["failures"] = failures
    print(json.dumps(agg, indent=1))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps({"aggregate": agg}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
